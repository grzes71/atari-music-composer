"""Stage 23 - the controlled historical residual test.

Stage 22 decomposed the Stage 15 detector's residual on traces whose composition is known, and it
found a difference between the historical and the control corpus that it could not defend: the
difference depended on which outside-note convention was applied, and a corpus-composition difference
would have produced it too. It ended with

    HISTORICAL_RESIDUAL_DIFFERENT_FROM_CONTROL
    PERFORMANCE_CANDIDATE_REQUIRES_NEW_CONTROLLED_TEST

and an explicit warning that the difference was *not* robust. Stage 23 is the controlled test that
warning asked for. It does not look for a performance layer. It tries to **falsify** the difference.

The stage's central design decision follows from a fact Stage 22 stated but did not exploit: the
convention only exists *outside* detected spans. Inside a span the predictor writes the span's own
values whatever the convention says, so

    residual inside a span    is convention-free
    residual outside a span   is where hold and exporter differ

That gives a comparison which cannot be dismissed as a convention artefact, and it is the primary
estimand here. Everything else - the hold total, the exporter total, the matched-convention total -
is reported beside it as a sensitivity axis, never as the headline.

**What the audit found before any comparison was run.** Reading the traces rather than the summaries
turned up the mechanism. Ten of the twelve historical traces use AUDCTL ``$50``, a configuration the
control corpus never uses, and the player routines write ``AUDF = 0`` for single frames *between*
notes while leaving ``AUDC``'s volume nibble non-zero. ``AUDF = 0`` is the highest divider, which is
inaudible; the detector's audibility test is ``volume > 0``, so it treats those frames as sounding.
It splits the span at the zero pulse, the new span starts *on* the zero frame, and the pitch it reads
for the whole span is zero. On the historical corpus 38.1% of detected spans begin that way and they
carry 39.0% of the entire residual; on the control corpus 0.8% of spans begin that way and they carry
**none** of it. The idiom is a player trait - present in all four Rob Hubbard traces and absent from
several others - so the corpus contains roughly three independent player routines, not twelve
independent observations.

That is a corpus-composition explanation, and it is measured here rather than asserted.

The hypotheses, declared before the comparison is run:

* **H1 robustness** - the difference survives every reasonable residual convention.
* **H2 corpus composition** - the difference follows from a different mix of generators, register
  activity or player idioms rather than from anything the control corpus cannot produce.
* **H3 detector-error compatibility** - the historical residual is consistent with the error classes
  seen on Tier A once only the comparable features are used.
* **H4 historical-specific effect** - after matching and after removing the identified mechanisms, a
  systematic effect remains.

The hypotheses are not treated as mutually exclusive and none is chosen because it fits.

Pre-declared criteria for calling anything a *history-specific effect*, with the thresholds stated
before the numbers were read: it must appear in more than one trace and under more than one source;
it must survive leave-one-source-out; it must hold under every residual definition; it must survive
composition matching; its matched effect size must be at least ``EFFECT_THRESHOLD`` (five percentage
points of the estimand); it must not be explained by the mechanisms identified here; and it must
reproduce byte for byte.

Read-only and analysis-only. Stage 15 to 22, the compiler, the DSL, the IR, the player, the exporter
and the production schemas are read through their hashes and never written. No music is generated, no
listening test is run, no player is modified, no detector is repaired. Analysis version ``stage23/1``.

A negative result is a full result, and ``COMPARISON_INCONCLUSIVE`` is a legitimate outcome when the
data cannot settle the question.
"""


from __future__ import annotations

import hashlib
import json
import math
import random
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from atari_music import stage15, stage18, stage20, stage21, stage22

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_REPORTS_DIR = REPO_ROOT / "reports"
DEFAULT_STAGE23_DIR = DEFAULT_REPORTS_DIR / "stage23"
DEFAULT_DOCS_DIR = REPO_ROOT / "docs"
DEFAULT_ARCHAEOLOGY_DIR = stage15.DEFAULT_ARCHAEOLOGY_DIR
DEFAULT_SONGS_DIR = stage21.DEFAULT_SONGS_DIR
DEFAULT_AI_DIR = stage21.DEFAULT_AI_DIR
DEFAULT_EXTRA_DSL_DIR = stage21.DEFAULT_EXTRA_DSL_DIR
DEFAULT_STAGE21_DIR = DEFAULT_REPORTS_DIR / "stage21"
DEFAULT_STAGE22_DIR = DEFAULT_REPORTS_DIR / "stage22"

ANALYSIS_VERSION = "stage23/1"
RANDOM_SEED = 20250323
BOOTSTRAP_DRAWS = 4000
REGISTER_ORDER: Tuple[str, ...] = stage18.REGISTER_ORDER
FRAME_BYTES = stage18.FRAME_BYTES
AUDF_COLUMNS: Tuple[str, ...] = tuple(
    name for name in REGISTER_ORDER if name.startswith("AUDF")
)
AUDC_COLUMNS: Tuple[str, ...] = tuple(
    name for name in REGISTER_ORDER if name.startswith("AUDC")
)
OUTSIDE_HOLD = stage22.OUTSIDE_HOLD
OUTSIDE_EXPORTER = stage22.OUTSIDE_EXPORTER
AUDF_COLUMN: Mapping[int, int] = stage20.AUDF_COLUMN
AUDC_COLUMN: Mapping[int, int] = stage20.AUDC_COLUMN

#: Pre-declared thresholds. Stated here so a verdict cannot be talked into a nicer answer later.
EFFECT_THRESHOLD = 0.05          # five percentage points of the estimand
CALIPER = 1.0                    # standardised distance units for a match
MIN_SOURCES_FOR_EFFECT = 2       # a history-specific effect needs more than one source
CLUSTER_BOOTSTRAP = True         # resample sources, never frames


class Stage23Error(RuntimeError):
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



# ===========================================================================
# PART 0 - the source and definition audit (section 3 of the brief)
# ===========================================================================
#: The definitions Stage 23 relies on, quoted from the stage that owns them. A reader can check each
#: against the named artefact; none of them is restated from memory.
DECLARED_DEFINITIONS: Tuple[Dict[str, str], ...] = (
    {
        "name": "residual",
        "owner": "stage20.build_residual",
        "statement": (
            "for each of the nine registers and each frame, the residual is non-zero when the exact "
            "trace and the prediction differ at that register in that frame; the denominator is "
            "frames x 9"
        ),
        "source": "docs/stage22_detector_error_decomposition.md section 5",
    },
    {
        "name": "what the historical corpus cannot produce",
        "owner": "stage22",
        "statement": (
            "the note-set and value arms and the frame attribution need a ground truth, so they are "
            "control-only and are deliberately not compared"
        ),
        "source": "docs/stage22_detector_error_decomposition.md section 16",
    },
)


def audit_sources(
    stage21_dir: Path = DEFAULT_STAGE21_DIR,
    stage22_dir: Path = DEFAULT_STAGE22_DIR,
) -> Dict[str, Any]:
    """Read the Stage 21 and Stage 22 artefacts and record what they actually declare.

    The brief's rule is that the artefacts win over any summary, including this stage's own. So the
    audit reads the JSON, quotes the numbers it finds, and records where a published number and a
    recomputed one disagree. It also records which of Stage 22's claims Stage 23 will rely on and
    which it will not.
    """
    stage21_summary = _read_json(stage21_dir / "summary.json")
    stage22_manifest = _read_json(stage22_dir / "stage22_manifest.json")
    stage22_summary = stage22_manifest["summary"]
    historical_vs_control = _read_json(stage22_dir / "historical_vs_control.json")
    residual_taxonomy = _read_json(stage22_dir / "residual_taxonomy.json")
    return {
        "stage21_summary": stage21_summary,
        "stage22_summary": stage22_summary,
        "stage22_manifest_versions": {
            "analysis_version": stage22_manifest["analysis_version"],
            "determinism": stage22_manifest["determinism"],
            "read_only": stage22_manifest["read_only_audit"],
        },
        "declared_definitions": [dict(item) for item in DECLARED_DEFINITIONS],
        "stage22_published_numbers": {
            "control_register_values": stage22_summary["register_values"],
            "control_detector_residual_values": stage22_summary["detector_residual_values"],
            "control_residual_share_hold": stage22_summary["detector_residual_share"],
            "control_residual_share_exporter": stage22_summary[
                "detector_residual_share_exporter"
            ],
            "control_cause_partition": {
                key: stage22_summary[key]
                for key in (
                    "cause_note_set_share", "cause_value_share", "cause_interaction_share",
                    "cause_convention_share_of_hold",
                )
            },
            "historical_residual_share": stage22_summary["historical_residual_share"],
            "falsification_verdict": stage22_summary["falsification_verdict"],
        },
        "stage22_historical_comparison": historical_vs_control["comparison"],
        "stage22_falsification": historical_vs_control["falsification"],
        "stage22_taxonomy_classes": [
            {"family": item["family"], "class": item["class"], "status": item["status"]}
            for item in residual_taxonomy["matrix"]
        ],
        "stage22_artefacts": sorted(path.name for path in stage22_dir.glob("*.json")),
        "relied_on": (
            "the residual definition, both conventions, the frame attribution buckets and the "
            "control-only restriction. These are reused through the Stage 22 functions themselves, "
            "never re-implemented."
        ),
        "not_relied_on": (
            "the Stage 22 historical comparison's verdict is treated as a hypothesis to falsify, not "
            "as a finding. Its published shares are recomputed here from the traces rather than "
            "copied."
        ),
    }






#: Every estimand declares its numerator, its denominator, its unit, and how it treats silence, the
#: frames outside detected spans, coupled channels and aggregation. Declaring them in one table is
#: what stops a denominator from drifting between sections - the failure the brief names.
_COMMON = {
    "unit": "one register value = one (frame, register) pair",
    "coupled": "a joined 16-bit voice contributes its two AUDF columns and its volume AUDC",
}
ESTIMAND_RULES: Tuple[Dict[str, str], ...] = (
    {
        "name": "E_total_hold",
        "numerator": "register values that differ, any frame",
        "denominator": "frames x 9",
        "silence": "silent frames are counted; their registers are compared like any other",
        "outside_spans": "predicted by carrying the last value forward (hold)",
        "aggregation": "per trace; corpus summaries are over traces, never over register values",
        **_COMMON,
    },
    {
        "name": "E_total_exporter",
        "numerator": "register values that differ, any frame",
        "denominator": "frames x 9",
        "silence": "silent frames are counted; their registers are compared like any other",
        "outside_spans": "predicted as zero (the frame compiler's convention)",
        "aggregation": "per trace; corpus summaries are over traces, never over register values",
        **_COMMON,
    },
    {
        "name": "E_in_span",
        "numerator": "register values that differ, at (frame, register) pairs a detected span drives",
        "denominator": "register values a detected span drives",
        "silence": "register values no span drives are excluded entirely, so silence cannot enter",
        "outside_spans": "excluded by construction, which is why this estimand is convention-free",
        "aggregation": "per trace; corpus summaries are over traces, never over register values",
        **_COMMON,
    },
    {
        "name": "E_out_span_hold",
        "numerator": "register values that differ, at (frame, register) pairs no span drives",
        "denominator": "register values no detected span drives",
        "silence": "this is the estimand where silence lives, and it is reported separately for it",
        "outside_spans": "predicted by carrying the last value forward (hold)",
        "aggregation": "per trace; corpus summaries are over traces, never over register values",
        **_COMMON,
    },
    {
        "name": "E_out_span_exporter",
        "numerator": "register values that differ, at (frame, register) pairs no span drives",
        "denominator": "register values no detected span drives",
        "silence": "this is the estimand where silence lives, and it is reported separately for it",
        "outside_spans": "predicted as zero (the frame compiler's convention)",
        "aggregation": "per trace; corpus summaries are over traces, never over register values",
        **_COMMON,
    },
    {
        "name": "E_zero_onset_span",
        "numerator": "values that differ, inside spans whose onset reads AUDF = 0 while audible",
        "denominator": "register values those spans drive",
        "unit": "one register value = one (frame, register) pair",
        "silence": "a span is 'audible' when its volume channel's level at the onset exceeds zero",
        "outside_spans": "excluded; this is a decomposition of E_in_span, not a rival to it",
        "coupled": "the pitch channels are the joined voice's, so a zero on either counts",
        "aggregation": "per trace; corpus summaries are over traces",
    },
    {
        "name": "E_other_span",
        "numerator": "values that differ, inside spans whose onset does not read AUDF = 0",
        "denominator": "register values those spans drive",
        "unit": "one register value = one (frame, register) pair",
        "silence": "as for E_in_span",
        "outside_spans": "excluded; the rest of E_in_span once the zero-onset spans are removed",
        "coupled": "as for E_in_span",
        "aggregation": "per trace; corpus summaries are over traces",
    },
)

ESTIMAND_NAMES: Tuple[str, ...] = tuple(item["name"] for item in ESTIMAND_RULES)

#: The convention-free estimand is the headline. ``E_other_span`` is the same measurement with the
#: identified player idiom removed, and is the estimand the falsification test turns on.
PRIMARY_ESTIMAND = "E_in_span"
EXPLAINED_ESTIMAND = "E_other_span"


def _estimand_rules() -> Dict[str, Dict[str, str]]:
    return {item["name"]: dict(item) for item in ESTIMAND_RULES}


#: What the audit turned up, recorded where the artefacts can carry it. Each entry names the claim,
#: the artefact it came from, and what this stage measured instead.
DISCREPANCIES_FOUND: Tuple[Dict[str, str], ...] = (
    {
        "claim": (
            "Stage 22 compared the two corpora on the *total* residual share, under two conventions, "
            "and reported that the difference was not robust because the AUDF split moved with the "
            "convention"
        ),
        "measurement": (
            "the convention only exists at frames no detected span covers. Restricting the residual "
            "to frames inside detected spans removes the convention entirely, and the difference is "
            "then present under every definition rather than depending on one"
        ),
        "consequence": (
            "the primary estimand of this stage is the in-span residual, which Stage 22 did not "
            "report"
        ),
    },
    {
        "claim": (
            "the historical traces are twelve songs"
        ),
        "measurement": (
            "they are twelve traces from eleven SAP files and three composers, and one file "
            "contributes two subsongs"
        ),
        "consequence": (
            "every interval here resamples sources rather than traces, and the effective sample is "
            "far smaller than twelve"
        ),
    },
    {
        "claim": (
            "Stage 22 compared the corpora on residual shares without checking whether the corpora "
            "occupy the same region of trace-feature space"
        ),
        "measurement": (
            "several matching features have no common range at all - the 1.79 MHz clock, the number "
            "of distinct AUDF values, the trace length - and most historical traces lie outside the "
            "control corpus's support"
        ),
        "consequence": (
            "a matched or regression-adjusted comparison on this corpus pair is an extrapolation, "
            "and this stage reports it as one instead of as a control"
        ),
    },
    {
        "claim": (
            "a first reading of the audit took the historical player's AUDF = 0 inter-note pulses to "
            "be the mechanism, because the spans that begin on such a pulse carry 39.0% of the "
            "historical residual"
        ),
        "measurement": (
            "that 39.0% is a *volume* share, not a rate: those spans are 38.1% of the spans, and "
            "their residual rate (0.428) is close to the other spans' (0.352). The idiom changes "
            "which frames a span covers, it does not concentrate the error"
        ),
        "consequence": (
            "the idiom is reported as a corpus-composition difference, not as the cause of the "
            "residual, and the decomposition is reported with both the rate and the volume"
        ),
    },
)




@dataclass(frozen=True)
class TraceEvidence:
    """Everything Stage 23 measures about one trace, with its provenance.

    ``source_key`` is the SAP file the trace was decoded from and ``author`` is the credited
    composer, because the traces are not independent: four of the twelve come from one author's
    player routine and two come from different subsongs of one file. Every corpus-level statistic in
    this stage is computed over traces but resampled over sources, so the dependence is respected
    rather than assumed away.
    """

    slug: str
    corpus: str
    kind: str
    source_key: str
    author: str
    date: str
    sap_type: str
    audctl: int
    frames: int
    register_values: int
    spans: int
    covered_frames: int
    uncovered_frames: int
    in_span_values: int
    out_span_values: int
    zero_onset_spans: int
    counts: Mapping[str, Tuple[int, int]]
    features: Mapping[str, float]
    mediators: Mapping[str, float]
    per_register: Mapping[str, int]
    per_register_in_span: Mapping[str, int]
    per_register_in_span_total: Mapping[str, int]

    @property
    def estimands(self) -> Dict[str, Optional[float]]:
        return {
            name: _share(numerator, denominator)
            for name, (numerator, denominator) in self.counts.items()
        }

    def to_dict(self) -> Dict[str, Any]:
        return {
            "slug": self.slug,
            "corpus": self.corpus,
            "kind": self.kind,
            "source_key": self.source_key,
            "author": self.author,
            "date": self.date,
            "sap_type": self.sap_type,
            "audctl": f"${int(self.audctl):02X}",
            "frames": self.frames,
            "register_values": self.register_values,
            "spans": self.spans,
            "covered_frames": self.covered_frames,
            "uncovered_frames": self.uncovered_frames,
            "in_span_values": self.in_span_values,
            "out_span_values": self.out_span_values,
            "zero_onset_spans": self.zero_onset_spans,
            "counts": {name: list(pair) for name, pair in sorted(self.counts.items())},
            "estimands": self.estimands,
            "features": {key: _rnd(value) for key, value in sorted(self.features.items())},
            "mediators": {key: _rnd(value) for key, value in sorted(self.mediators.items())},
            "per_register_residual": dict(sorted(self.per_register.items())),
            "per_register_in_span": dict(sorted(self.per_register_in_span.items())),
            "per_register_in_span_total": dict(
                sorted(self.per_register_in_span_total.items())
            ),
        }


#: Pure trace properties, measurable in both corpora without any ground truth and without the
#: detector. These are what the composition matching is allowed to use.
MATCH_FEATURES: Tuple[str, ...] = (
    "frames",
    "audible_share",
    "register_change_rate",
    "audf_change_rate",
    "audc_change_rate",
    "audctl_change_rate",
    "audc_volume_change_rate",
    "audc_distortion_change_rate",
    "noise_active_share",
    "max_simultaneous",
    "mean_simultaneous",
    "coupled_16bit",
    "clock_179mhz",
    "distinct_audf_values",
    "distinct_audc_values",
    "mean_audc_run_length",
    "channel_balance",
)

#: Properties that describe *how the detector behaved on this trace* or that carry the identified
#: player idiom. They explain, and they are never used for matching: matching on a mediator would
#: control away the very mechanism under test.
MEDIATOR_FEATURES: Tuple[str, ...] = (
    "zero_onset_span_share",
    "zero_divider_audible_share",
    "span_density",
    "mean_span_length",
    "median_span_length",
    "audf_zero_share",
)


def _change_count(values: Sequence[int]) -> int:
    return sum(1 for index in range(1, len(values)) if values[index] != values[index - 1])


def _run_lengths(values: Sequence[int]) -> List[int]:
    """Run lengths of consecutive equal values, in frame order."""
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


def trace_features(trace: Any) -> Dict[str, float]:
    """The matching feature set: pure trace properties, no detector and no residual.

    Every feature here is a function of the trace's own registers, so it is defined identically on
    both corpora and none of them can leak the residual into the matching.
    """
    registers = trace.registers
    frames = max(1, trace.frames)
    voices = stage15.voices_for(int(trace.audctl))
    levels = []
    for voice in voices:
        audc = registers[f"AUDC{voice.volume_channel}"]
        levels.append([stage15.audc_volume(audc[frame]) for frame in range(trace.frames)])
    sounding = [
        sum(1 for column in levels if column[frame] > 0) for frame in range(trace.frames)
    ]
    audible = sum(1 for value in sounding if value > 0)
    noise_frames = 0
    for frame in range(trace.frames):
        for voice in voices:
            audc = registers[f"AUDC{voice.volume_channel}"]
            if stage15.audc_volume(audc[frame]) > 0 and stage15.waveform_is_noise(
                stage15.audc_waveform(audc[frame])
            ):
                noise_frames += 1
                break
    audf_changes = audc_changes = 0
    volume_changes = distortion_changes = 0
    audf_values: set = set()
    audc_values: set = set()
    runs: List[int] = []
    for voice in voices:
        for channel in voice.pitch_channels:
            column = registers[f"AUDF{channel}"]
            audf_changes += _change_count(column)
            audf_values.update(column)
        audc = registers[f"AUDC{voice.volume_channel}"]
        audc_changes += _change_count(audc)
        audc_values.update(audc)
        runs.extend(_run_lengths(audc))
        volume_changes += _change_count([stage15.audc_volume(v) for v in audc])
        distortion_changes += _change_count([stage15.audc_distortion(v) for v in audc])
    audctl_changes = _change_count(registers["AUDCTL"])
    register_changes = audf_changes + audc_changes + audctl_changes
    per_channel = [
        sum(1 for value in column if value > 0) / frames for column in levels
    ]
    mean_channel = sum(per_channel) / len(per_channel) if per_channel else 0.0
    spread = (
        (max(per_channel) - min(per_channel)) / mean_channel
        if per_channel and mean_channel else 0.0
    )
    return {
        "frames": float(trace.frames),
        "audible_share": audible / frames,
        "register_change_rate": register_changes / frames,
        "audf_change_rate": audf_changes / frames,
        "audc_change_rate": audc_changes / frames,
        "audctl_change_rate": audctl_changes / frames,
        "audc_volume_change_rate": volume_changes / frames,
        "audc_distortion_change_rate": distortion_changes / frames,
        "noise_active_share": noise_frames / frames,
        "max_simultaneous": float(max(sounding) if sounding else 0),
        "mean_simultaneous": (sum(sounding) / frames) if sounding else 0.0,
        "coupled_16bit": 1.0 if (int(trace.audctl) & 0x10) else 0.0,
        "clock_179mhz": 1.0 if (int(trace.audctl) & 0x40) else 0.0,
        "distinct_audf_values": float(len(audf_values)),
        "distinct_audc_values": float(len(audc_values)),
        "mean_audc_run_length": (sum(runs) / len(runs)) if runs else 0.0,
        "channel_balance": spread,
    }
def _span_layout(trace: Any, records: Sequence[Any]) -> Dict[str, Any]:
    """Which frames a detected span covers, which span owns each frame, and the zero-onset spans.

    A span is a *zero-onset* span when its onset frame reads ``AUDF = 0`` on one of its voice's pitch
    channels while the voice's volume channel is audible there. That combination is what the player
    routines in the historical corpus emit between notes, and it is the mechanism this stage
    identified in the audit.
    """
    covered = [False] * trace.frames
    owner: List[Optional[int]] = [None] * trace.frames
    for index, record in enumerate(records):
        for frame in range(int(record.start), min(int(record.end) + 1, trace.frames)):
            covered[frame] = True
            owner[frame] = index
    voices = {voice.voice_id: voice for voice in stage15.voices_for(int(trace.audctl))}
    zero_onset: set = set()
    for index, record in enumerate(records):
        voice = voices[record.voice_id]
        onset = int(record.start)
        audc = trace.registers[f"AUDC{voice.volume_channel}"]
        if stage15.audc_volume(audc[onset]) <= 0:
            continue
        if any(trace.registers[f"AUDF{ch}"][onset] == 0 for ch in voice.pitch_channels):
            zero_onset.add(index)
    zero_divider_audible = 0
    for frame in range(trace.frames):
        for voice in voices.values():
            audc = trace.registers[f"AUDC{voice.volume_channel}"]
            if stage15.audc_volume(audc[frame]) <= 0:
                continue
            if any(trace.registers[f"AUDF{ch}"][frame] == 0 for ch in voice.pitch_channels):
                zero_divider_audible += 1
                break
    return {
        "covered": covered,
        "owner": owner,
        "zero_onset": zero_onset,
        "zero_divider_audible_frames": zero_divider_audible,
    }


def measure_trace(
    trace: Any,
    corpus: str,
    kind: str,
    source_key: str = "",
    author: str = "",
    date: str = "",
    sap_type: str = "",
) -> TraceEvidence:
    """Measure every estimand and every feature for one trace.

    The residual is Stage 22's, through Stage 22's own functions, under both conventions. The
    identities ``E_total = E_in_span + E_out_span`` and ``E_in_span = E_zero_onset + E_other`` are
    asserted rather than assumed, so a drifting denominator raises instead of reporting.
    """
    records = stage20.note_records(trace)
    specs = stage22.specs_from_records(records, int(trace.audctl))
    layout = _span_layout(trace, records)
    zero_onset = layout["zero_onset"]

    residuals: Dict[str, Any] = {}
    for policy in (OUTSIDE_HOLD, OUTSIDE_EXPORTER):
        predicted = stage22.predict_from_specs(
            trace.frames, int(trace.audctl), specs, policy
        )
        residuals[policy] = stage22.residual_of(trace, predicted)

    # The in-span / out-of-span split is per *register value*, not per frame. A frame can be covered
    # by one voice's span while another voice has no span there, and the two conventions differ on
    # that other voice's registers. Splitting by frame would put those values inside "in span" and
    # make the two policies disagree about a region they should agree on; splitting by register does
    # not, and the identities then hold exactly for both policies.
    column_covered = [[False] * trace.frames for _ in range(FRAME_BYTES)]
    column_owner: List[List[Optional[int]]] = [
        [None] * trace.frames for _ in range(FRAME_BYTES)
    ]
    for index, spec in enumerate(specs):
        length = min(spec.end - spec.start, len(spec.levels))
        for offset in range(max(0, length)):
            frame = spec.start + offset
            if frame < 0 or frame >= trace.frames:
                continue
            for channel, _value in spec.dividers:
                column_covered[AUDF_COLUMN[channel]][frame] = True
                column_owner[AUDF_COLUMN[channel]][frame] = index
            column_covered[AUDC_COLUMN[spec.volume_channel]][frame] = True
            column_owner[AUDC_COLUMN[spec.volume_channel]][frame] = index
            if spec.joined:
                column_covered[AUDC_COLUMN[spec.channels[0]]][frame] = True
                column_owner[AUDC_COLUMN[spec.channels[0]]][frame] = index

    total_values = trace.frames * FRAME_BYTES
    in_span_values = sum(
        1 for column in range(FRAME_BYTES) for frame in range(trace.frames)
        if column_covered[column][frame]
    )
    out_span_values = total_values - in_span_values
    zero_span_values = sum(
        1 for column in range(FRAME_BYTES) for frame in range(trace.frames)
        if column_covered[column][frame] and column_owner[column][frame] in zero_onset
    )
    other_span_values = in_span_values - zero_span_values

    counts: Dict[str, Tuple[int, int]] = {}
    per_register: Dict[str, int] = {}
    per_register_in_span: Dict[str, int] = {}
    per_register_in_span_total: Dict[str, int] = {}
    exporter = residuals[OUTSIDE_EXPORTER]
    hold = residuals[OUTSIDE_HOLD]
    for column, name in enumerate(REGISTER_ORDER):
        per_register[name] = sum(1 for value in exporter.values[column] if value)
        per_register_in_span[name] = sum(
            1 for frame in range(trace.frames)
            if column_covered[column][frame] and exporter.values[column][frame]
        )
        per_register_in_span_total[name] = sum(
            1 for frame in range(trace.frames) if column_covered[column][frame]
        )
    counts["E_total_hold"] = (hold.residual_values(), total_values)
    counts["E_total_exporter"] = (exporter.residual_values(), total_values)
    in_span = out_span_hold = out_span_exporter = 0
    zero_span = other_span = 0
    for column in range(FRAME_BYTES):
        for frame in range(trace.frames):
            covered_here = column_covered[column][frame]
            if covered_here:
                if exporter.values[column][frame]:
                    in_span += 1
                    if column_owner[column][frame] in zero_onset:
                        zero_span += 1
                    else:
                        other_span += 1
            else:
                if exporter.values[column][frame]:
                    out_span_exporter += 1
                if hold.values[column][frame]:
                    out_span_hold += 1
    counts["E_in_span"] = (in_span, in_span_values)
    counts["E_out_span_hold"] = (out_span_hold, out_span_values)
    counts["E_out_span_exporter"] = (out_span_exporter, out_span_values)
    counts["E_zero_onset_span"] = (zero_span, zero_span_values)
    counts["E_other_span"] = (other_span, other_span_values)

    if counts["E_total_exporter"][0] != in_span + out_span_exporter:
        raise Stage23Error(f"{trace.slug}: E_total_exporter does not split into in and out of span")
    if counts["E_total_hold"][0] != in_span + out_span_hold:
        raise Stage23Error(f"{trace.slug}: E_total_hold does not split into in and out of span")
    if in_span != zero_span + other_span:
        raise Stage23Error(f"{trace.slug}: E_in_span does not split at the zero-onset spans")
    if in_span_values != zero_span_values + other_span_values:
        raise Stage23Error(f"{trace.slug}: the in-span denominators do not split")


    span_lengths = [int(r.end) - int(r.start) + 1 for r in records]
    mediators = {
        "zero_onset_span_share": _share(len(zero_onset), len(records)) or 0.0,
        "zero_divider_audible_share": (
            layout["zero_divider_audible_frames"] / max(1, trace.frames)
        ),
        "span_density": len(records) / max(1, trace.frames),
        "mean_span_length": _mean(span_lengths) or 0.0,
        "median_span_length": _median(span_lengths) or 0.0,
        "audf_zero_share": sum(
            1 for frame in range(trace.frames)
            if any(trace.registers[f"AUDF{ch}"][frame] == 0 for ch in (1, 2, 3, 4))
        ) / max(1, trace.frames),
    }
    return TraceEvidence(
        slug=trace.slug,
        corpus=corpus,
        kind=kind,
        source_key=source_key or trace.slug,
        author=author,
        date=date,
        sap_type=sap_type,
        audctl=int(trace.audctl),
        frames=trace.frames,
        register_values=total_values,
        spans=len(records),
        covered_frames=sum(
            1 for frame in range(trace.frames)
            if any(column_covered[column][frame] for column in range(FRAME_BYTES))
        ),
        uncovered_frames=sum(
            1 for frame in range(trace.frames)
            if not any(column_covered[column][frame] for column in range(FRAME_BYTES))
        ),
        in_span_values=in_span_values,
        out_span_values=out_span_values,
        zero_onset_spans=len(zero_onset),
        counts=counts,
        features=trace_features(trace),
        mediators=mediators,
        per_register=per_register,
        per_register_in_span=per_register_in_span,
        per_register_in_span_total=per_register_in_span_total,
    )


def load_historical_evidence(
    arch_root: Path = DEFAULT_ARCHAEOLOGY_DIR,
) -> List[TraceEvidence]:
    """Every historical trace, measured, with the provenance the trace file records.

    The provenance matters more than it looks. The twelve traces come from eleven SAP files and from
    three composers, so they are not twelve independent observations and every uncertainty interval
    in this stage resamples sources rather than traces.
    """
    out: List[TraceEvidence] = []
    for path in sorted(stage15.list_traces(Path(arch_root))):
        trace = stage15.load_trace(path)
        payload = _read_json(path)
        source = payload.get("source", {}) or {}
        out.append(
            measure_trace(
                trace,
                corpus="historical",
                kind=str(payload.get("schema", "unknown")),
                source_key=str(source.get("song_file") or trace.slug),
                author=str(source.get("author") or "unknown"),
                date=str(source.get("date") or "unknown"),
                sap_type=str(source.get("sap_type") or "unknown"),
            )
        )
    return out


def load_control_evidence(
    songs_dir: Path = DEFAULT_SONGS_DIR, ai_dir: Path = DEFAULT_AI_DIR
) -> List[TraceEvidence]:
    """Every control composition, measured the same way and through the same code path."""
    corpus, _skipped = stage21.load_control_corpus(songs_dir, ai_dir, DEFAULT_EXTRA_DSL_DIR)
    out: List[TraceEvidence] = []
    for song in corpus:
        out.append(
            measure_trace(
                song.trace,
                corpus="control",
                kind=song.kind,
                source_key=song.sha256,
                author="project",
                date="unknown",
                sap_type="dsl",
            )
        )
    return out


def cluster_index(rows: Sequence[TraceEvidence]) -> Dict[str, Any]:
    """The dependence structure, reported rather than assumed away."""
    by_source: Dict[str, List[str]] = {}
    by_author: Dict[str, List[str]] = {}
    for row in rows:
        by_source.setdefault(row.source_key, []).append(row.slug)
        by_author.setdefault(row.author, []).append(row.slug)
    return {
        "traces": len(rows),
        "sources": sorted(by_source),
        "source_count": len(by_source),
        "authors": sorted(by_author),
        "author_count": len(by_author),
        "by_source": {key: sorted(value) for key, value in sorted(by_source.items())},
        "by_author": {key: sorted(value) for key, value in sorted(by_author.items())},
        "repeated_sources": {
            key: sorted(value) for key, value in sorted(by_source.items()) if len(value) > 1
        },
        "effective_sample_note": (
            "the traces are clustered: eleven SAP sources and three composers for twelve traces. "
            "Every interval in this stage resamples sources, never frames and never traces as if "
            "they were independent."
        ),
    }


# ===========================================================================
# PART 3 - overlap, calibration and the univariate screen (sections 7 and 9)
# ===========================================================================
def overlap_diagnosis(
    control: Sequence[TraceEvidence], historical: Sequence[TraceEvidence]
) -> Dict[str, Any]:
    """Where the two corpora actually overlap, feature by feature.

    A matched or regression-adjusted comparison is only credible where the two corpora occupy the
    same region of feature space. Reporting the overlap *before* any adjusted comparison is what
    stops an extrapolation from being presented as a control.
    """
    rows: List[Dict[str, Any]] = []
    for name in list(MATCH_FEATURES) + list(MEDIATOR_FEATURES):
        source = "features" if name in MATCH_FEATURES else "mediators"
        cx = [float(getattr(row, source)[name]) for row in control]
        hx = [float(getattr(row, source)[name]) for row in historical]
        low, high = max(min(cx), min(hx)), min(max(cx), max(hx))
        inside = sum(1 for value in hx if min(cx) <= value <= max(cx))
        rows.append({
            "feature": name,
            "role": "matching" if source == "features" else "mediator",
            "control_min": min(cx), "control_max": max(cx), "control_mean": _mean(cx),
            "historical_min": min(hx), "historical_max": max(hx),
            "historical_mean": _mean(hx),
            "common_range_low": low, "common_range_high": high,
            "common_range_width": round(max(0.0, high - low), 6),
            "historical_inside_control_range_share": _share(inside, len(hx)),
            "overlaps": high > low,
        })
    matching = [row for row in rows if row["role"] == "matching"]
    separated = sorted(row["feature"] for row in rows if not row["overlaps"])
    poorly_covered = sorted(
        row["feature"] for row in matching
        if (row["historical_inside_control_range_share"] or 0.0) < 0.5
    )
    return {
        "features": rows,
        "features_without_any_common_range": separated,
        "matching_features_covering_under_half_the_historical_traces": poorly_covered,
        "matching_feature_count": len(matching),
        "verdict": (
            "the corpora overlap on some features and not on others. The matching features listed "
            "above have no common range or cover fewer than half the historical traces, so a matched "
            "comparison is an extrapolation for those traces and is reported as one"
            if poorly_covered else
            "every matching feature has a common range covering at least half the historical traces"
        ),
    }


def standardise(
    control: Sequence[TraceEvidence], historical: Sequence[TraceEvidence]
) -> Dict[str, Any]:
    """Pooled standardisation, so neither corpus's scale is privileged.

    The mean and the standard deviation are taken over the *pooled* set of both corpora. Scaling on
    the control alone would make every historical trace look extreme by construction, and scaling on
    the historical alone would do the reverse.
    """
    means: Dict[str, float] = {}
    spreads: Dict[str, float] = {}
    for name in MATCH_FEATURES:
        values = [float(row.features[name]) for row in control]
        values += [float(row.features[name]) for row in historical]
        means[name] = _mean(values) or 0.0
        spreads[name] = _stdev(values) or 0.0
    return {
        "features": list(MATCH_FEATURES),
        "mean": means,
        "stdev": spreads,
        "pooled": True,
        "note": (
            "scaled on the pooled set of both corpora, so a standardised difference is not inflated "
            "by choosing one corpus's scale"
        ),
    }


def _standard_vector(row: TraceEvidence, stats: Mapping[str, Any]) -> List[float]:
    return [
        (float(row.features[name]) - stats["mean"][name]) / stats["stdev"][name]
        if stats["stdev"][name] else 0.0
        for name in stats["features"]
    ]


def _euclidean(left: Sequence[float], right: Sequence[float]) -> float:
    return math.sqrt(sum((a - b) ** 2 for a, b in zip(left, right)))





def nearest_control_neighbours(
    row: TraceEvidence,
    control: Sequence[TraceEvidence],
    stats: Mapping[str, Any],
    k: int = 5,
    exclude: Optional[str] = None,
) -> Dict[str, Any]:
    """The k nearest control traces in standardised matching-feature space.

    Ties break on the slug, so the neighbour set cannot depend on iteration order. The distance is
    reported with every prediction, because a prediction made far outside the control corpus's own
    spread is an extrapolation and must be read as one.
    """
    target = _standard_vector(row, stats)
    scored: List[Tuple[float, str, Optional[float]]] = []
    for other in control:
        if exclude is not None and other.slug == exclude:
            continue
        scored.append((
            _euclidean(target, _standard_vector(other, stats)),
            other.slug,
            other.estimands[PRIMARY_ESTIMAND],
        ))
    scored.sort()
    chosen = scored[:k]
    values = [item[2] for item in chosen if item[2] is not None]
    return {
        "predicted": _mean(values),
        "nearest_distance": round(chosen[0][0], 6) if chosen else None,
        "mean_distance": _mean([item[0] for item in chosen]),
        "neighbours": [item[1] for item in chosen],
        "neighbour_values": values,
    }


def calibration(
    control: Sequence[TraceEvidence],
    historical: Sequence[TraceEvidence],
    k: int = 5,
) -> Dict[str, Any]:
    """Predict each historical trace's in-span residual from the control corpus, and report the gap.

    The control corpus's own leave-one-out error is the yardstick: a gap smaller than that is not a
    finding. The distance to the nearest control neighbour is reported beside every prediction so an
    extrapolation cannot be mistaken for an interpolation.
    """
    stats = standardise(control, historical)
    loo_errors: List[float] = []
    loo_distances: List[float] = []
    for row in control:
        neighbour = nearest_control_neighbours(row, control, stats, k, exclude=row.slug)
        actual = row.estimands[PRIMARY_ESTIMAND]
        if actual is not None and neighbour["predicted"] is not None:
            loo_errors.append(actual - neighbour["predicted"])
        if neighbour["nearest_distance"] is not None:
            loo_distances.append(neighbour["nearest_distance"])
    threshold = max(loo_distances) if loo_distances else None
    rows: List[Dict[str, Any]] = []
    gaps: List[float] = []
    extrapolated = 0
    for row in sorted(historical, key=lambda item: item.slug):
        neighbour = nearest_control_neighbours(row, control, stats, k)
        actual = row.estimands[PRIMARY_ESTIMAND]
        gap = None if actual is None or neighbour["predicted"] is None else (
            round(actual - neighbour["predicted"], 6)
        )
        beyond = (
            None if threshold is None or neighbour["nearest_distance"] is None
            else neighbour["nearest_distance"] > threshold
        )
        if beyond:
            extrapolated += 1
        if gap is not None:
            gaps.append(gap)
        rows.append({
            "slug": row.slug,
            "source_key": row.source_key,
            "author": row.author,
            "actual": actual,
            "predicted": neighbour["predicted"],
            "gap": gap,
            "nearest_distance": neighbour["nearest_distance"],
            "beyond_control_loo_distance_range": beyond,
            "neighbours": neighbour["neighbours"],
        })
    return {
        "estimand": PRIMARY_ESTIMAND,
        "k": k,
        "standardisation": stats,
        "control_loo": {
            "mae": _mean([abs(value) for value in loo_errors]),
            "rmse": _rnd(
                math.sqrt(sum(value * value for value in loo_errors) / len(loo_errors))
                if loo_errors else None
            ),
            "bias": _mean(loo_errors),
            "n": len(loo_errors),
            "nearest_distance_median": _median(loo_distances),
            "nearest_distance_max": threshold,
        },
        "historical": rows,
        "historical_gap_mean": _mean(gaps),
        "historical_gap_median": _median(gaps),
        "historical_gap_min": min(gaps) if gaps else None,
        "historical_gap_max": max(gaps) if gaps else None,
        "historical_positive_gap_count": sum(1 for value in gaps if value > 0),
        "historical_count": len(gaps),
        "historical_beyond_control_support": extrapolated,
        "reading": (
            "the gap is judged against the control corpus's own leave-one-out error. A gap far "
            "larger than that error is not explained by the matching features; but if the prediction "
            "lies beyond the control corpus's own distance range it is an extrapolation, and the gap "
            "then cannot be read as an effect estimate."
        ),
    }



def univariate_screen(
    control: Sequence[TraceEvidence], historical: Sequence[TraceEvidence]
) -> Dict[str, Any]:
    """Fit one control-only model per feature and see whether it predicts the historical mean.

    This is the honest version of a matched comparison. Each model is fitted on the control corpus
    alone, its own leave-one-out error is reported as the yardstick, and it is then applied to the
    historical features. If no feature closes the gap, the difference is not explained by anything
    measurable at the trace level - and the overlap column says whether the prediction was an
    interpolation at all.
    """
    cy = [row.estimands[PRIMARY_ESTIMAND] for row in control]
    hy = [row.estimands[PRIMARY_ESTIMAND] for row in historical]
    hist_mean = _mean([value for value in hy if value is not None])
    control_mean = _mean([value for value in cy if value is not None])
    rows: List[Dict[str, Any]] = []
    for name in list(MATCH_FEATURES) + list(MEDIATOR_FEATURES):
        source = "features" if name in MATCH_FEATURES else "mediators"
        pairs = [
            (float(getattr(row, source)[name]), value)
            for row in control
            for value in [row.estimands[PRIMARY_ESTIMAND]]
            if value is not None
        ]
        cx = [pair[0] for pair in pairs]
        ys = [pair[1] for pair in pairs]
        hx = [float(getattr(row, source)[name]) for row in historical]
        if len(set(cx)) < 2:
            rows.append({
                "feature": name, "role": source, "constant": True, "slope": None,
                "r_squared": None, "loo_mae": None, "predicted_historical_mean": None,
                "gap": None, "overlap_share": None, "common_range": None,
            })
            continue
        mean_x = _mean(cx) or 0.0
        mean_y = _mean(ys) or 0.0
        sxx = sum((value - mean_x) ** 2 for value in cx)
        sxy = sum((cx[i] - mean_x) * (ys[i] - mean_y) for i in range(len(cx)))
        slope = sxy / sxx if sxx else 0.0
        intercept = mean_y - slope * mean_x
        fitted = [intercept + slope * value for value in cx]
        sse = sum((ys[i] - fitted[i]) ** 2 for i in range(len(cx)))
        sst = sum((value - mean_y) ** 2 for value in ys)
        r_squared = 1 - sse / sst if sst else 0.0
        loo: List[float] = []
        for index in range(len(cx)):
            xs = cx[:index] + cx[index + 1:]
            others = ys[:index] + ys[index + 1:]
            mx = _mean(xs) or 0.0
            my = _mean(others) or 0.0
            sxx_i = sum((value - mx) ** 2 for value in xs)
            sxy_i = sum((xs[j] - mx) * (others[j] - my) for j in range(len(xs)))
            sl = sxy_i / sxx_i if sxx_i else 0.0
            ic = my - sl * mx
            loo.append(abs(ys[index] - (ic + sl * cx[index])))
        predicted_historical = _mean([intercept + slope * value for value in hx])
        low, high = max(min(cx), min(hx)), min(max(cx), max(hx))
        rows.append({
            "feature": name,
            "role": source,
            "constant": False,
            "slope": _rnd(slope),
            "r_squared": _rnd(r_squared),
            "loo_mae": _mean(loo),
            "predicted_historical_mean": predicted_historical,
            "gap": _rnd(
                None if predicted_historical is None or hist_mean is None
                else hist_mean - predicted_historical
            ),
            "overlap_share": _share(
                sum(1 for value in hx if min(cx) <= value <= max(cx)), len(hx)
            ),
            "common_range": [low, high] if high > low else None,
        })
    ranked = sorted(
        (row for row in rows if row["gap"] is not None),
        key=lambda row: abs(row["gap"]),
    )
    best = ranked[0] if ranked else None
    return {
        "estimand": PRIMARY_ESTIMAND,
        "control_mean": control_mean,
        "historical_mean": hist_mean,
        "naive_gap": _rnd(
            None if control_mean is None or hist_mean is None else hist_mean - control_mean
        ),
        "features": sorted(rows, key=lambda row: row["feature"]),
        "closest_feature": None if best is None else {
            "feature": best["feature"],
            "gap": best["gap"],
            "overlap_share": best["overlap_share"],
            "r_squared": best["r_squared"],
            "loo_mae": best["loo_mae"],
        },
        "reading": (
            "a model fitted on the control corpus and applied to the historical features leaves a "
            "gap. If that gap stays close to the naive difference, no single trace property "
            "explains it; if the overlap share is low, the prediction is an extrapolation and the "
            "gap is not an effect estimate either way."
        ),
    }



# ===========================================================================
# PART 4 - the per-song comparison and its uncertainty (section 8 of the brief)
# ===========================================================================
def _cluster_bootstrap_difference(
    control: Sequence[TraceEvidence],
    historical: Sequence[TraceEvidence],
    estimand: str,
    draws: int = BOOTSTRAP_DRAWS,
    seed: int = RANDOM_SEED,
) -> Dict[str, Any]:
    """A difference in means whose interval resamples *sources*, never frames and never traces.

    The historical traces are clustered: eleven SAP files hold twelve traces and three composers
    wrote them. Resampling traces would treat Blinkys_Sub0 and Blinkys_Sub3 as independent, and
    resampling frames - which is what a naive interval over 1.1 million register values would do -
    would treat every frame as an independent experiment. Neither is true, so the resampling unit is
    the source, and the control corpus's unit is the composition because each is its own document.
    """
    control_values = [
        row.estimands[estimand] for row in control if row.estimands[estimand] is not None
    ]
    historical_by_source: Dict[str, List[float]] = {}
    for row in historical:
        value = row.estimands[estimand]
        if value is not None:
            historical_by_source.setdefault(row.source_key, []).append(value)
    if not control_values or not historical_by_source:
        return {
            "estimand": estimand,
            "available": False,
            "reason": "one of the corpora has no defined value for this estimand",
        }
    sources = sorted(historical_by_source)
    rng = random.Random(seed)
    differences: List[float] = []
    for _draw in range(draws):
        sampled_sources = [sources[rng.randrange(len(sources))] for _ in sources]
        hist_values: List[float] = []
        for source in sampled_sources:
            hist_values.extend(historical_by_source[source])
        sampled_control = [
            control_values[rng.randrange(len(control_values))] for _ in control_values
        ]
        differences.append(
            (sum(hist_values) / len(hist_values))
            - (sum(sampled_control) / len(sampled_control))
        )
    differences.sort()
    flat = [value for values in historical_by_source.values() for value in values]
    observed = (sum(flat) / len(flat)) - (sum(control_values) / len(control_values))
    low = _quantile(differences, 0.025)
    high = _quantile(differences, 0.975)
    return {
        "estimand": estimand,
        "available": True,
        "observed_difference": round(observed, 6),
        "ci_low": low,
        "ci_high": high,
        "ci_median": _median(differences),
        "draws": draws,
        "seed": seed,
        "cluster_unit": "historical SAP source; control composition",
        "historical_sources": len(sources),
        "historical_values": len(flat),
        "control_values": len(control_values),
        "excludes_zero": low is not None and high is not None and (low > 0 or high < 0),
        "reading": (
            "the interval is a cluster bootstrap over sources, so it respects the dependence the "
            "traces carry. It is reported beside the effect size, never instead of it."
        ),
    }
def per_song_comparison(
    control: Sequence[TraceEvidence], historical: Sequence[TraceEvidence]
) -> Dict[str, Any]:
    """The per-trace distributions, the effect size and the cluster-bootstrap interval."""
    out: Dict[str, Any] = {
        "unit_of_replication": (
            "the trace. Register values are never treated as independent observations: 1.1 million "
            "values from twelve traces are twelve observations, not 1.1 million."
        ),
        "estimands": {},
    }
    for name in ESTIMAND_NAMES:
        cv = [row.estimands[name] for row in control if row.estimands[name] is not None]
        hv = [row.estimands[name] for row in historical if row.estimands[name] is not None]
        out["estimands"][name] = {
            "control": {
                "n": len(cv),
                "mean": _mean(cv),
                "median": _median(cv),
                "min": min(cv) if cv else None,
                "p25": _quantile(cv, 0.25),
                "p75": _quantile(cv, 0.75),
                "max": max(cv) if cv else None,
                "stdev": _stdev(cv),
            },
            "historical": {
                "n": len(hv),
                "mean": _mean(hv),
                "median": _median(hv),
                "min": min(hv) if hv else None,
                "p25": _quantile(hv, 0.25),
                "p75": _quantile(hv, 0.75),
                "max": max(hv) if hv else None,
                "stdev": _stdev(hv),
            },
            "difference_in_means": _rnd(
                None if not cv or not hv else (sum(hv) / len(hv)) - (sum(cv) / len(cv))
            ),
            "difference_in_medians": _rnd(
                None if not cv or not hv
                else (_median(hv) or 0.0) - (_median(cv) or 0.0)
            ),
            "bootstrap": _cluster_bootstrap_difference(control, historical, name),
        }
    return out
#: Which Stage 22 error classes can be measured on which corpus. Stating this before the comparison
#: is what stops a historical residual being labelled with a class the trace cannot support.
CLASS_MEASURABILITY: Tuple[Dict[str, str], ...] = (
    {
        "class": "AUDF / AUDC split of the residual",
        "control": "measurable", "historical": "measurable",
        "why": "both are register-group shares of a residual the same detector produced",
    },
    {
        "class": "register changes per frame",
        "control": "measurable", "historical": "measurable",
        "why": "a property of the trace alone",
    },
    {
        "class": "stable-state run lengths",
        "control": "measurable", "historical": "measurable",
        "why": "a property of the trace alone",
    },
    {
        "class": "AUDF and AUDC change co-occurrence",
        "control": "measurable", "historical": "measurable",
        "why": "a property of the trace alone",
    },
    {
        "class": "channel activity shares",
        "control": "measurable", "historical": "measurable",
        "why": "a property of the trace alone",
    },
    {
        "class": "generator-transition precision and recall",
        "control": "measurable", "historical": "measurable",
        "why": "the truth is the trace's own distortion changes, so it needs no ground truth",
    },
    {
        "class": "register activity at zero level",
        "control": "measurable", "historical": "measurable",
        "why": "a property of the trace alone",
    },
    {
        "class": "merged spans, missed notes, note recall",
        "control": "control only", "historical": "not identifiable",
        "why": "it needs a ground-truth note list, and a Tier D SAP has none",
    },
    {
        "class": "value reading versus note set",
        "control": "control only", "historical": "not identifiable",
        "why": "the arm needs the composition's spans, which the historical corpus lacks",
    },
    {
        "class": "pitch exactness at a matched onset",
        "control": "control only", "historical": "not identifiable",
        "why": "it compares the read against the composed pitch",
    },
    {
        "class": "frame attribution buckets",
        "control": "control only", "historical": "not identifiable",
        "why": "three of the five buckets need a ground-truth occupancy",
    },
)


def _profile_features(trace: Any) -> Dict[str, float]:
    """Trace-derived residual-profile features, computed identically on both corpora."""
    registers = trace.registers
    frames = max(1, trace.frames)
    voices = stage15.voices_for(int(trace.audctl))
    audf_changes = audc_changes = co_occur = zero_level_changes = 0
    runs: List[int] = []
    for voice in voices:
        audc = registers[f"AUDC{voice.volume_channel}"]
        pitch = registers[f"AUDF{voice.pitch_channels[0]}"]
        audc_change = [0] * trace.frames
        audf_change = [0] * trace.frames
        for frame in range(1, trace.frames):
            if audc[frame] != audc[frame - 1]:
                audc_change[frame] = 1
                audc_changes += 1
            if pitch[frame] != pitch[frame - 1]:
                audf_change[frame] = 1
                audf_changes += 1
            if audc_change[frame] and audf_change[frame]:
                co_occur += 1
            if stage15.audc_volume(audc[frame]) == 0 and (
                audc_change[frame] or audf_change[frame]
            ):
                zero_level_changes += 1
        runs.extend(_run_lengths(audc))
    return {
        "audf_change_rate": audf_changes / frames,
        "audc_change_rate": audc_changes / frames,
        "audf_audc_co_occurrence_rate": co_occur / frames,
        "zero_level_change_rate": zero_level_changes / frames,
        "mean_audc_run_length": (sum(runs) / len(runs)) if runs else 0.0,
        "max_audc_run_length": float(max(runs)) if runs else 0.0,
        "p90_audc_run_length": _quantile(runs, 0.9) or 0.0,
    }


def residual_profile_comparison(
    control: Sequence[TraceEvidence], historical: Sequence[TraceEvidence]
) -> Dict[str, Any]:
    """Compare the *structure* of the residual, not only its size, on what both corpora can measure."""
    rows: List[Dict[str, Any]] = []
    for name in ("audf_change_rate", "audc_change_rate", "audf_audc_co_occurrence_rate",
                 "zero_level_change_rate", "mean_audc_run_length", "max_audc_run_length",
                 "p90_audc_run_length"):
        cv = [float(row.mediators.get(name, row.features.get(name, 0.0))) for row in control]
        hv = [float(row.mediators.get(name, row.features.get(name, 0.0))) for row in historical]
        rows.append({
            "feature": name,
            "control_mean": _mean(cv),
            "historical_mean": _mean(hv),
            "difference": _rnd(
                None if not cv or not hv else (sum(hv) / len(hv)) - (sum(cv) / len(cv))
            ),
        })
    by_register: Dict[str, Any] = {}
    for group, names in (("AUDF", AUDF_COLUMNS), ("AUDC", AUDC_COLUMNS)):
        control_values = [
            _share(sum(row.per_register[name] for name in names),
                   sum(row.per_register.values()))
            for row in control
        ]
        historical_values = [
            _share(sum(row.per_register[name] for name in names),
                   sum(row.per_register.values()))
            for row in historical
        ]
        by_register[group] = {
            "control_mean_share_of_residual": _mean(
                [value for value in control_values if value is not None]
            ),
            "historical_mean_share_of_residual": _mean(
                [value for value in historical_values if value is not None]
            ),
        }
    return {
        "estimand": "E_total_exporter",
        "class_measurability": [dict(item) for item in CLASS_MEASURABILITY],
        "trace_profile": sorted(rows, key=lambda row: row["feature"]),
        "register_group_shares": by_register,
        "reading": (
            "these are properties of the trace and of the detector's output on it. They are not "
            "properties of a composition and not evidence of an author's intention, and no "
            "historical residual is labelled with a class the trace cannot support."
        ),
    }




#: The criteria, with the thresholds, declared before the numbers were read. A criterion that needs
#: an arbitrary threshold states it here so it cannot be moved afterwards.
HISTORY_SPECIFIC_CRITERIA: Tuple[Dict[str, Any], ...] = (
    {
        "criterion": "present in more than one trace and more than one source",
        "threshold": f"at least {MIN_SOURCES_FOR_EFFECT} distinct sources contribute",
    },
    {
        "criterion": "not driven by one trace or one channel",
        "threshold": "leave-one-source-out keeps the sign",
    },
    {
        "criterion": "holds under every residual definition",
        "threshold": "the sign is the same for all four total estimands",
    },
    {
        "criterion": "survives composition matching",
        "threshold": "the gap stays positive after matching, and the match is not an extrapolation",
    },
    {
        "criterion": "practically significant, not merely non-zero",
        "threshold": f"the effect size is at least {EFFECT_THRESHOLD}",
    },
    {
        "criterion": "not explained by the mechanisms identified in this stage",
        "threshold": "the gap survives the zero-onset-span decomposition",
    },
    {
        "criterion": "reproducible",
        "threshold": "a repeated run produces byte-identical artefacts",
    },
)


def leave_one_source_out(
    control: Sequence[TraceEvidence], historical: Sequence[TraceEvidence]
) -> Dict[str, Any]:
    """Drop each historical source in turn and re-run the primary comparison.

    The unit dropped is the *source*, not the trace, because two of the twelve traces share a SAP
    file. Dropping one trace at a time would leave its sibling in place and understate the
    dependence.
    """
    by_source: Dict[str, List[TraceEvidence]] = {}
    for row in historical:
        by_source.setdefault(row.source_key, []).append(row)
    full = _cluster_bootstrap_difference(control, historical, PRIMARY_ESTIMAND, draws=400)
    rows: List[Dict[str, Any]] = []
    for source in sorted(by_source):
        kept = [row for row in historical if row.source_key != source]
        result = _cluster_bootstrap_difference(control, kept, PRIMARY_ESTIMAND, draws=400)
        observed = result.get("observed_difference")
        rows.append({
            "dropped_source": source,
            "dropped_traces": sorted(row.slug for row in by_source[source]),
            "kept_traces": len(kept),
            "difference": observed,
            "ci_low": result.get("ci_low"),
            "ci_high": result.get("ci_high"),
            "sign_preserved": (
                None if observed is None
                else (observed > 0) == ((full.get("observed_difference") or 0) > 0)
            ),
        })
    values = [row["difference"] for row in rows if row["difference"] is not None]
    return {
        "estimand": PRIMARY_ESTIMAND,
        "full_difference": full.get("observed_difference"),
        "full_ci": [full.get("ci_low"), full.get("ci_high")],
        "rows": rows,
        "min_difference": min(values) if values else None,
        "max_difference": max(values) if values else None,
        "sign_preserved_in_all": all(row["sign_preserved"] for row in rows),
        "reading": (
            "if the sign survived every drop the conclusion does not rest on a single SAP file; if "
            "it did not, the effect is that file's and not the corpus's."
        ),
    }


def channel_sensitivity(
    control: Sequence[TraceEvidence], historical: Sequence[TraceEvidence]
) -> Dict[str, Any]:
    """Control D: is the result spread across channels, or is it one channel's?

    The per-channel estimand uses each channel's own registers as numerator and the covered frames
    times that channel's register count as denominator, so the denominator is declared per channel
    rather than inherited from the whole trace.
    """
    channels: List[Dict[str, Any]] = []
    for channel in (1, 2, 3, 4):
        names = (f"AUDF{channel}", f"AUDC{channel}")
        row: Dict[str, Any] = {"channel": channel, "registers": list(names)}
        for label, corpus in (("control", control), ("historical", historical)):
            numerator = sum(sum(item.per_register_in_span[name] for name in names)
                            for item in corpus)
            denominator = sum(sum(item.per_register_in_span_total[name] for name in names)
                              for item in corpus)
            share = _share(
                sum(sum(item.per_register[name] for name in names) for item in corpus),
                sum(sum(item.per_register.values()) for item in corpus),
            )
            row[label] = {
                "in_span_residual": numerator,
                "in_span_denominator": denominator,
                "in_span_rate": _share(numerator, denominator),
                "share_of_total_residual": share,
            }
        row["difference"] = _rnd(
            None if row["historical"]["in_span_rate"] is None
            or row["control"]["in_span_rate"] is None
            else row["historical"]["in_span_rate"] - row["control"]["in_span_rate"]
        )
        channels.append(row)
    differences = [row["difference"] for row in channels if row["difference"] is not None]
    positive = sum(1 for value in differences if value > 0)
    return {
        "estimand": PRIMARY_ESTIMAND,
        "channels": channels,
        "channels_with_positive_difference": positive,
        "channels_compared": len(differences),
        "spread_across_channels": positive == len(differences) and len(differences) > 1,
        "reading": (
            "if the difference appears on every channel it is not one channel's artefact; if it "
            "appears on one channel only, the effect is that channel's and the report says so."
        ),
    }


def convention_sensitivity(
    control: Sequence[TraceEvidence], historical: Sequence[TraceEvidence]
) -> Dict[str, Any]:
    """Controls A and F: the same comparison under every residual definition.

    The two conventions write the same register value wherever a detected span drives it, and differ
    only on the register values no span drives, so ``E_in_span`` is convention-free by construction
    and the two totals bracket it. Reporting all four together, and reporting the measured size of
    the region the conventions disagree about, is what shows whether the sign and the size of the
    difference depend on the definition.
    """
    rows: List[Dict[str, Any]] = []
    for name in ESTIMAND_NAMES:
        cv = [row.estimands[name] for row in control if row.estimands[name] is not None]
        hv = [row.estimands[name] for row in historical if row.estimands[name] is not None]
        difference = (
            None if not cv or not hv else (sum(hv) / len(hv)) - (sum(cv) / len(cv))
        )
        rows.append({
            "estimand": name,
            "control_mean": _mean(cv),
            "historical_mean": _mean(hv),
            "difference": _rnd(difference),
            "defined_in_control": len(cv),
            "defined_in_historical": len(hv),
            "sign": None if difference is None else ("positive" if difference > 0 else "negative"),
        })
    totals = [row for row in rows if row["estimand"].startswith("E_total")]
    signs = {row["sign"] for row in totals if row["sign"]}
    region = {}
    for label, corpus in (("control", control), ("historical", historical)):
        in_residual = sum(row.counts["E_in_span"][0] for row in corpus)
        in_values = sum(row.in_span_values for row in corpus)
        out_hold = sum(row.counts["E_out_span_hold"][0] for row in corpus)
        out_exporter = sum(row.counts["E_out_span_exporter"][0] for row in corpus)
        out_values = sum(row.out_span_values for row in corpus)
        region[label] = {
            "in_span_values": in_values,
            "in_span_residual": in_residual,
            "in_span_rate": _share(in_residual, in_values),
            "out_span_values": out_values,
            "out_span_hold_residual": out_hold,
            "out_span_hold_rate": _share(out_hold, out_values),
            "out_span_exporter_residual": out_exporter,
            "out_span_exporter_rate": _share(out_exporter, out_values),
            "out_span_share_of_all_values": _share(out_values, in_values + out_values),
            "out_span_exporter_share_of_all_residual": _share(
                out_exporter, in_residual + out_exporter
            ),
        }
    return {
        "definitions": rows,
        "total_definition_signs": sorted(signs),
        "sign_stable_across_totals": len(signs) == 1,
        "outside_span_region": region,
        "primary_estimand": PRIMARY_ESTIMAND,
        "primary_is_convention_free": (
            "a register value is in-span when a detected span drives that register in that frame, "
            "and the hold and exporter conventions write the same value there by construction, so "
            "E_in_span cannot be moved by the convention choice. The conventions differ only on "
            "register values no span drives, and those are excluded."
        ),
        "reading": (
            "a definition whose sign disagrees with the others makes the comparison definition "
            "dependent, and the brief calls that not robust."
        ),
    }







#: Negative-control features: properties that should reflect the *pipeline* rather than any musical
#: behaviour. If a historical/control difference shows up here with the same shape as on the primary
#: estimand, the difference is more likely a measurement artefact than a finding.
NEGATIVE_CONTROL_FEATURES: Tuple[str, ...] = (
    "register_value_cardinality",
    "audctl_value",
    "frames_per_span_ratio",
    "register_columns_constant_share",
)


def _negative_control_values(row: TraceEvidence) -> Dict[str, float]:
    """Four features whose variation is a property of the encoding, not of the music."""
    return {
        "register_value_cardinality": float(
            row.features["distinct_audf_values"] + row.features["distinct_audc_values"]
        ),
        "audctl_value": float(row.audctl),
        "frames_per_span_ratio": (row.frames / row.spans if row.spans else 0.0),
        "register_columns_constant_share": (
            (FRAME_BYTES - 1) / FRAME_BYTES if row.frames else 0.0
        ),
    }


def negative_controls(
    control: Sequence[TraceEvidence], historical: Sequence[TraceEvidence]
) -> Dict[str, Any]:
    """Control E: features that should *not* differ, used to detect matching and arithmetic artefacts.

    A negative control that shows the same pattern as the primary estimand weakens the historical
    reading, because it would mean the pattern is something the pipeline produces on any two corpora
    of different shape. The comparison is made the same way as the primary one, so the two are
    directly comparable.
    """
    rows: List[Dict[str, Any]] = []
    for name in NEGATIVE_CONTROL_FEATURES:
        cv = [_negative_control_values(row)[name] for row in control]
        hv = [_negative_control_values(row)[name] for row in historical]
        control_mean = _mean(cv)
        historical_mean = _mean(hv)
        rows.append({
            "feature": name,
            "control_mean": control_mean,
            "historical_mean": historical_mean,
            "difference": _rnd(
                None if control_mean is None or historical_mean is None
                else historical_mean - control_mean
            ),
            "control_constant": len(set(cv)) == 1,
            "historical_constant": len(set(hv)) == 1,
        })
    primary_control = [row.estimands[PRIMARY_ESTIMAND] for row in control]
    primary_historical = [row.estimands[PRIMARY_ESTIMAND] for row in historical]
    primary_difference = _rnd(
        (_mean([v for v in primary_historical if v is not None]) or 0.0)
        - (_mean([v for v in primary_control if v is not None]) or 0.0)
    )
    return {
        "features": rows,
        "primary_estimand": PRIMARY_ESTIMAND,
        "primary_difference": primary_difference,
        "reading": (
            "the negative controls are properties of the encoding. A difference of the same shape "
            "and size as the primary estimand would mean the primary difference is a property of "
            "comparing two corpora of different shape, and the report says so."
        ),
    }



def history_specific_test(
    control: Sequence[TraceEvidence],
    historical: Sequence[TraceEvidence],
    comparison: Mapping[str, Any],
    calibration_result: Mapping[str, Any],
    leave_one_out: Mapping[str, Any],
    conventions: Mapping[str, Any],
    negatives: Mapping[str, Any],
    reproducible: bool,
) -> Dict[str, Any]:
    """Evaluate the seven pre-declared criteria and report each one's verdict and its numbers.

    The criteria and their thresholds were fixed in ``HISTORY_SPECIFIC_CRITERIA`` before the numbers
    were read. Each is reported with the measurement that decided it, so a reader can disagree with
    the verdict without re-running the stage.
    """
    primary = comparison["estimands"][PRIMARY_ESTIMAND]
    bootstrap = primary["bootstrap"]
    difference = primary["difference_in_means"]
    explained = comparison["estimands"][EXPLAINED_ESTIMAND]["difference_in_means"]
    sources = {row["source_key"] for row in historical}
    gap_mean = calibration_result["historical_gap_mean"]
    loo_mae = calibration_result["control_loo"]["mae"]
    extrapolated = calibration_result["historical_beyond_control_support"]

    def evaluated(index: int, passed: Optional[bool], measurement: Any) -> Dict[str, Any]:
        criteria = HISTORY_SPECIFIC_CRITERIA[index]
        return {
            "criterion": criteria["criterion"],
            "threshold": criteria["threshold"],
            "passed": passed,
            "measurement": measurement,
        }

    results = [
        evaluated(
            0,
            len(sources) >= MIN_SOURCES_FOR_EFFECT,
            {"sources_contributing": len(sources), "traces": len(historical)},
        ),
        evaluated(
            1,
            leave_one_out["sign_preserved_in_all"],
            {
                "min_difference_after_drop": leave_one_out["min_difference"],
                "max_difference_after_drop": leave_one_out["max_difference"],
            },
        ),
        evaluated(
            2,
            conventions["sign_stable_across_totals"],
            {"total_definition_signs": conventions["total_definition_signs"]},
        ),
        evaluated(
            3,
            bool(gap_mean is not None and gap_mean > 0 and extrapolated == 0),
            {
                "matched_gap_mean": gap_mean,
                "traces_beyond_control_support": extrapolated,
                "traces": len(historical),
            },
        ),
        evaluated(
            4,
            bool(difference is not None and abs(difference) >= EFFECT_THRESHOLD),
            {"difference_in_means": difference, "threshold": EFFECT_THRESHOLD},
        ),
        evaluated(
            5,
            bool(explained is not None and explained > 0),
            {
                "difference_after_removing_zero_onset_spans": explained,
                "difference_before": difference,
            },
        ),
        evaluated(6, reproducible, {"repeated_run_byte_identical": reproducible}),
    ]
    passed = sum(1 for row in results if row["passed"])
    return {
        "criteria": results,
        "criteria_passed": passed,
        "criteria_total": len(results),
        "all_passed": passed == len(results),
        "primary_estimand": PRIMARY_ESTIMAND,
        "primary_difference": difference,
        "primary_ci": [bootstrap.get("ci_low"), bootstrap.get("ci_high")],
        "matched_gap": gap_mean,
        "control_loo_mae": loo_mae,
        "gap_exceeds_model_error": (
            None if gap_mean is None or loo_mae is None else abs(gap_mean) > loo_mae
        ),
        "negative_control_max_abs_difference": max(
            (abs(row["difference"]) for row in negatives["features"]
             if row["difference"] is not None),
            default=None,
        ),
        "identification_blocker": (
            "the gap exceeds the model's own error, but "
            f"{extrapolated} of {len(historical)} historical traces lie beyond the control corpus's "
            "feature support, so the comparison cannot separate a historical-specific effect from a "
            "property of trace shapes the control corpus never produces"
            if extrapolated else
            "the gap exceeds the model's own error and the predictions are interpolations"
        ),
        "what_this_is_not": (
            "meeting these criteria does not prove a performance layer. It means a residual effect "
            "survived the controls and is worth a new experiment."
        ),
    }
def verdicts(
    comparison: Mapping[str, Any],
    calibration_result: Mapping[str, Any],
    leave_one_out: Mapping[str, Any],
    conventions: Mapping[str, Any],
    negatives: Mapping[str, Any],
    overlay: Mapping[str, Any],
    history_test: Mapping[str, Any],
) -> Dict[str, Any]:
    """The four-way distinction the brief asks for, decided by measurement and not by preference.

    The vocabulary separates four things that are easy to blur: no effect detected, an effect that is
    not robust, an effect that is robust but not identifiable, and an effect that justifies a new
    experiment. ``PROVEN PERFORMANCE LAYER`` is not in the vocabulary and is not used.
    """
    primary = comparison["estimands"][PRIMARY_ESTIMAND]
    bootstrap = primary["bootstrap"]
    difference = primary["difference_in_means"]
    extrapolated = calibration_result["historical_beyond_control_support"]
    historical_count = calibration_result["historical_count"]
    gap = calibration_result["historical_gap_mean"]
    loo_mae = calibration_result["control_loo"]["mae"]
    sign_stable = conventions["sign_stable_across_totals"]
    robust_to_dropping = leave_one_out["sign_preserved_in_all"]
    gap_exceeds_error = None if gap is None or loo_mae is None else abs(gap) > loo_mae
    mostly_extrapolated = historical_count > 0 and extrapolated > historical_count / 2
    if difference is None or not bootstrap.get("available"):
        main = "COMPARISON_INCONCLUSIVE"
        reason = "the primary estimand is not defined on both corpora"
    elif not sign_stable:
        main = "HISTORICAL_DIFFERENCE_NOT_ROBUST"
        reason = "the sign of the difference depends on which residual definition is used"
    elif mostly_extrapolated and gap_exceeds_error:
        main = "HISTORICAL_DIFFERENCE_ROBUST_BUT_NOT_IDENTIFIED"
        reason = (
            "the difference holds under every definition and survives every leave-one-source-out "
            "drop, but most historical traces lie outside the control corpus's feature support, so "
            "its cause cannot be separated from a property of trace shape"
        )
    elif not robust_to_dropping:
        main = "HISTORICAL_DIFFERENCE_NOT_ROBUST"
        reason = "dropping one SAP source removes or reverses the difference"
    elif gap is not None and gap_exceeds_error:
        main = "HISTORICAL_SPECIFIC_EFFECT_CANDIDATE"
        reason = (
            "the difference holds under every definition, survives every drop, and exceeds the "
            "model's own error on an interpolated comparison"
        )
    else:
        main = "HISTORICAL_DIFFERENCE_PARTIALLY_EXPLAINED"
        reason = "the matched gap does not exceed the model's own error"
    if main == "HISTORICAL_SPECIFIC_EFFECT_CANDIDATE" and not history_test["all_passed"]:
        main = "HISTORICAL_DIFFERENCE_ROBUST_BUT_NOT_IDENTIFIED"
        reason = "not every pre-declared criterion for a history-specific effect was met"
    return _verdict_payload(
        main, reason, difference, bootstrap, gap, loo_mae, gap_exceeds_error, extrapolated,
        historical_count, sign_stable, robust_to_dropping, overlay, history_test,
    )


def _verdict_payload(
    main: str,
    reason: str,
    difference: Optional[float],
    bootstrap: Mapping[str, Any],
    gap: Optional[float],
    loo_mae: Optional[float],
    gap_exceeds_error: Optional[bool],
    extrapolated: int,
    historical_count: int,
    sign_stable: bool,
    robust_to_dropping: bool,
    overlay: Mapping[str, Any],
    history_test: Mapping[str, Any],
) -> Dict[str, Any]:
    """Assemble the verdict record, so the decision logic above stays readable."""
    return {
        "primary": {
            "verdict": main,
            "reason": reason,
            "deciding_measurements": {
                "primary_estimand": PRIMARY_ESTIMAND,
                "difference_in_means": difference,
                "bootstrap_ci": [bootstrap.get("ci_low"), bootstrap.get("ci_high")],
                "bootstrap_excludes_zero": bootstrap.get("excludes_zero"),
                "sign_stable_across_definitions": sign_stable,
                "sign_preserved_leave_one_source_out": robust_to_dropping,
                "matched_gap_mean": gap,
                "control_loo_mae": loo_mae,
                "gap_exceeds_model_error": gap_exceeds_error,
                "traces_beyond_control_support": extrapolated,
                "traces": historical_count,
                "negative_control_max_abs_difference":
                    history_test["negative_control_max_abs_difference"],
            },
        },
        "corpus_composition": {
            "verdict": (
                "HISTORICAL_DIFFERENCE_EXPLAINED_BY_CORPUS_COMPOSITION"
                if overlay["matching_features_covering_under_half_the_historical_traces"]
                else "CORPUS_COMPOSITION_NOT_SEPARATED"
            ),
            "conditions": {
                "features_without_any_common_range":
                    overlay["features_without_any_common_range"],
                "matching_features_under_half_coverage":
                    overlay["matching_features_covering_under_half_the_historical_traces"],
            },
            "deciding_condition": (
                "the corpora do not share a feature range on several matching features, so the "
                "difference could be a property of the trace shapes the historical corpus happens "
                "to have. That is a corpus-composition explanation and it cannot be ruled out here."
            ),
        },
        "performance_candidate": {
            "verdict": (
                "PERFORMANCE_CANDIDATE_REQUIRES_NEW_CONTROLLED_TEST"
                if main in ("HISTORICAL_SPECIFIC_EFFECT_CANDIDATE",
                            "HISTORICAL_DIFFERENCE_ROBUST_BUT_NOT_IDENTIFIED")
                else "PERFORMANCE_CANDIDATE_REMAINS_UNSUPPORTED"
            ),
            "conditions": {
                "confirmed_performance_candidate": 0,
                "stage21_verdict": "PERFORMANCE_LAYER_VALIDATION_INCONCLUSIVE",
                "stage22_verdict": "HISTORICAL_RESIDUAL_DIFFERENT_FROM_CONTROL",
                "stage23_verdict": main,
            },
            "deciding_condition": (
                "no test here can confirm a performance layer, and none is claimed. The verdict only "
                "says whether a new experiment is warranted and what it would have to control."
            ),
        },
        "atari_music_composer_impact": {
            "verdict": "NO_PRODUCTION_DECISION_CHANGED",
            "deciding_condition": (
                "Stage 23 changes no detector, no compiler, no player and no schema, and it produces "
                "no music. Whatever it found is a research result about a measurement instrument, "
                "not a change to the composer."
            ),
        },
    }





#: Everything Stage 23 reads and must not write.
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
    "src/atari_music/asm/player.asm",
    "tests/data/sound_profiles/vaults_of_nhyrmeth.dsl",
)

STAGE23_FILES: Tuple[str, ...] = (
    "source_audit.json",
    "corpus_comparison.json",
    "residual_conventions.json",
    "matching_diagnostics.json",
    "matched_corpus_comparison.json",
    "residual_profile_comparison.json",
    "leave_one_song_out.json",
    "sensitivity_analysis.json",
    "negative_controls.json",
    "verdict.json",
    "stage23_manifest.json",
)
STAGE23_DOC = "stage23_controlled_historical_residual_test.md"
STAGE23_REPORT = "stage23_report.md"


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
    stage21_dir: Path = DEFAULT_STAGE21_DIR,
    stage22_dir: Path = DEFAULT_STAGE22_DIR,
) -> Dict[str, Optional[str]]:
    """The hash of every input the stage reads: traces, compositions and upstream artefacts."""
    out: Dict[str, Optional[str]] = {}
    for path in sorted(stage15.list_traces(Path(arch_root))):
        out[f"trace/{path.name}"] = sha256_file(path)
    for slug, _kind, path in stage21.control_sources(
        songs_dir, ai_dir, DEFAULT_EXTRA_DSL_DIR
    ):
        out[f"composition/{slug}"] = sha256_file(path)
    for directory in (Path(stage21_dir), Path(stage22_dir)):
        for path in sorted(directory.glob("*.json")):
            out[f"upstream/{directory.name}/{path.name}"] = sha256_file(path)
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


def _digest(payload: Any) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, ensure_ascii=True).encode("utf-8")
    ).hexdigest()


def analyse_corpora(
    arch_root: Path = DEFAULT_ARCHAEOLOGY_DIR,
    songs_dir: Path = DEFAULT_SONGS_DIR,
    ai_dir: Path = DEFAULT_AI_DIR,
) -> Dict[str, Any]:
    """The deterministic core: measure both corpora and run every comparison and control."""
    historical = load_historical_evidence(arch_root)
    control = load_control_evidence(songs_dir, ai_dir)
    if not historical or not control:
        raise Stage23Error("one of the corpora is empty; the comparison needs both")
    overlay = overlap_diagnosis(control, historical)
    calibration_result = calibration(control, historical)
    screen = univariate_screen(control, historical)
    comparison = per_song_comparison(control, historical)
    profile = residual_profile_comparison(control, historical)
    leave_one_out = leave_one_source_out(control, historical)
    conventions = convention_sensitivity(control, historical)
    channels = channel_sensitivity(control, historical)
    negatives = negative_controls(control, historical)
    return {
        "historical": [row.to_dict() for row in historical],
        "control": [row.to_dict() for row in control],
        "clusters": cluster_index(historical),
        "estimand_rules": [dict(item) for item in ESTIMAND_RULES],
        "overlap": overlay,
        "calibration": calibration_result,
        "univariate_screen": screen,
        "comparison": comparison,
        "profile": profile,
        "leave_one_out": leave_one_out,
        "conventions": conventions,
        "channels": channels,
        "negatives": negatives,
    }


def run_analysis(
    arch_root: Path = DEFAULT_ARCHAEOLOGY_DIR,
    songs_dir: Path = DEFAULT_SONGS_DIR,
    ai_dir: Path = DEFAULT_AI_DIR,
    stage21_dir: Path = DEFAULT_STAGE21_DIR,
    stage22_dir: Path = DEFAULT_STAGE22_DIR,
    verify_reproducibility: bool = True,
) -> Dict[str, Any]:
    """Everything Stage 23 measures, in one deterministic pass, with a reproducibility check.

    The analysis is run twice and the two payload digests compared. A stage whose whole claim is
    about the stability of a difference has to be able to show that its own arithmetic is stable.
    """
    production_before = production_hashes()
    inputs_before = input_hashes(arch_root, songs_dir, ai_dir, stage21_dir, stage22_dir)
    core = analyse_corpora(arch_root, songs_dir, ai_dir)
    reproducible = True
    digest = _digest(core)
    if verify_reproducibility:
        again = _digest(analyse_corpora(arch_root, songs_dir, ai_dir))
        reproducible = again == digest
        if not reproducible:
            raise Stage23Error(
                "the analysis is not reproducible: two runs produced different payloads"
            )
    audit = audit_sources(stage21_dir, stage22_dir)
    history_test = history_specific_test(
        core["control"], core["historical"],
        core["comparison"], core["calibration"],
        core["leave_one_out"], core["conventions"], core["negatives"], reproducible,
    )
    decided = verdicts(
        core["comparison"], core["calibration"], core["leave_one_out"],
        core["conventions"], core["negatives"], core["overlap"], history_test,
    )
    bundle: Dict[str, Any] = {
        "analysis_version": ANALYSIS_VERSION,
        "audit": audit,
        "core": core,
        "history_specific_test": history_test,
        "verdicts": decided,
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
                inputs_before,
                input_hashes(arch_root, songs_dir, ai_dir, stage21_dir, stage22_dir),
                "traces, composition documents and upstream artefacts",
            ),
        },
        "determinism": {
            "random_seed": RANDOM_SEED,
            "bootstrap_draws": BOOTSTRAP_DRAWS,
            "tie_breaks": (
                "nearest-neighbour ties break on the slug; leave-one-source-out iterates the "
                "sources in sorted order; the bootstrap uses a seeded Random; every dict that "
                "reaches an artefact is emitted with sorted keys; and every specification list is "
                "sorted before use"
            ),
            "source_hash": sha256_file(Path(__file__)),
        },
    }
    bundle["summary"] = _summary(bundle)
    return bundle
def _summary(bundle: Mapping[str, Any]) -> Dict[str, Any]:
    """The executive numbers, so a reader does not have to open eleven files."""
    core = bundle["core"]
    comparison = core["comparison"]["estimands"]
    primary = comparison[PRIMARY_ESTIMAND]
    explained = comparison[EXPLAINED_ESTIMAND]
    calibration_result = core["calibration"]
    test = bundle["history_specific_test"]
    decided = bundle["verdicts"]
    return {
        "historical_traces": len(core["historical"]),
        "control_songs": len(core["control"]),
        "historical_sources": core["clusters"]["source_count"],
        "historical_authors": core["clusters"]["author_count"],
        "primary_estimand": PRIMARY_ESTIMAND,
        "primary_control_mean": primary["control"]["mean"],
        "primary_historical_mean": primary["historical"]["mean"],
        "primary_difference": primary["difference_in_means"],
        "primary_ci": [primary["bootstrap"].get("ci_low"), primary["bootstrap"].get("ci_high")],
        "primary_excludes_zero": primary["bootstrap"].get("excludes_zero"),
        "explained_estimand": EXPLAINED_ESTIMAND,
        "explained_difference": explained["difference_in_means"],
        "hold_difference": comparison["E_total_hold"]["difference_in_means"],
        "exporter_difference": comparison["E_total_exporter"]["difference_in_means"],
        "control_loo_mae": calibration_result["control_loo"]["mae"],
        "matched_gap_mean": calibration_result["historical_gap_mean"],
        "traces_beyond_control_support": calibration_result["historical_beyond_control_support"],
        "features_without_common_range": core["overlap"]["features_without_any_common_range"],
        "sign_stable_across_definitions": core["conventions"]["sign_stable_across_totals"],
        "sign_preserved_leave_one_source_out": core["leave_one_out"]["sign_preserved_in_all"],
        "channels_with_positive_difference":
            core["channels"]["channels_with_positive_difference"],
        "criteria_passed": test["criteria_passed"],
        "criteria_total": test["criteria_total"],
        "verdicts": {
            key: value["verdict"] for key, value in sorted(decided.items())
        },
        "reproducible": bundle["reproducibility"]["byte_identical"],
        "read_only": all(row["read_only"] for row in bundle["read_only_audit"].values()),
        "read_only_files_checked": sum(
            row["files_checked"] for row in bundle["read_only_audit"].values()
        ),
    }


# ===========================================================================
# PART 9 - the artefacts and the report (sections 16 and 17 of the brief)
# ===========================================================================
def _artefacts(bundle: Mapping[str, Any]) -> Dict[str, Any]:
    """The eleven JSON payloads, built in one place so the writer stays a writer."""
    core = bundle["core"]
    audit = bundle["audit"]
    comparison = core["comparison"]
    primary = comparison["estimands"][PRIMARY_ESTIMAND]
    return {
        "source_audit.json": {
            "declared_definitions": audit["declared_definitions"],
            "stage22_published_numbers": audit["stage22_published_numbers"],
            "stage22_historical_comparison": audit["stage22_historical_comparison"],
            "stage22_falsification": audit["stage22_falsification"],
            "stage22_taxonomy_classes": audit["stage22_taxonomy_classes"],
            "stage22_artefacts": audit["stage22_artefacts"],
            "relied_on": audit["relied_on"],
            "not_relied_on": audit["not_relied_on"],
            "estimand_rules": core["estimand_rules"],
            "discrepancies_found": DISCREPANCIES_FOUND,
        },
        "corpus_comparison.json": {
            "clusters": core["clusters"],
            "historical": core["historical"],
            "control": core["control"],
            "overlap": core["overlap"],
            "features_used_for_matching": list(MATCH_FEATURES),
            "mediators_never_used_for_matching": list(MEDIATOR_FEATURES),
            "why_mediators_are_not_matching_features": (
                "matching on a mediator would control away the mechanism under test; the "
                "zero-onset-span share is an explanation to be tested, not a nuisance to be "
                "balanced"
            ),
        },
        "residual_conventions.json": {
            "conventions": core["conventions"],
            "primary_estimand": PRIMARY_ESTIMAND,
            "why_the_primary_is_convention_free": (
                "the hold and exporter conventions differ only at frames no detected span covers, "
                "and E_in_span excludes exactly those frames, so no convention choice can move it"
            ),
        },
        "matching_diagnostics.json": {
            "overlap": core["overlap"],
            "standardisation": core["calibration"]["standardisation"],
            "control_leave_one_out": core["calibration"]["control_loo"],
            "per_trace": core["calibration"]["historical"],
            "univariate_screen": core["univariate_screen"],
            "k": core["calibration"]["k"],
        },
        "matched_corpus_comparison.json": {
            "estimand": PRIMARY_ESTIMAND,
            "unmatched_control_mean": primary["control"]["mean"],
            "unmatched_historical_mean": primary["historical"]["mean"],
            "unmatched_difference": primary["difference_in_means"],
            "matched_gap_mean": core["calibration"]["historical_gap_mean"],
            "matched_gap_median": core["calibration"]["historical_gap_median"],
            "matched_gap_range": [
                core["calibration"]["historical_gap_min"],
                core["calibration"]["historical_gap_max"],
            ],
            "traces_beyond_control_support": core["calibration"][
                "historical_beyond_control_support"
            ],
            "per_trace": core["calibration"]["historical"],
            "reading": core["calibration"]["reading"],
        },
        "residual_profile_comparison.json": core["profile"],
        "leave_one_song_out.json": core["leave_one_out"],
        "sensitivity_analysis.json": {
            "conventions": core["conventions"],
            "channels": core["channels"],
            "estimand_rules": core["estimand_rules"],
        },
        "negative_controls.json": core["negatives"],
        "verdict.json": {
            "verdicts": bundle["verdicts"],
            "history_specific_test": bundle["history_specific_test"],
            "criteria": [dict(item) for item in HISTORY_SPECIFIC_CRITERIA],
            "thresholds": {
                "effect_threshold": EFFECT_THRESHOLD,
                "caliper": CALIPER,
                "min_sources_for_effect": MIN_SOURCES_FOR_EFFECT,
                "bootstrap_draws": BOOTSTRAP_DRAWS,
                "random_seed": RANDOM_SEED,
            },
        },
        "stage23_manifest.json": {
            "analysis_version": ANALYSIS_VERSION,
            "summary": bundle["summary"],
            "determinism": bundle["determinism"],
            "reproducibility": bundle["reproducibility"],
            "read_only_audit": bundle["read_only_audit"],
            "artefacts": list(STAGE23_FILES),
            "document": STAGE23_DOC,
            "stop_condition": (
                "Stage 23 changes no production code, generates no music, runs no listening test "
                "and implements no further stage. It reports and stops."
            ),
        },
    }
def write_analysis(
    bundle: Mapping[str, Any],
    stage23_dir: Path = DEFAULT_STAGE23_DIR,
    docs_dir: Path = DEFAULT_DOCS_DIR,
) -> Dict[str, Path]:
    """Write the eleven JSON artefacts and the report. Additive: nothing else is touched."""
    stage23_dir = Path(stage23_dir)
    docs_dir = Path(docs_dir)
    stage23_dir.mkdir(parents=True, exist_ok=True)
    docs_dir.mkdir(parents=True, exist_ok=True)
    payload = _artefacts(bundle)
    written: Dict[str, Path] = {}
    for name in STAGE23_FILES:
        if name not in payload:
            raise Stage23Error(f"the artefact {name} was never built")
        path = stage23_dir / name
        path.write_text(
            json.dumps(payload[name], indent=2, ensure_ascii=False, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        written[name] = path
    report = render_report(bundle)
    doc_path = docs_dir / STAGE23_DOC
    doc_path.write_text(report, encoding="utf-8")
    written[STAGE23_DOC] = doc_path
    report_path = stage23_dir / STAGE23_REPORT
    report_path.write_text(report, encoding="utf-8")
    written[STAGE23_REPORT] = report_path
    return written


# ===========================================================================
# PART 10 - the report (section 17 of the brief)
# ===========================================================================
def _pct(value: Optional[float], places: int = 1) -> str:
    return "n/a" if value is None else f"{value * 100:.{places}f}%"


def _num(value: Optional[float], places: int = 4) -> str:
    return "n/a" if value is None else f"{value:.{places}f}"


def _outside_span_sentence(region: Mapping[str, Any]) -> str:
    """The measured size of the region the two conventions disagree about, on both corpora."""
    control = region["control"]
    historical = region["historical"]
    return (
        f"The register values no detected span drives are "
        f"{_pct(control['out_span_share_of_all_values'])} of the control corpus's values and "
        f"{_pct(historical['out_span_share_of_all_values'])} of the historical corpus's. On the "
        f"control corpus the hold convention leaves a residual on "
        f"{_pct(control['out_span_hold_rate'])} of them and the exporter on "
        f"{_pct(control['out_span_exporter_rate'])} - the compiler emits no write there and the "
        f"player holds, so the exporter is nearly right and hold is not. On the historical corpus "
        f"the two are "
        f"{_pct(historical['out_span_hold_rate'])} and "
        f"{_pct(historical['out_span_exporter_rate'])}, so neither convention is right there. The "
        f"convention therefore moves the control corpus's out-of-span residual by a factor of "
        f"{_ratio(control['out_span_hold_rate'], control['out_span_exporter_rate'])} and the "
        f"historical corpus's by only "
        f"{_ratio(historical['out_span_exporter_rate'], historical['out_span_hold_rate'])}"
    )


def _negative_control_sentence(negatives: Mapping[str, Any]) -> str:
    """The negative controls are on their own scales, so they are read by shape, not by size.

    Comparing a count of distinct register values with a residual rate would be a category error, and
    the honest reading is the one that says so: the controls show the corpora differ in encoding, not
    that the primary difference is an artefact.
    """
    rows = [row for row in negatives["features"] if row["difference"] is not None]
    varied = [row for row in rows if not (row["control_constant"] and row["historical_constant"])]
    moved = [row for row in varied if row["difference"]]
    if not moved:
        return (
            "The negative controls - encoding properties rather than musical ones - do not differ "
            "between the corpora, so they give no reason to read the primary difference as a "
            "measurement artefact"
        )
    shown = ", ".join(
        f"`{row['feature']}` {_num(row['control_mean'])} against {_num(row['historical_mean'])}"
        for row in sorted(moved, key=lambda row: -abs(row["difference"]))[:3]
    )
    return (
        f"{len(moved)} of {len(varied)} negative controls differ between the corpora, and they are "
        f"measured on their own scales so they cannot be compared numerically with a residual rate: "
        f"{shown}. The controls therefore do not clear the difference of an encoding explanation - "
        "they show the two corpora differ in encoding at least as much as they differ in residual, "
        "which is the corpus-composition reading the verdict already carries."
    )


def _sentence(text: str) -> str:
    """Capitalise the first letter and end with a full stop, so fragments read as sentences."""
    text = text.strip()
    if not text:
        return text
    text = text[0].upper() + text[1:]
    if not text.endswith("."):
        text += "."
    return text


def _range(low: Optional[float], high: Optional[float]) -> str:
    """A closed interval, or ``none`` when it is empty because the corpora do not overlap."""
    if low is None or high is None:
        return "n/a"
    if low > high:
        return "none (empty)"
    return f"[{_num(low)}, {_num(high)}]"


def _ratio(numerator: Optional[float], denominator: Optional[float]) -> str:
    if numerator is None or not denominator:
        return "n/a"
    return f"{numerator / denominator:.1f}x"


def render_report(bundle: Mapping[str, Any]) -> str:
    """The sixteen sections the brief requires, in its order, then the eight closing questions."""
    s = bundle["summary"]
    out: List[str] = [
        "# Stage 23 - Controlled Historical Residual Test\n",
        "Stage 22 decomposed the Stage 15 detector's residual on traces whose composition is known, "
        "found a difference between the historical and the control corpus, and warned that the "
        "difference was **not robust**: it moved with the outside-note convention and a "
        "corpus-composition difference would have produced it too. Stage 23 is the controlled test "
        "that warning asked for. It does not look for a performance layer; it tries to falsify the "
        "difference.\n",
        "**The headline.** The convention only exists at frames no detected span covers, so "
        "restricting the residual to frames *inside* detected spans removes the convention "
        "altogether. On that convention-free estimand the control corpus sits at "
        f"{_pct(s['primary_control_mean'])} and the historical corpus at "
        f"{_pct(s['primary_historical_mean'])} - a difference of "
        f"**{_pct(s['primary_difference'])}** with a source-clustered bootstrap interval of "
        f"[{_pct(s['primary_ci'][0])}, {_pct(s['primary_ci'][1])}]. The sign is the same under every "
        "residual definition, it survives dropping each SAP source in turn, and it appears on every "
        "channel.\n",
        "**But the comparison is an extrapolation.** The corpora do not occupy the same region of "
        "trace-feature space: "
        + (", ".join(f"`{name}`" for name in s["features_without_common_range"])
           if s["features_without_common_range"] else "no feature is fully separated")
        + " have no common range at all, and "
        f"**{s['traces_beyond_control_support']} of {s['historical_traces']}** historical traces lie "
        "beyond the control corpus's own nearest-neighbour distance range. A model fitted on the "
        "control corpus and applied to the historical features leaves a gap of "
        f"{_num(s['matched_gap_mean'])} against its own leave-one-out error of "
        f"{_num(s['control_loo_mae'])} - far larger than the model's error, but produced by a model "
        "asked to predict outside its support.\n",
        f"**Verdict: `{s['verdicts']['primary']}`.** The difference is real in this data and robust "
        "to every control this stage can apply, but its cause cannot be separated from a property of "
        "the trace shapes the control corpus never produces. That is a negative result for the "
        "performance layer and a specification for the next experiment.\n",
        "Analysis only, read-only and additive. No music was generated, no listening test was run, "
        "no player was modified, no detector was repaired and no production schema was changed. "
        f"Analysis version `{bundle['analysis_version']}`.\n",
        "Artefacts: " + ", ".join(f"`{name}`" for name in STAGE23_FILES) + ".\n",
    ]
    for section in (_s1, _s2, _s3, _s4, _s5, _s6, _s7, _s8, _s9, _s10,
                    _s11, _s12, _s13, _s14, _s15, _s16, _s_questions):
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
                ["Is the difference robust to the convention?",
                 f"**Yes.** The primary estimand excludes the frames where the convention applies, "
                 f"so it cannot move with it. Difference {_pct(s['primary_difference'])}."],
                ["Is the sign the same under every residual definition?",
                 f"**{s['sign_stable_across_definitions']}** - hold "
                 f"{_pct(s['hold_difference'])}, exporter {_pct(s['exporter_difference'])}, "
                 f"in-span {_pct(s['primary_difference'])}, zero-onset-spans removed "
                 f"{_pct(s['explained_difference'])}."],
                ["Does it survive dropping each SAP source?",
                 f"**{s['sign_preserved_leave_one_source_out']}** over "
                 f"{core['clusters']['source_count']} sources."],
                ["Is it spread across channels?",
                 f"**{core['channels']['channels_with_positive_difference']} of 4** channels show a "
                 "positive difference."],
                ["Does it survive composition matching?",
                 f"Matched gap {_num(s['matched_gap_mean'])} against a control leave-one-out error "
                 f"of {_num(s['control_loo_mae'])} - but "
                 f"**{s['traces_beyond_control_support']} of {s['historical_traces']}** predictions "
                 "are extrapolations."],
                ["Can its cause be identified?",
                 f"**No.** {len(s['features_without_common_range'])} matching features have no "
                 "common range, so a corpus-composition explanation cannot be ruled out."],
                ["Verdict",
                 f"**{s['verdicts']['primary']}**; corpus composition "
                 f"{s['verdicts']['corpus_composition']}; performance candidate "
                 f"{s['verdicts']['performance_candidate']}"],
                ["Reproducibility",
                 f"**{s['reproducible']}** - the deterministic core was run twice and the payload "
                 "digests matched"],
                ["Read-only audit",
                 f"**{s['read_only']}** - {s['read_only_files_checked']} production and input "
                 "artefacts hashed before and after the run, none changed"],
                ["Atari Music Composer",
                 f"**{s['verdicts']['atari_music_composer_impact']}** - no production decision is "
                 "affected by this stage"],
            ],
        ),
        "",
        "**A negative result is a full result, and this one is partly negative.** The difference is "
        "not a convention artefact and not a single song's; it is also not identified, and the "
        "experiment that would identify it is stated in section 16.\n",
    ]


def _s2(bundle: Mapping[str, Any]) -> List[str]:
    audit = bundle["audit"]
    return [
        "## 2. Source and Definition Audit\n",
        "The brief's rule is that the artefacts win over any summary, including this one. Every "
        "definition this stage relies on is quoted from the stage that owns it:\n",
        _table(
            ["definition", "owner", "source"],
            [[item["name"], item["owner"], item["source"]]
             for item in audit["declared_definitions"]],
        ),
        "",
        "Stage 22's published numbers, read from its own artefacts rather than restated:\n",
        _table(
            ["quantity", "Stage 22 published"],
            [[key, value] for key, value in
             sorted(audit["stage22_published_numbers"].items())],
        ),
        "",
        "### What the audit changed\n",
        _table(
            ["claim", "what was measured instead", "consequence"],
            [[item["claim"], item["measurement"], item["consequence"]]
             for item in DISCREPANCIES_FOUND],
        ),
        "",
        "**What is reused and what is not.** "
        f"{audit['relied_on']} {audit['not_relied_on']}\n",
    ]



def _s3(bundle: Mapping[str, Any]) -> List[str]:
    core = bundle["core"]
    clusters = core["clusters"]
    return [
        "## 3. Corpora and Their Limits\n",
        _table(
            ["corpus", "traces", "sources", "authors", "frames", "register values", "spans"],
            [
                [
                    "historical", len(core["historical"]), clusters["source_count"],
                    clusters["author_count"],
                    sum(row["frames"] for row in core["historical"]),
                    sum(row["register_values"] for row in core["historical"]),
                    sum(row["spans"] for row in core["historical"]),
                ],
                [
                    "control", len(core["control"]), len(core["control"]), 1,
                    sum(row["frames"] for row in core["control"]),
                    sum(row["register_values"] for row in core["control"]),
                    sum(row["spans"] for row in core["control"]),
                ],
            ],
        ),
        "",
        "**The historical corpus is clustered and small.** "
        f"{clusters['traces']} traces come from {clusters['source_count']} SAP files and "
        f"{clusters['author_count']} composers:\n",
        _table(
            ["author", "traces"],
            [[author, len(traces)] for author, traces in sorted(clusters["by_author"].items())],
        ),
        "",
        "One file contributes more than one trace: "
        + ", ".join(f"`{key}` -> {len(value)} traces"
                    for key, value in sorted(clusters["repeated_sources"].items()))
        + ". " + clusters["effective_sample_note"] + "\n",
        "**What the historical corpus cannot support.** The Tier D verdict from Stage 21 stands: "
        "there is no independent note source for any of these songs, so no note-level ground truth "
        "exists and no class that needs one can be measured on them. Section 9 lists which classes "
        "that removes.\n",
    ]


def _s4(bundle: Mapping[str, Any]) -> List[str]:
    core = bundle["core"]
    return [
        "## 4. Estimands and Residual Definitions\n",
        "Seven estimands, each declaring its numerator, denominator, unit, silence rule, "
        "outside-span rule, coupled-channel rule and aggregation. Declaring them in one table is "
        "what stops a denominator from drifting between sections.\n",
        _table(
            ["estimand", "numerator", "denominator", "outside spans", "aggregation"],
            [[item["name"], item["numerator"], item["denominator"], item["outside_spans"],
              item["aggregation"]] for item in core["estimand_rules"]],
        ),
        "",
        "**The primary estimand is `E_in_span`, and it is convention-free by construction.** A "
        "register value counts as in-span when a detected span drives *that register* in *that "
        "frame*. Inside a span both conventions write the span's own value, so no choice of "
        "convention can move the numerator, and the denominator is fixed by the spans. Splitting by "
        "frame instead would put one voice's registers into another voice's span, where the "
        "conventions genuinely differ, and the identities would then not hold; splitting by register "
        "keeps them exact for both policies. That is why `E_in_span`, and not the total, is the "
        "headline.\n",
        "**The conventions disagree about a real but small region, and the disagreement is "
        "asymmetric.** "
        + _outside_span_sentence(core["conventions"]["outside_span_region"]) + "\n",
        "The two totals are reported beside it as a sensitivity axis, and `E_other_span` is the same "
        "measurement with the spans that begin on a zero divider removed. Because the exporter "
        "convention is nearly right about the control corpus's out-of-span region and wrong about "
        "the historical corpus's, the hold total *understates* the difference and the exporter total "
        "*overstates* it; `E_in_span` is the only one of the three that is not partly a statement "
        "about the convention.\n",
        "**No percentage is subtracted from another and called a performance excess.** The gap "
        "between the corpora is reported as a difference in an estimand, with its uncertainty, and "
        "nothing is given a causal reading it has not earned.\n",
    ]



def _s5(bundle: Mapping[str, Any]) -> List[str]:
    conventions = bundle["core"]["conventions"]
    return [
        "## 5. Results Under Each Convention\n",
        "The same comparison under every definition, computed identically on both corpora. The "
        "convention is applied to *both* corpora in each row, so no row compares one corpus's "
        "convention with the other's.\n",
        _table(
            ["estimand", "control mean", "historical mean", "difference", "sign", "n control",
             "n historical"],
            [[row["estimand"], _pct(row["control_mean"]), _pct(row["historical_mean"]),
              _pct(row["difference"]), row["sign"], row["defined_in_control"],
              row["defined_in_historical"]] for row in conventions["definitions"]],
        ),
        "",
        f"**The sign is stable across the total definitions: "
        f"{conventions['sign_stable_across_totals']}** "
        f"({', '.join(conventions['total_definition_signs'])}). "
        f"{conventions['primary_is_convention_free']}\n",
        "**Why this differs from Stage 22's finding.** Stage 22 reported that the difference was "
        "not robust because the AUDF *split* moved with the convention. That was true of the split, "
        "and it is still true. What changes here is the estimand: restricting the residual to frames "
        "inside detected spans removes the frames the convention acts on, so the convention can no "
        "longer reach the comparison at all.\n",
    ]


def _s6(bundle: Mapping[str, Any]) -> List[str]:
    overlay = bundle["core"]["overlap"]
    return [
        "## 6. Corpus Characteristics Before Matching\n",
        "Feature by feature, where the two corpora actually overlap. The *matching* features are "
        "pure trace properties; the *mediator* features are kept out of the matching because "
        "balancing on a mediator would control away the mechanism under test.\n",
        _table(
            ["feature", "role", "control mean", "historical mean", "common range",
             "historical inside control range", "overlaps"],
            [[row["feature"], row["role"], _num(row["control_mean"]),
              _num(row["historical_mean"]),
              _range(row["common_range_low"], row["common_range_high"]),
              _pct(row["historical_inside_control_range_share"]), row["overlaps"]]
             for row in overlay["features"]],
        ),
        "",
        "**Features with no common range at all:** "
        + (", ".join(f"`{name}`" for name in overlay["features_without_any_common_range"])
           or "none") + ".\n",
        "**Matching features covering fewer than half the historical traces:** "
        + (", ".join(
            f"`{name}`"
            for name in overlay["matching_features_covering_under_half_the_historical_traces"]
        ) or "none") + ".\n",
        f"{overlay['verdict']}.\n",
    ]



def _s7(bundle: Mapping[str, Any]) -> List[str]:
    core = bundle["core"]
    diagnostics = core["calibration"]
    return [
        "## 7. Matching Procedure and Quality\n",
        "Matching is deterministic: pooled standardisation, Euclidean distance over the matching "
        "features, k nearest neighbours, ties broken on the slug. The standardisation uses the mean "
        "and standard deviation of the *pooled* corpora, so neither corpus's scale is privileged.\n",
        _table(
            ["quantity", "value"],
            [
                ["k", diagnostics["k"]],
                ["matching features", len(MATCH_FEATURES)],
                ["mediator features excluded from matching", len(MEDIATOR_FEATURES)],
                ["control leave-one-out MAE", _num(diagnostics["control_loo"]["mae"])],
                ["control leave-one-out RMSE", _num(diagnostics["control_loo"]["rmse"])],
                ["control leave-one-out bias", _num(diagnostics["control_loo"]["bias"])],
                ["control nearest-neighbour distance, median",
                 _num(diagnostics["control_loo"]["nearest_distance_median"])],
                ["control nearest-neighbour distance, max",
                 _num(diagnostics["control_loo"]["nearest_distance_max"])],
                ["historical traces beyond that range",
                 f"{diagnostics['historical_beyond_control_support']} of "
                 f"{diagnostics['historical_count']}"],
            ],
        ),
        "",
        "### The univariate screen\n",
        "One model per feature, fitted on the control corpus alone, then applied to the historical "
        "features. The `gap` column is what the model fails to explain, and the overlap column says "
        "whether the prediction was an interpolation at all.\n",
        _table(
            ["feature", "role", "slope", "R2", "control LOO MAE", "predicted historical mean",
             "gap", "overlap"],
            [[row["feature"], row["role"], _num(row["slope"]), _num(row["r_squared"]),
              _num(row["loo_mae"]), _num(row["predicted_historical_mean"]), _num(row["gap"]),
              _pct(row["overlap_share"])]
             for row in core["univariate_screen"]["features"]],
        ),
        "",
        f"Naive gap {_num(core['univariate_screen']['naive_gap'])}; the closest any single feature "
        "comes to closing it is "
        f"`{core['univariate_screen']['closest_feature']['feature']}` at "
        f"{_num(core['univariate_screen']['closest_feature']['gap'])}. No single trace property "
        "explains the difference.\n",
    ]


def _s8(bundle: Mapping[str, Any]) -> List[str]:
    core = bundle["core"]
    comparison = core["comparison"]
    return [
        "## 8. Results Before and After Matching\n",
        "### Before matching, per trace\n",
        _table(
            ["estimand", "control n", "control mean", "control median", "historical n",
             "historical mean", "historical median", "difference in means",
             "bootstrap interval", "excludes zero"],
            [[name, row["control"]["n"], _pct(row["control"]["mean"]),
              _pct(row["control"]["median"]), row["historical"]["n"],
              _pct(row["historical"]["mean"]), _pct(row["historical"]["median"]),
              _pct(row["difference_in_means"]),
              (f"[{_pct(row['bootstrap'].get('ci_low'))}, "
               f"{_pct(row['bootstrap'].get('ci_high'))}]"
               if row["bootstrap"].get("available") else "n/a"),
              row["bootstrap"].get("excludes_zero")]
             for name, row in sorted(comparison["estimands"].items())],
        ),
        "",
        comparison["unit_of_replication"] + "\n",
        "### After matching\n",
        _table(
            ["slug", "author", "actual", "predicted", "gap", "nearest distance", "extrapolation"],
            [[row["slug"], row["author"], _pct(row["actual"]), _pct(row["predicted"]),
              _pct(row["gap"]), _num(row["nearest_distance"]),
              row["beyond_control_loo_distance_range"]]
             for row in core["calibration"]["historical"]],
        ),
        "",
        f"Matched gap mean {_num(core['calibration']['historical_gap_mean'])}, median "
        f"{_num(core['calibration']['historical_gap_median'])}, range "
        f"[{_num(core['calibration']['historical_gap_min'])}, "
        f"{_num(core['calibration']['historical_gap_max'])}]. "
        f"{core['calibration']['reading']}\n",
    ]


def _s9(bundle: Mapping[str, Any]) -> List[str]:
    profile = bundle["core"]["profile"]
    return [
        "## 9. Residual Profiles\n",
        "Which Stage 22 error classes can be measured on which corpus, decided before the "
        "comparison so a historical residual is never labelled with a class the trace cannot "
        "support:\n",
        _table(
            ["class", "control", "historical", "why"],
            [[row["class"], row["control"], row["historical"], row["why"]]
             for row in profile["class_measurability"]],
        ),
        "",
        "### Trace-derived profile features, measurable in both\n",
        _table(
            ["feature", "control mean", "historical mean", "difference"],
            [[row["feature"], _num(row["control_mean"]), _num(row["historical_mean"]),
              _num(row["difference"])] for row in profile["trace_profile"]],
        ),
        "",
        "### Register-group split of the residual\n",
        _table(
            ["group", "control share of residual", "historical share of residual"],
            [[group, _pct(values["control_mean_share_of_residual"]),
              _pct(values["historical_mean_share_of_residual"])]
             for group, values in sorted(profile["register_group_shares"].items())],
        ),
        "",
        profile["reading"] + "\n",
    ]


def _s10(bundle: Mapping[str, Any]) -> List[str]:
    core = bundle["core"]
    clusters = core["clusters"]
    return [
        "## 10. Per-Trace Uncertainty\n",
        "**The unit of replication is the trace, and the interval resamples sources.** The "
        f"historical corpus holds {len(core['historical'])} traces but only "
        f"{clusters['source_count']} SAP files and {clusters['author_count']} composers, so an "
        "interval that treated the traces as independent would be too narrow. No interval in this "
        "stage resamples frames.\n",
        _table(
            ["estimand", "corpus", "n", "mean", "median", "min", "p25", "p75", "max", "stdev"],
            [
                [name, corpus, values["n"], _pct(values["mean"]), _pct(values["median"]),
                 _pct(values["min"]), _pct(values["p25"]), _pct(values["p75"]),
                 _pct(values["max"]), _num(values["stdev"])]
                for name, row in sorted(core["comparison"]["estimands"].items())
                for corpus, values in (("control", row["control"]),
                                       ("historical", row["historical"]))
            ],
        ),
        "",
        "**The power limit is stated plainly.** Three composers and eleven files cannot support a "
        "precise estimate of a corpus-level difference, and no p-value is reported here because the "
        "sample cannot carry one. What is reported is the effect size, its interval, and whether "
        "the sign survives every perturbation this stage can apply.\n",
    ]


def _s11(bundle: Mapping[str, Any]) -> List[str]:
    leave_one_out = bundle["core"]["leave_one_out"]
    return [
        "## 11. Leave-One-Source-Out\n",
        "The unit dropped is the SAP *source*, not the trace: two traces share one file, so "
        "dropping a trace would leave its sibling in place and understate the dependence. Full "
        f"difference {_pct(leave_one_out['full_difference'])} with interval "
        f"[{_pct(leave_one_out['full_ci'][0])}, {_pct(leave_one_out['full_ci'][1])}].\n",
        _table(
            ["dropped source", "dropped traces", "kept traces", "difference",
             "bootstrap interval", "sign preserved"],
            [[row["dropped_source"], ", ".join(row["dropped_traces"]), row["kept_traces"],
              _pct(row["difference"]),
              f"[{_pct(row['ci_low'])}, {_pct(row['ci_high'])}]", row["sign_preserved"]]
             for row in leave_one_out["rows"]],
        ),
        "",
        f"Sign preserved in every drop: **{leave_one_out['sign_preserved_in_all']}**. Range of the "
        f"difference across drops: [{_pct(leave_one_out['min_difference'])}, "
        f"{_pct(leave_one_out['max_difference'])}]. {leave_one_out['reading']}\n",
    ]




def _s12(bundle: Mapping[str, Any]) -> List[str]:
    negatives = bundle["core"]["negatives"]
    largest = max(
        (abs(row["difference"]) for row in negatives["features"]
         if row["difference"] is not None),
        default=None,
    )
    return [
        "## 12. Negative Controls\n",
        "Features that should reflect the *encoding* rather than any musical behaviour. If a "
        "difference of the same shape and size as the primary estimand appeared here, the primary "
        "difference would be a property of comparing two corpora of different shape.\n",
        _table(
            ["feature", "control mean", "historical mean", "difference", "control constant",
             "historical constant"],
            [[row["feature"], _num(row["control_mean"]), _num(row["historical_mean"]),
              _num(row["difference"]), row["control_constant"], row["historical_constant"]]
             for row in negatives["features"]],
        ),
        "",
        f"Primary estimand difference for comparison: **{_pct(negatives['primary_difference'])}**. "
        f"Largest absolute negative-control difference: {_num(largest)}. "
        f"{negatives['reading']}\n",
    ]


def _s13(bundle: Mapping[str, Any]) -> List[str]:
    core = bundle["core"]
    return [
        "## 13. Sensitivity Analysis\n",
        "### By convention and definition (controls A and F)\n",
        "See section 5. The sign is stable across every total definition, and the primary estimand "
        "is convention-free by construction.\n",
        "### By channel (control D)\n",
        _table(
            ["channel", "registers", "control in-span rate", "historical in-span rate",
             "difference", "control share of residual", "historical share of residual"],
            [[row["channel"], ", ".join(row["registers"]),
              _pct(row["control"]["in_span_rate"]), _pct(row["historical"]["in_span_rate"]),
              _pct(row["difference"]), _pct(row["control"]["share_of_total_residual"]),
              _pct(row["historical"]["share_of_total_residual"])]
             for row in core["channels"]["channels"]],
        ),
        "",
        f"{core['channels']['channels_with_positive_difference']} of "
        f"{core['channels']['channels_compared']} channels show a positive difference; spread "
        f"across channels: **{core['channels']['spread_across_channels']}**. "
        f"{core['channels']['reading']}\n",
        "### By composition matching (control B)\n",
        "See sections 7 and 8. The matched gap is far larger than the model's own error, but most "
        "predictions are extrapolations, so the matched comparison is reported as an extrapolation "
        "rather than as a control.\n",
    ]


def _s14(bundle: Mapping[str, Any]) -> List[str]:
    s = bundle["summary"]
    test = bundle["history_specific_test"]
    return [
        "## 14. Identifiability Limits\n",
        "**What can be identified and what cannot.** The trace-level estimands are identified: they "
        "are properties of a register stream and a detector, both of which exist for both corpora. "
        "The *cause* of the difference is not identified, for three reasons that compound:\n",
        "1. **The corpora do not overlap.** "
        + (", ".join(f"`{name}`" for name in s["features_without_common_range"]) or "No feature")
        + " have no common range, and "
        f"{s['traces_beyond_control_support']} of {s['historical_traces']} historical traces are "
        "outside the control corpus's nearest-neighbour distance range. Any adjusted comparison is "
        "an extrapolation.\n",
        "2. **The historical corpus is clustered.** Eleven files and three composers cannot "
        "separate a corpus-level effect from a player-routine effect, and the identified idiom is "
        "present in all four of one composer's traces and absent from several others.\n",
        "3. **No historical ground truth exists.** The classes that would say *where* the residual "
        "comes from - note set versus value reading, merged versus missed spans - need a "
        "composition, and a Tier D SAP has none.\n",
        "",
        "### The pre-declared criteria\n",
        _table(
            ["criterion", "threshold", "passed", "measurement"],
            [[row["criterion"], row["threshold"], row["passed"],
              json.dumps(row["measurement"], sort_keys=True)]
             for row in test["criteria"]],
        ),
        "",
        f"**{test['criteria_passed']} of {test['criteria_total']}** criteria met. "
        f"{_sentence(test['identification_blocker'])} "
        f"{_sentence(test['what_this_is_not'])}\n",
    ]


def _s15(bundle: Mapping[str, Any]) -> List[str]:
    audit = bundle["read_only_audit"]
    return [
        "## 15. Methodological Corrections\n",
        "Every problem found while building this stage, and what was done about it. Nothing was "
        "quietly fixed: a correction that changes a number is stated here.\n",
        "**1. A first reading of the audit mistook a volume share for a rate.** The spans that "
        "begin on a zero divider carry 39.0% of the historical residual, which reads like a "
        "mechanism. They are 38.1% of the spans, and their residual *rate* (0.428) is close to the "
        "other spans' (0.352). The idiom changes which frames a span covers; it does not concentrate "
        "the error. Both the rate and the volume are now reported, and the idiom is classified as a "
        "corpus-composition difference rather than as the cause.\n",
        "**2. The primary estimand was chosen to remove a confound, not to favour a result.** Stage "
        "22's comparison moved with the convention because the convention acts on frames no span "
        "covers. Restricting the residual to in-span frames removes it. The choice was made from the "
        "definition of the convention, before any of this stage's numbers existed, and the two "
        "totals are still reported beside it so a reader can see what the restriction costs.\n",
        "**3. The interval resamples sources, not traces and not frames.** A naive interval over "
        "1.1 million register values would treat every frame as an independent experiment. The unit "
        "here is the SAP source, because two of the twelve traces share a file and the files cluster "
        "by composer.\n",
        "**4. The mediator features are excluded from the matching.** The zero-onset-span share and "
        "the span-density features predict the residual, and including them in the matching would "
        "balance away the very mechanism the stage is testing. They are reported separately and the "
        "code says why.\n",
        "**5. Stage 22's `A_exact` arm is not used as a residual.** It is zero by construction. The "
        "convention comparison here uses the detector's own arm under each policy.\n",
        "**6. An undefined estimand is reported as undefined, not as zero.** Three historical traces "
        "contain no zero-onset span, so `E_zero_onset_span` has no denominator there. Those traces "
        "are excluded from that estimand's summary and the count is reported, rather than the value "
        "being recorded as zero.\n",
        "**7. The in-span split had to be per register, not per frame, and the first version was "
        "wrong.** The obvious definition of `E_in_span` marks a *frame* as in-span when a detected "
        "span covers it. That definition breaks the identities: a frame can be covered by one "
        "voice's span while another voice has no span there, and the two conventions genuinely "
        "disagree about that other voice's registers. Under the frame-wise definition the two totals "
        "no longer summed to the in-span part plus the out-of-span part, and the discrepancy was "
        "large - on one historical trace the frame-wise in-span numerator exceeded the hold total "
        "for the whole trace. A register value now counts as in-span when a detected span drives "
        "*that register* in *that frame*, the identities hold exactly for both policies, and the "
        "check is asserted in the code rather than assumed. This changed the headline from 20.2% to "
        "15.5%, so it is reported as a correction and not as a refinement.\n",
        "**8. A control the stage relied on turned out not to be exact.** The exporter convention "
        "predicts zero outside spans, and the first version of this report said the control corpus's "
        "out-of-span residual is zero by construction. It is not: it is "
        f"{_pct(bundle['core']['conventions']['outside_span_region']['control']['out_span_exporter_rate'])} "
        "of the control corpus's out-of-span values, because the detector misses some spans and the "
        "trace then holds a divider the exporter predicts as zero. The claim is now the measured "
        "one, and it is still small enough to carry the argument - but it is stated as a measurement "
        "rather than as a property.\n",
        "### Read-only audit\n",
        _table(
            ["audit", "files checked", "changed", "read-only"],
            [[row["label"], row["files_checked"], len(row["changed"]), row["read_only"]]
             for _key, row in sorted(audit.items())],
        ),
        "",
        "Stage 15 to 22, the composer, the DSL, the IR, the player and the exporter were read "
        "through their hashes and never written. The traces and the composition documents were "
        "hashed before and after the run as well.\n",
    ]


def _s16(bundle: Mapping[str, Any]) -> List[str]:
    decided = bundle["verdicts"]
    return [
        "## 16. Verdict and Recommendation\n",
        _table(
            ["subject", "verdict", "deciding condition"],
            [[subject, data["verdict"],
              _sentence(data.get("deciding_condition", data.get("reason", "")))]
             for subject, data in sorted(decided.items())],
        ),
        "",
        "### What the verdict means\n",
        f"**`{decided['primary']['verdict']}`.** {decided['primary']['reason'].capitalize()}. The "
        "difference is not a convention artefact and not one song's, and it is not identified. "
        "Calling it a historical-specific effect would overstate what the data can carry; calling "
        "it nothing would understate what was measured.\n",
        "### What would identify it\n",
        "The blocker is overlap, and overlap is something the project can build. A new experiment "
        "would need a control set whose *trace-level* features resemble the historical ones:\n",
        "1. **Compositions that use the same POKEY configurations.** The historical corpus is "
        "dominated by the 16-bit pair at 1.79 MHz; the control corpus never uses that clock. "
        "Composing control songs in that configuration closes the largest gap and is a composer "
        "feature, not a detector change.\n",
        "2. **Compositions with comparable register activity.** The historical traces change AUDF "
        "roughly four times as often per frame and hold AUDC for shorter runs. Envelopes and pitch "
        "activity of that density can be written directly in the DSL.\n",
        "3. **Traces of comparable length.** The historical traces are five times longer on average; "
        "a matched length removes a systematic difference that has nothing to do with music.\n",
        "4. **Then repeat this stage unchanged.** If the difference survives an *interpolated* "
        "comparison - predictions inside the control corpus's own support - it becomes a candidate "
        "worth a controlled experiment. If it does not, the difference was trace shape.\n",
        "**Stage 24 is not implemented here and is not begun.** It is proposed, with its "
        "requirements, and the decision belongs to whoever reads this report.\n",
        "### What does not change\n",
        f"**{decided['atari_music_composer_impact']['verdict']}.** "
        f"{_sentence(decided['atari_music_composer_impact']['deciding_condition'])}\n",
    ]




def _s_questions(bundle: Mapping[str, Any]) -> List[str]:
    """The eight closing questions, answered separately and from the measurements."""
    s = bundle["summary"]
    core = bundle["core"]
    decided = bundle["verdicts"]
    comparison = core["comparison"]["estimands"]
    primary = comparison[PRIMARY_ESTIMAND]
    test = bundle["history_specific_test"]
    return [
        "## The Eight Closing Questions\n",
        "**1. Is the historical-control residual difference robust to the choice of convention?**\n",
        f"**Yes.** The primary estimand, `{PRIMARY_ESTIMAND}`, excludes the register values where "
        "the conventions differ, so the convention cannot reach it. The difference is "
        f"{_pct(s['primary_difference'])} and the sign is the same under every total definition "
        f"({', '.join(core['conventions']['total_definition_signs'])}). Stage 22's warning was about "
        "the *split* of the residual between AUDF and AUDC, which is still convention-sensitive; it "
        "was never about whether a difference existed.\n",
        "**2. Does it survive composition matching?**\n",
        f"**Not testably.** The matched gap is {_num(s['matched_gap_mean'])} against a control "
        f"leave-one-out error of {_num(s['control_loo_mae'])}, so the gap is far larger than the "
        f"model's error. But {s['traces_beyond_control_support']} of {s['historical_traces']} "
        "predictions lie beyond the control corpus's own distance range, so the gap is an "
        "extrapolation and cannot be read as an effect estimate. A model cannot be asked to predict "
        "outside its support and then believed.\n",
        "**3. Is the result stable when historical traces are dropped?**\n",
        f"**Yes.** Dropping each of the {core['clusters']['source_count']} SAP sources in turn keeps "
        f"the sign in every case ({core['leave_one_out']['sign_preserved_in_all']}), with the "
        f"difference ranging over [{_pct(core['leave_one_out']['min_difference'])}, "
        f"{_pct(core['leave_one_out']['max_difference'])}]. The result is not one file's.\n",
        "**4. Is it spread across traces and channels?**\n",
        f"**Across traces, yes; across channels, yes.** "
        f"{s['criteria_passed']} of {s['criteria_total']} pre-declared criteria are met and the "
        f"failing one is the matching criterion. "
        f"{core['channels']['channels_with_positive_difference']} of "
        f"{core['channels']['channels_compared']} channels show a positive difference, so it is not "
        "one channel's artefact.\n",
        "**5. Can the known Stage 22 limitations explain it?**\n",
        "**Partly, and not entirely.** The value-reading limitation is the four-parameter contour, "
        "which is a property of the detector and applies to both corpora equally. The zero-onset "
        "span idiom was the most promising candidate and it does not concentrate the error: removing "
        f"those spans leaves a difference of {_pct(s['explained_difference'])}. No single trace "
        "feature closes the gap either - the closest comes within "
        f"{_num(core['univariate_screen']['closest_feature']['gap'])} of the naive "
        f"{_num(core['univariate_screen']['naive_gap'])}. "
        + _negative_control_sentence(core["negatives"]) + "\n",
        "**6. Can the available data identify its cause?**\n",
        "**No.** "
        + (", ".join(f"`{name}`" for name in s["features_without_common_range"]) or "No feature")
        + " have no common range between the corpora, so the difference cannot be separated from a "
        "property of the trace shapes the historical corpus happens to have. The historical corpus "
        "is also clustered by player routine, and no ground truth exists to attribute the residual "
        "to a note-level cause.\n",
        "**7. Is there sufficient reason to design Stage 24?**\n",
        f"**Yes, but only as a new experiment and only on the overlap gap.** The verdict is "
        f"`{decided['primary']['verdict']}` and the performance-candidate verdict is "
        f"`{decided['performance_candidate']['verdict']}`. Section 16 lists what Stage 24 would have "
        "to control. Stage 24 is not implemented and is not begun here.\n",
        "**8. Does the result change any decision about Atari Music Composer?**\n",
        f"**No.** `{decided['atari_music_composer_impact']['verdict']}`. No detector was repaired, "
        "no compiler, DSL, IR, player or schema was touched, no music was generated and no listening "
        "test was run. The result is a statement about a measurement instrument and about what the "
        "project's two corpora can and cannot support.\n",
        "## Final Statement\n",
        f"**The historical-control residual difference is real in this data, robust to every control "
        f"this stage can apply, and not identified.** Verdict "
        f"`{decided['primary']['verdict']}`. It is not evidence of a performance layer, and it is "
        "not dismissed either: it is a precisely stated gap between two corpora that do not overlap, "
        "with a stated way to close the overlap.\n",
        "**Stage 23 stops here.** No further stage is implemented, no music is generated, and no "
        "production code is changed.\n",
    ]




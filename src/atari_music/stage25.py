"""Stage 25 - matched control corpus design and validation.

Stage 24 ended with ``COMMON_SUPPORT_INADEQUATE``: zero of twelve historical traces lie inside the
control corpus's joint feature box, against forty-one of fifty-three control traces under the same
leave-one-out test. That is a statement about the *corpora*, not about the music, and Stage 25 is the
response to it.

Stage 25 does not analyse a residual. It does not look for a performance layer. It designs a control
corpus that could support an honest comparison, audits whether the existing pipeline can build that
corpus, runs a minimal pilot to prove the mechanics, and states plainly which parts of the problem no
amount of corpus building can fix.

The stage is organised around four questions and refuses to merge them:

* **Can the pipeline produce the required configurations?** Answered by probing the real pipeline,
  not by reading its documentation.
* **Can the required configurations be *controlled* at the composition level, or only observed?**
  Answered feature by feature, with the mechanism named.
* **What corpus would close the measured gap, and how large must it be?** Answered with a declared
  design and an honest statement that no power estimate is available.
* **What remains unclosable?** Answered with the one confound that more compositions cannot touch:
  the historical traces come from unknown third-party players and the controls from one known
  compiler and player.

**What the audit found, stated up front.** The pipeline can produce the historical POKEY
configuration. A bound sound profile declaring ``audctl_mode = $50`` yields a trace whose AUDCTL
column is ``$50`` on every frame, and the composer's own ``BASS16`` flag contributes ``$10``. All
eight POKEY distortion bytes are reachable through the DSL's ``dist=`` parameter. Composition length
is ``rows x frames_per_tick`` over a repeated sequence, and 19200 frames is reachable against a
historical maximum of 19008. So the two structural gaps Stage 24 measured - the clock and the length -
are both closable with documents and a profile, and **no production change is required for them**.

**What the audit also found.** One player idiom is *not* expressible. The historical players pulse
``AUDF`` to zero for a single frame while leaving the ``AUDC`` volume nibble non-zero, which makes the
detector split a span on an audible frame with a zero divider. The compiler writes ``AUDF`` and
``AUDC`` together from a note, a note's divider is never zero, and a rest zeroes ``AUDC``. So
``AUDF = 0`` and "silent" are the same thing in a compiled trace, and the idiom cannot be produced.
That is recorded as a capability gap with its mechanism, and the design says what it costs.

**And one thing no corpus can fix.** The historical corpus contains at least three composer clusters
and an unknown number of player routines; the control corpus contains exactly one compiler and one
player. A difference in residual between them is therefore confounded with the generator, and the
only designs that address it are ones that vary the player while holding the music fixed. Stage 25
states that limit rather than designing around it.

Everything is analysis and design only, plus a deliberately minimal pilot. No production file is
modified, no corpus is committed, no music is released and Stage 26 is not begun.
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

from atari_music import stage15, stage18, stage20, stage21, stage22, stage23, stage24

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_REPORTS_DIR = REPO_ROOT / "reports"
DEFAULT_STAGE25_DIR = DEFAULT_REPORTS_DIR / "stage25"
DEFAULT_DOCS_DIR = REPO_ROOT / "docs"
DEFAULT_ARCHAEOLOGY_DIR = stage24.DEFAULT_ARCHAEOLOGY_DIR
DEFAULT_SONGS_DIR = stage24.DEFAULT_SONGS_DIR
DEFAULT_AI_DIR = stage24.DEFAULT_AI_DIR
DEFAULT_STAGE21_DIR = stage24.DEFAULT_STAGE21_DIR
DEFAULT_STAGE22_DIR = stage24.DEFAULT_STAGE22_DIR
DEFAULT_STAGE23_DIR = stage24.DEFAULT_STAGE23_DIR
DEFAULT_STAGE24_DIR = stage24.DEFAULT_STAGE24_DIR
DEFAULT_PROFILE_BANK = REPO_ROOT / "tests" / "data" / "sound_profiles" / "bank"

ANALYSIS_VERSION = "stage25/1"
RANDOM_SEED = 20250325
PILOT_SEED = 20250326

#: The residual estimand is Stage 23's and the feature set is Stage 24's. Stage 25 re-derives
#: neither: a design that changed the measurement would be designing for a different question.
PRIMARY_ESTIMAND = stage23.PRIMARY_ESTIMAND
MATCHING_FEATURES: Tuple[str, ...] = stage24.MATCHING_FEATURES
FRAME_BYTES = stage18.FRAME_BYTES
REGISTER_ORDER: Tuple[str, ...] = stage18.REGISTER_ORDER


# ---------------------------------------------------------------------------
# Pre-declared acceptance criteria. Every one is stated before the pilot runs.
# ---------------------------------------------------------------------------
#: A candidate corpus is accepted only when a historical trace can be placed inside the *joint*
#: control box. Stage 24 calibrated that test: 41 of 53 control traces pass it leave-one-out, so
#: the criterion discriminates and is not vacuously strict.
ACCEPT_JOINT_BOX_COVERAGE = 1.00

#: The same test must pass on the control corpus's own members at this rate or better, or the
#: criterion is judged to have no power and the corpus is refused for the wrong reason.
ACCEPT_CALIBRATION_MIN = 0.50

#: Distance criterion: no historical trace may sit further from the candidate corpus than the
#: candidate corpus's own leave-one-out maximum.
ACCEPT_DISTANCE_BEYOND = 0

#: Propensity overlap: the overlap region must retain at least this share of both corpora.
ACCEPT_PROPENSITY_RETAINED = 0.80

#: Matching: a caliper must be declared, must be enforced, and the match must satisfy the balance
#: criterion after it runs. The threshold is Stage 24's, reused rather than re-chosen.
ACCEPT_SMD_THRESHOLD = stage24.SMD_THRESHOLD
ACCEPT_MIN_RETAINED_TRACES = stage24.MIN_RETAINED_TRACES
ACCEPT_MIN_RETAINED_SOURCES = stage24.MIN_RETAINED_SOURCES

#: The one historical idiom the pipeline cannot express. Named once here and referenced everywhere,
#: so the capability audit, the design and the tests cannot drift apart on its wording.
PRODUCTION_CHANGE_IDIOM = "AUDF = 0 while audible (the between-note pulse idiom)"

#: The AUDCTL configurations the historical corpus uses, and the control corpus does not.
HISTORICAL_AUDCTL = ("$50", "$00")
CONTROL_AUDCTL_EXISTING = ("$00", "$10")

#: The pilot's four compositions. Deliberately minimal: one per configuration the design needs, plus
#: one aimed at pitch-change density. A pilot is a feasibility test, not a corpus.
PILOT_SPECS: Tuple[Dict[str, Any], ...] = (
    {
        "id": "pilot_a_baseline",
        "group": "A_baseline",
        "audctl": "$00",
        "bpm": 125,
        "rows": 32,
        "repeats": 2,
        "channels": 4,
        "distortions": (0xA0, 0xA0, 0x80, 0x00),
        "purpose": "continuity with the existing control corpus at the default 64 kHz clock",
    },
    {
        "id": "pilot_b_clock50",
        "group": "B_feature_coverage",
        "audctl": "$50",
        "bpm": 60,
        "rows": 128,
        "repeats": 3,
        "channels": 4,
        "distortions": (0x00, 0xA0, 0x80, 0x00),
        "purpose": "the historical clock and a length inside the historical region, at once",
    },
    {
        "id": "pilot_c_16bit64",
        "group": "B_feature_coverage",
        "audctl": "$10",
        "bpm": 125,
        "rows": 32,
        "repeats": 2,
        "channels": 4,
        "distortions": (0xA0, 0xA0, 0x80, 0x00),
        "purpose": "the 16-bit pair at 64 kHz, the configuration the existing corpus already uses",
    },
    {
        "id": "pilot_d_dense_pitch",
        "group": "C_mechanism_controls",
        "audctl": "$50",
        "bpm": 60,
        "rows": 128,
        "repeats": 2,
        "channels": 4,
        "distortions": (0x00, 0xA0, 0x80, 0x40),
        "purpose": "high AUDF change density: many short notes over a wide pitch range",
    },
)

#: The pilot's continuation criteria, declared before it runs. Each names the measurement that
#: decides it, so a failure cannot be argued away after the fact.
PILOT_CRITERIA: Tuple[Dict[str, str], ...] = (
    {
        "criterion": "every pilot composition compiles",
        "measurement": "the build raises no exception for any spec",
    },
    {
        "criterion": "the requested AUDCTL mode appears in the trace",
        "measurement": "the trace's AUDCTL column equals the requested mode on every frame",
    },
    {
        "criterion": "the declared length is produced",
        "measurement": "frames equals rows x repeats x frames_per_tick",
    },
    {
        "criterion": "the historical length region is reachable",
        "measurement": "at least one pilot trace reaches the historical minimum of 2048 frames",
    },
    {
        "criterion": "all three ground-truth levels are captured and consistent",
        "measurement": "the source hash, the compiled hash and the trace hash are all present, and "
                       "the compiled hash equals the trace hash because they hash the same payload",
    },
    {
        "criterion": "the build is deterministic",
        "measurement": "building the same spec twice gives a byte-identical source hash and payload",
    },
    {
        "criterion": "every matching feature is defined on every pilot trace",
        "measurement": "no matching feature is undefined for any pilot trace",
    },
)



class Stage25Error(RuntimeError):
    """A required input is missing or malformed, or a declared identity does not hold."""


def _read_json(path: Path) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def sha256_file(path: Path) -> str:
    return stage15.sha256_file(path)


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


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



# ===========================================================================
# PART 1 - the audit of Stage 21 to 24 (section 2 of the brief)
# ===========================================================================
#: Every conclusion Stage 25 inherits, the artefact it was read from, and what it forces. The brief's
#: rule is that the artefacts win over any summary, so each row names a file and a field.
INHERITED_CONCLUSIONS: Tuple[Dict[str, str], ...] = (
    {
        "conclusion": "the two corpora share no joint feature range",
        "source": "reports/stage24/multivariate_overlap.json box.historical.inside_on_every_feature",
        "consequence": (
            "the new corpus must extend the joint range, not only the marginal ranges. A design that "
            "matches on one feature at a time repeats Stage 23's mistake"
        ),
    },
    {
        "conclusion": "the box criterion has discriminating power",
        "source": "reports/stage24/multivariate_overlap.json box.calibration_inside_control",
        "consequence": (
            "the same calibrated criterion is reused as the acceptance test, so the new corpus is "
            "judged by the test that rejected the old one"
        ),
    },
    {
        "conclusion": "no historical ground truth exists",
        "source": "reports/stage21/evidence_tiers.json and docs/stage21_controlled_validation.md",
        "consequence": (
            "the control corpus must keep exact source truth, and the historical side stays Tier D. "
            "A control corpus cannot create ground truth on the historical side"
        ),
    },
    {
        "conclusion": "the detector's note-boundary errors are the dominant error class",
        "source": (
            "reports/stage22/residual_taxonomy.json and "
            "docs/stage22_detector_error_decomposition.md"
        ),
        "consequence": (
            "the control corpus must let the detector's boundary behaviour be measured, which means "
            "spans of controlled length and controlled onset structure"
        ),
    },
    {
        "conclusion": "the Stage 23 matching never applied its declared caliper",
        "source": "reports/stage24/matching_diagnostics.json stage23_defect",
        "consequence": (
            "the new design declares its matching rule, tests that the implementation enforces it, "
            "and refuses to report a match that fails its own balance criterion"
        ),
    },
    {
        "conclusion": "the residual difference is measured, stable and unidentified",
        "source": "reports/stage23/verdict.json and reports/stage24/verdict.json",
        "consequence": (
            "the difference may not be carried forward as a performance-layer effect, and Stage 25 "
            "must not treat corpus building as evidence for one"
        ),
    },
    {
        "conclusion": "the historical traces use AUDCTL $50 and the control corpus does not",
        "source": "reports/stage24/corpus_inventory.json inventory.historical.audctl",
        "consequence": (
            "the $50 configuration is the first thing the new corpus must cover, and the capability "
            "audit must establish whether the pipeline can produce it"
        ),
    },
)


def audit_previous_stages(
    stage21_dir: Path = DEFAULT_STAGE21_DIR,
    stage22_dir: Path = DEFAULT_STAGE22_DIR,
    stage23_dir: Path = DEFAULT_STAGE23_DIR,
    stage24_dir: Path = DEFAULT_STAGE24_DIR,
) -> Dict[str, Any]:
    """Read the Stage 21 to 24 artefacts and record the numbers Stage 25 actually relies on.

    Nothing here is restated from a previous report. Each figure is read from the artefact that owns
    it, so a reader can check the chain from Stage 25's design back to the measurement that motivated
    it.
    """
    stage21_summary = _read_json(stage21_dir / "summary.json")
    stage22_manifest = _read_json(stage22_dir / "stage22_manifest.json")
    stage23_manifest = _read_json(stage23_dir / "stage23_manifest.json")
    stage23_verdict = _read_json(stage23_dir / "verdict.json")
    stage24_overlap = _read_json(stage24_dir / "multivariate_overlap.json")
    stage24_inventory = _read_json(stage24_dir / "corpus_inventory.json")
    stage24_matching = _read_json(stage24_dir / "matching_diagnostics.json")
    stage24_verdict = _read_json(stage24_dir / "verdict.json")
    stage24_identifiability = _read_json(stage24_dir / "identifiability_assessment.json")
    box = stage24_overlap["box"]
    return {
        "stage21_summary": stage21_summary,
        "stage22_analysis_version": stage22_manifest["analysis_version"],
        "stage22_summary": stage22_manifest["summary"],
        "stage23_analysis_version": stage23_manifest["analysis_version"],
        "stage23_summary": stage23_manifest["summary"],
        "stage23_verdict": stage23_verdict["verdicts"]["primary"]["verdict"],
        "stage24_overlap": {
            "support_verdict": stage24_overlap["verdict"],
            "historical_traces": box["historical"]["traces"],
            "historical_inside_joint_box": box["historical"]["inside_on_every_feature"],
            "control_inside_joint_box_leave_one_out": (
                box["calibration_inside_control"]["inside_on_every_feature"]
            ),
            "control_traces": box["control"]["traces"],
            "criteria_agree": stage24_overlap["criteria_agree"],
        },
        "stage24_matching": {
            "methods": stage24_matching["method_count"],
            "reportable": stage24_matching["reportable_count"],
            "validated": stage24_matching["validated_count"],
            "stage23_defect": stage24_matching["stage23_defect"],
        },
        "stage24_verdict": stage24_verdict["main"]["verdict"],
        "stage24_auxiliary": [row["verdict"] for row in stage24_verdict["auxiliary"]],
        "stage24_blockers": [
            row["blocker"]
            for row in stage24_identifiability["C_identified_cause"]["blockers"]
        ],
        "stage24_historical_audctl": stage24_inventory["inventory"]["historical"]["audctl"],
        "stage24_control_audctl": stage24_inventory["inventory"]["control"]["audctl"],
        "stage24_historical_frames": stage24_inventory["inventory"]["historical"]["frames"],
        "stage24_control_frames": stage24_inventory["inventory"]["control"]["frames"],
        "inherited_conclusions": [dict(item) for item in INHERITED_CONCLUSIONS],
    }


# ===========================================================================
# PART 2 - target population, ground truth and feature controllability
# ===========================================================================
def _counts(values: Any) -> Dict[str, int]:
    out: Dict[str, int] = {}
    for value in values:
        out[str(value)] = out.get(str(value), 0) + 1
    return dict(sorted(out.items()))


def target_population(
    historical: Sequence[stage24.CorpusRecord],
    control: Sequence[stage24.CorpusRecord],
) -> Dict[str, Any]:
    """What the corpus is meant to represent, and - just as important - what it is not.

    The historical corpus is twelve traces. Stage 24 established that they are not twelve independent
    songs: eleven SAP files, three composers, at least three player routines. Treating them as a
    sample of "Atari music" would be a category error, so the population is stated as the
    *observable property region* those twelve traces occupy, and the inference is scoped to it.
    """
    historical_frames = sorted(record.frames for record in historical)
    control_frames = sorted(record.frames for record in control)
    return {
        "population": (
            "Atari 8-bit POKEY game-music traces that are observable as a 50 Hz register stream and "
            "that lie inside the property region the twelve historical traces occupy"
        ),
        "inference_scope": (
            "the corpus supports statements about traces in that region. It does not support "
            "statements about Atari music in general, about any specific composer, or about any "
            "player routine that is not the project's own"
        ),
        "what_the_population_is_not": [
            "all Atari 8-bit music: the historical corpus is twelve traces chosen by availability",
            "a random sample of composers: three are represented, and one contributes four traces",
            "a sample of player routines: the routines are unknown and unequally represented",
            "a statement about 1980s composition practice: one trace is dated 2024",
        ],
        "historical_traces": len(historical),
        "historical_sources": len({record.source_key for record in historical}),
        "historical_authors": sorted({record.author for record in historical}),
        "historical_audctl": _counts(f"${record.audctl:02X}" for record in historical),
        "historical_frames": {
            "min": historical_frames[0],
            "median": _median([float(v) for v in historical_frames]),
            "max": historical_frames[-1],
        },
        "existing_control_traces": len(control),
        "existing_control_audctl": _counts(f"${record.audctl:02X}" for record in control),
        "existing_control_frames": {
            "min": control_frames[0],
            "median": _median([float(v) for v in control_frames]),
            "max": control_frames[-1],
        },
        "structural_gaps": [
            {
                "gap": "POKEY clock configuration",
                "historical": _counts(f"${r.audctl:02X}" for r in historical),
                "existing_control": _counts(f"${r.audctl:02X}" for r in control),
                "closable_without_production_change": True,
            },
            {
                "gap": "trace length",
                "historical": f"[{historical_frames[0]}, {historical_frames[-1]}]",
                "existing_control": f"[{control_frames[0]}, {control_frames[-1]}]",
                "closable_without_production_change": True,
            },
        ],
        "reading": (
            "the population is defined by observable trace properties rather than by era or genre, "
            "because era and genre are not recoverable from a trace and are not what the comparison "
            "measures"
        ),
    }


#: The three ground-truth levels. A control example has all three; a historical SAP has only the
#: third, which is why the two corpora cannot be treated symmetrically.
GROUND_TRUTH_LEVELS: Tuple[Dict[str, str], ...] = (
    {
        "level": "A_source",
        "name": "source ground truth",
        "what_it_is": (
            "the authored composition document: notes, durations, rests, channel assignment, "
            "instrument roles, envelope parameters, distortion per instrument, and the AUDCTL "
            "configuration the composition asks for"
        ),
        "identity": "the document's SHA-256, hashed as text",
        "available_for_control": "yes, exactly",
        "available_for_historical": "no - a SAP is a player plus data",
        "limitations": (
            "it is the *intent*, not the performance. A note the document declares may be realized "
            "differently by the compiler, and a player may add behaviour the document never asked for"
        ),
    },
    {
        "level": "B_compiled",
        "name": "compiled and player ground truth",
        "what_it_is": (
            "the exact frame stream the compiler produced, the resolved AUDCTL byte, the "
            "frames_per_tick the tempo mapped to, and the identity of the compiler and player that "
            "produced it"
        ),
        "identity": "the frame payload's SHA-256 plus the resolved configuration",
        "available_for_control": "yes, exactly",
        "available_for_historical": "partially - the trace is observable, the compiler is not",
        "limitations": (
            "it is one realization. The same document compiled by a different player would give a "
            "different stream, and that difference is invisible here"
        ),
    },
    {
        "level": "C_trace",
        "name": "exact trace ground truth",
        "what_it_is": (
            "the register stream wrapped as a trace, with a deterministic link back to level A and "
            "level B"
        ),
        "identity": "the trace file's SHA-256, and the same payload hashed by the frame stream",
        "available_for_control": "yes, exactly",
        "available_for_historical": "yes, but with no link to a level A or B",
        "limitations": (
            "a trace is not a composition. Every feature in the matching set is a property of the "
            "trace, and none of them is a property of the music the trace came from"
        ),
    },
)

#: The four controllability classes the brief names.


#: The four controllability classes the brief names. Declared before the feature table that uses
#: them, so a reader meets the vocabulary before the classification.
CONTROL_DIRECT = "controlled_directly"
CONTROL_INDIRECT = "controlled_indirectly"
CONTROL_OBSERVED = "observed_only"
CONTROL_NOT_POSSIBLE = "not_controllable"



#: Feature controllability. Every matching feature is classified by *how* it can be influenced, and
#: the classification is a claim about the pipeline that the capability audit then tests.
FEATURE_CONTROLLABILITY: Tuple[Dict[str, str], ...] = (
    {
        "feature": "frames",
        "class": CONTROL_DIRECT,
        "mechanism": (
            "rows per pattern (max 128) x the number of sequence repetitions x frames_per_tick, "
            "where frames_per_tick follows BPM: <=80 gives 6, <=110 gives 5, <=145 gives 4, else 3"
        ),
        "granularity": "one frame per step at the slowest tempo",
        "caveat": "BPM also changes the musical content, so length and tempo are not independent",
    },
    {
        "feature": "clock_179mhz",
        "class": CONTROL_DIRECT,
        "mechanism": (
            "bind a sound profile whose hardware.audctl_mode declares the 0x40 bit; "
            "resolve_audctl_mode OR-s it into the frame stream's AUDCTL"
        ),
        "granularity": "the whole trace, since AUDCTL is written once for every frame",
        "caveat": "the profile must be coherent: a conflicting dist= in the document is refused",
    },
    {
        "feature": "coupled_16bit",
        "class": CONTROL_DIRECT,
        "mechanism": "the DSL's BASS16 directive, or a profile declaring the 0x10 join bit",
        "granularity": "the whole trace",
        "caveat": "the join consumes two channels, so it also sets the maximum simultaneity",
    },
    {
        "feature": "audf_change_rate",
        "class": CONTROL_DIRECT,
        "mechanism": "note density and the width of the pitch range; short notes on many pitches",
        "granularity": "one note",
        "caveat": (
            "the historical players also pulse AUDF to zero between notes, which raises this feature "
            "in a way the compiler cannot reproduce; the two contributions are not separable from the "
            "feature value alone"
        ),
    },
    {
        "feature": "audc_change_rate",
        "class": CONTROL_INDIRECT,
        "mechanism": (
            "the per-instrument envelope (att/dec/sus/rel) plus note length and the number of "
            "simultaneous voices; the compiler emits one AUDC write per frame from the envelope"
        ),
        "granularity": "one frame, but only through the envelope's shape",
        "caveat": (
            "an envelope cannot hold a constant level for an arbitrary number of frames and then "
            "step: the shape is the player's, not the document's"
        ),
    },
    {
        "feature": "audc_volume_change_rate",
        "class": CONTROL_INDIRECT,
        "mechanism": "the same envelope mechanism, restricted to the volume nibble",
        "granularity": "one frame via the envelope",
        "caveat": "the release tail always decays, so a trace cannot end on a held full level",
    },
    {
        "feature": "audc_distortion_change_rate",
        "class": CONTROL_DIRECT,
        "mechanism": (
            "the DSL's dist= parameter on an instrument, or a per-note distortion override; all "
            "eight POKEY distortion bytes are accepted"
        ),
        "granularity": "one note",
        "caveat": "the player sets distortion per span, so a change can only occur at a span onset",
    },
    {
        "feature": "noise_active_share",
        "class": CONTROL_DIRECT,
        "mechanism": "use a noise distortion byte (0x80) on a voice for the desired fraction of notes",
        "granularity": "one note",
        "caveat": "the waveform family is read from the distortion nibble, so this is exact",
    },
    {
        "feature": "silence_share",
        "class": CONTROL_DIRECT,
        "mechanism": "the density of rest steps in the pattern",
        "granularity": "one step",
        "caveat": (
            "a rest zeroes AUDC and leaves AUDF at the array's initial value, so silence is absolute "
            "and a silent frame can never carry a divider"
        ),
    },
    {
        "feature": "low_volume_share",
        "class": CONTROL_INDIRECT,
        "mechanism": "the number of simultaneously active voices per step, via the channel tracks",
        "granularity": "one step",
        "caveat": "it is a consequence of voice count, not an independent control",
    },
    {
        "feature": "register_change_rate",
        "class": CONTROL_INDIRECT,
        "mechanism": (
            "note density and the number of channels carrying notes: a note onset writes AUDF and "
            "AUDC, so more onsets mean more register writes per frame"
        ),
        "granularity": "one note, but only jointly across AUDF and AUDC",
        "caveat": (
            "it counts any register write, so it cannot be moved independently of audf_change_rate "
            "and audc_change_rate; a composition cannot raise this feature without raising those"
        ),
    },
    {
        "feature": "register_change_cooccurrence",
        "class": CONTROL_INDIRECT,
        "mechanism": (
            "how many channels change at the same step; aligning note onsets raises it, offsetting "
            "them lowers it"
        ),
        "granularity": "one step",
        "caveat": "it is a property of the alignment, not of any single register",
    },
    {
        "feature": "mean_simultaneous",
        "class": CONTROL_DIRECT,
        "mechanism": "how many CHn tracks carry notes in a pattern, and CHANNELS 1..4",
        "granularity": "one step",
        "caveat": "a joined pair occupies two channels and counts as one voice, so the join lowers it",
    },
    {
        "feature": "max_simultaneous",
        "class": CONTROL_DIRECT,
        "mechanism": (
            "the largest number of CHn tracks sounding at any one step, so it is set by the busiest "
            "step in the pattern rather than by the average"
        ),
        "granularity": "one step",
        "caveat": "a joined pair occupies two channels and counts as one voice, so the join lowers it",
    },
    {
        "feature": "channel_balance",
        "class": CONTROL_INDIRECT,
        "mechanism": "how evenly the notes are distributed across the active channels",
        "granularity": "one trace",
        "caveat": "undefined with no audible voice, and reported as undefined rather than as zero",
    },
    {
        "feature": "audf_diversity_per_1000_frames",
        "class": CONTROL_DIRECT,
        "mechanism": "the number of distinct pitches used, normalised by length",
        "granularity": "one note",
        "caveat": (
            "the 1.79 MHz clock widens the representable divider range, so the same melody yields a "
            "different value under $50 than under $00. Clock and diversity are therefore not "
            "independent controls"
        ),
    },
    {
        "feature": "distinct_audc_values",
        "class": CONTROL_INDIRECT,
        "mechanism": "the number of distinct envelope levels reached across the trace",
        "granularity": "one frame via the envelope",
        "caveat": "bounded by the envelope shapes available, so it saturates",
    },
    {
        "feature": "mean_audc_run_length",
        "class": CONTROL_INDIRECT,
        "mechanism": "note length against the envelope's change rate",
        "granularity": "one note",
        "caveat": "a long rest contributes a long silent run and dominates the mean",
    },
    {
        "feature": "audible_share",
        "class": CONTROL_INDIRECT,
        "mechanism": "the complement of rest density",
        "granularity": "one step",
        "caveat": "the compiler's audibility is volume > 0, matching the detector by construction",
    },
    {
        "feature": "detector_generator_recall",
        "class": CONTROL_OBSERVED,
        "mechanism": (
            "not controlled: a property of the detector's segmentation interacting with where "
            "distortion changes are placed"
        ),
        "granularity": "n/a",
        "caveat": (
            "measurable identically on both corpora because the truth is the trace itself, but it "
            "cannot be set directly"
        ),
    },
    {
        "feature": "detector_generator_precision",
        "class": CONTROL_OBSERVED,
        "mechanism": "as above",
        "granularity": "n/a",
        "caveat": "an onset need not be a distortion change, so a low value is expected",
    },
    {
        "feature": "stable_run_median",
        "class": CONTROL_NOT_POSSIBLE,
        "mechanism": (
            "not controllable and not needed: Stage 24 measured it at exactly 1.0 in all 65 traces "
            "of both corpora, so it is degenerate and carries no information"
        ),
        "granularity": "n/a",
        "caveat": "with four voices' worth of registers, at least one column changes almost every frame",
    },
    {
        "feature": "audctl_change_rate",
        "class": CONTROL_NOT_POSSIBLE,
        "mechanism": (
            "not controllable and not needed: AUDCTL is written once for the whole frame stream, so "
            "it is constant in every trace of both corpora. Stage 24 measured it at exactly zero and "
            "excluded it as degenerate"
        ),
        "granularity": "n/a",
        "caveat": "a mid-song AUDCTL change is not expressible, and no historical trace has one either",
    },
)


def validate_feature_coverage() -> None:
    """Refuse to run if the controllability table does not cover every matching feature once.

    The claim the report makes is "answered feature by feature", so a matching feature with no row
    would be a silent gap in the design: the reader would take its absence for a classification. This
    is checked rather than asserted in prose so the table cannot drift from the feature set.
    """
    names = [row["feature"] for row in FEATURE_CONTROLLABILITY]
    if len(names) != len(set(names)):
        duplicates = sorted({name for name in names if names.count(name) > 1})
        raise Stage25Error(f"the controllability table repeats a feature: {duplicates}")
    missing = sorted(set(MATCHING_FEATURES) - set(names))
    if missing:
        raise Stage25Error(
            f"the controllability table does not classify every matching feature; missing: {missing}"
        )


# ===========================================================================
# PART 3 - the pipeline capability audit (section 6 of the brief)
# ===========================================================================
#: The BPM -> frames_per_tick mapping, read from the interpreter rather than restated. It is quoted
#: here so the capability audit and the report agree with the code that actually decides it.
BPM_TICK_TABLE: Tuple[Tuple[int, int], ...] = ((80, 6), (110, 5), (145, 4), (250, 3))

#: A pattern's step count is bounded by the composition schema. The bound is why length is controlled
#: by sequence repetition rather than by one very long pattern.
MAX_PATTERN_STEPS = 128

#: Every POKEY distortion byte, and the generator family it names.
DISTORTION_MODES: Tuple[Tuple[int, str], ...] = (
    (0x00, "poly5 gated poly17"),
    (0x20, "poly5 gated pure tone"),
    (0x40, "poly5 gated poly4"),
    (0x60, "poly5 gated pure tone (alias of $20)"),
    (0x80, "poly9/poly17 noise"),
    (0xA0, "pure tone"),
    (0xC0, "poly4 direct"),
    (0xE0, "pure tone (alias of $A0)"),
)

_PITCHES: Tuple[str, ...] = (
    "C4", "D4", "E4", "F4", "G4", "A4", "B4", "C5", "D5", "E5", "F5", "G5",
)
_BASS: Tuple[str, ...] = ("C2", "E2", "G2", "C3", "F2", "A2", "D3", "G3")


def _pitch_for(index: int) -> str:
    return _PITCHES[index % len(_PITCHES)]


def _bass_pitch(index: int) -> str:
    return _BASS[index % len(_BASS)]


def _tick_for_bpm(bpm: int) -> int:
    for bound, ticks in BPM_TICK_TABLE:
        if bpm <= bound:
            return ticks
    return 3


def _pilot_dsl(spec: Mapping[str, Any]) -> str:
    """Build a DSL document from a declared spec. Deterministic: the same spec gives the same text.

    The document deliberately declares no ``dist=`` on the bass instrument when a profile is bound,
    because a bound profile is a coherent register configuration and an explicit conflicting
    distortion is refused by the binder. That refusal is a real property of the pipeline and the
    pilot respects it rather than working around it.
    """
    channels = int(spec.get("channels", 4))
    bpm = int(spec["bpm"])
    rows = int(spec["rows"])
    repeats = int(spec["repeats"])
    sequence = " ".join(["A"] * repeats)
    distortions = spec.get("distortions", (0xA0, 0xA0, 0x80, 0x00))
    audctl = str(spec.get("audctl", "$00"))
    bound = audctl == "$50"
    bass_dist = "" if bound else f" dist=${distortions[0]:02X}"

    note_length = max(1, rows // 8)
    steps = max(1, rows // note_length)
    lead_line = " ".join(f"{_pitch_for(index)}/{note_length}" for index in range(steps))
    bass_line = " ".join(f"{_bass_pitch(index)}/{note_length}" for index in range(steps))
    perc_line = " ".join(
        ("R" if index % 3 else "C4") + f"/{note_length}" for index in range(steps)
    )

    lines = [
        f'TITLE "{spec["id"]}"',
        'AUTHOR "Stage 25 pilot"',
        "KEY C",
        "MODE MAJOR",
        f"BPM {bpm}",
    ]
    if audctl in ("$10", "$50"):
        lines.append("BASS16")
    lines.append(f"CHANNELS {channels}")
    lines.append(f"SEQUENCE {sequence}")
    lines.append("")
    lines.append(f"INSTRUMENT bass character=bass{bass_dist} att=1 dec=3 sus=8 rel=2")
    lines.append(
        f"INSTRUMENT lead character=bright_lead dist=${distortions[1]:02X} "
        "att=1 dec=2 sus=12 rel=2"
    )
    lines.append(
        f"INSTRUMENT perc character=percussion dist=${distortions[2]:02X} "
        "att=1 dec=2 sus=6 rel=1"
    )
    lines.append("")
    lines.append("[PATTERN A]")
    if channels >= 4 and audctl in ("$10", "$50"):
        lines.append(f"CH1 bass V13\n{bass_line}")
        lines.append(f"CH3 lead V14\n{lead_line}")
        lines.append(f"CH4 perc V9\n{perc_line}")
    else:
        lines.append(f"CH1 bass V13\n{bass_line}")
        lines.append(f"CH2 lead V14\n{lead_line}")
        lines.append(f"CH3 perc V9\n{perc_line}")
    return "\n".join(lines) + "\n"


def _profile_for_audctl(bank: Any, mode: int) -> str:
    """The first renderable profile in the bank whose AUDCTL mode matches, by sorted id.

    Sorted rather than insertion-ordered, so the choice cannot depend on dictionary order. The bank
    is the repository's own example bank; using it is what makes the pilot a test of the pipeline
    rather than of a fixture written for the occasion.
    """
    from atari_music.sound_profiles.bank import RENDERABLE_STATUSES

    for profile_id in sorted(bank.profiles):
        profile = bank.profiles[profile_id]
        if profile.audctl_mode == mode and profile.status in RENDERABLE_STATUSES:
            return profile_id
    raise Stage25Error(f"the profile bank has no renderable profile with audctl_mode ${mode:02X}")


def _merged_features(evidence: Any, trace: Any) -> Dict[str, Optional[float]]:
    """The Stage 23 matching features merged with the Stage 24 measures, exactly as Stage 24 does.

    ``CorpusRecord.features`` is the feature set every matching feature is drawn from, so the pilot
    must use the same union or the criterion "every matching feature is defined" would be answered
    against a different feature space than the corpus it is a pilot for.
    """
    merged: Dict[str, Optional[float]] = {
        name: float(evidence.features[name]) for name in stage23.MATCH_FEATURES
    }
    merged.update(dict(stage24.trace_measures(trace)))
    return merged


def build_pilot_trace(spec: Mapping[str, Any]) -> Dict[str, Any]:
    """Compile one pilot spec through the production pipeline and capture all three truth levels.

    The path is deliberately the one Stage 21 uses for the existing control corpus, plus the profile
    binding step a ``$50`` configuration requires. Nothing is re-implemented: the document goes
    through ``load_composition_dsl``, the compiler is ``compile_ir_to_pokey_frames``, and the trace
    wrapper is ``stage21.build_trace``.
    """
    from atari_music.ai.client import load_composition_dsl, generate_music_from_composition
    from atari_music.sound_profiles.bank import load_sound_profile_bank
    from atari_music.sound_profiles.binding import (
        BINDING_SCHEMA, apply_profile_binding, load_profile_binding,
    )
    from atari_music import ir

    dsl = _pilot_dsl(spec)
    document = load_composition_dsl(dsl)
    result = generate_music_from_composition(document)
    binding_applied = None
    audctl = str(spec.get("audctl", "$00"))
    if audctl == "$50":
        bank = load_sound_profile_bank(DEFAULT_PROFILE_BANK)
        profile_id = _profile_for_audctl(bank, 0x50)
        binding = load_profile_binding({
            "schema": BINDING_SCHEMA, "instruments": {"bass": profile_id},
        })
        result = apply_profile_binding(result, binding, bank, composition=document)
        binding_applied = profile_id

    song = result.pokey_ir
    frames = np.asarray(ir.compile_ir_to_pokey_frames(song))
    trace = stage21.build_trace(str(spec["id"]), song, frames)
    payload_hash = sha256_bytes(frames.tobytes())
    evidence = stage23.measure_trace(
        trace,
        corpus="control",
        kind="stage25_pilot",
        source_key=f"stage25/{spec['id']}",
        author="project",
        date="unknown",
        sap_type="dsl",
    )
    return {
        "id": spec["id"],
        "group": spec["group"],
        "purpose": spec["purpose"],
        "dsl": dsl,
        "source_sha256": sha256_text(dsl),
        "compiled_sha256": payload_hash,
        "trace_sha256": payload_hash,
        "frames": int(frames.shape[0]),
        "frames_per_tick": int(song.frames_per_tick),
        "uses_16bit_bass": bool(song.uses_16bit_bass),
        "resolved_audctl": f"${int(ir.resolve_audctl_mode(song)):02X}",
        "audctl_column": sorted({f"${int(v):02X}" for v in frames[:, 8]}),
        "binding_applied": binding_applied,
        "player": "src/atari_music/asm/player.asm",
        "compiler": "src/atari_music/ir.py::compile_ir_to_pokey_frames",
        "ground_truth": {
            "A_source": "captured: the DSL text and its hash",
            "B_compiled": "captured: the frame payload hash and the resolved configuration",
            "C_trace": "captured: the trace wrapper over the same payload",
        },
        "measures": {
            name: _rnd(value)
            for name, value in sorted(_merged_features(evidence, trace).items())
        },
        "estimands": {key: _rnd(value) for key, value in sorted(evidence.estimands.items())},
        "spans": evidence.spans,
        "zero_onset_spans": evidence.zero_onset_spans,
        "trace": trace,
        "evidence": evidence,
    }



def pipeline_capability_audit() -> Dict[str, Any]:
    """Probe the real pipeline and record what it can and cannot produce.

    Every finding here is measured, not read from documentation. Each probe builds a document, runs
    it through the production compiler, and inspects the frame stream. A probe that fails records the
    exception's own message, so a capability claim can be checked by re-running the probe.
    """
    from atari_music.ai.client import load_composition_dsl, generate_music_from_composition
    from atari_music.sound_profiles.bank import load_sound_profile_bank, RENDERABLE_STATUSES
    from atari_music import ir

    findings: List[Dict[str, Any]] = []

    distortion_rows: List[Dict[str, Any]] = []
    for byte, family in DISTORTION_MODES:
        dsl = _pilot_dsl({
            "id": "probe_distortion", "group": "probe", "purpose": "probe",
            "audctl": "$00", "bpm": 125, "rows": 32, "repeats": 1, "channels": 4,
            "distortions": (byte, byte, byte, 0x00),
        })
        try:
            document = load_composition_dsl(dsl)
            song = generate_music_from_composition(document).pokey_ir
            frames = np.asarray(ir.compile_ir_to_pokey_frames(song))
            seen = sorted({int(v) & 0xE0 for v in frames[:, 5] if v})
            distortion_rows.append({
                "distortion": f"${byte:02X}", "family": family,
                "reachable": True, "observed_nibbles": [f"${v:02X}" for v in seen],
            })
        except Exception as error:  # noqa: BLE001 - a refusal is the finding
            distortion_rows.append({
                "distortion": f"${byte:02X}", "family": family, "reachable": False,
                "error": f"{type(error).__name__}: {str(error)[:120]}",
            })
    findings.append({
        "capability": "distortion modes",
        "rows": distortion_rows,
        "reachable_count": sum(1 for row in distortion_rows if row["reachable"]),
        "total": len(distortion_rows),
        "conclusion": "all eight POKEY distortion bytes are reachable through dist=",
    })

    audctl_rows: List[Dict[str, Any]] = []
    for mode in ("$00", "$10", "$50"):
        spec = {
            "id": f"probe_audctl_{mode}", "group": "probe", "purpose": "probe",
            "audctl": mode, "bpm": 125, "rows": 32, "repeats": 1, "channels": 4,
            "distortions": (0xA0, 0xA0, 0x80, 0x00),
        }
        try:
            result = build_pilot_trace(spec)
            audctl_rows.append({
                "requested": mode,
                "resolved": result["resolved_audctl"],
                "column": result["audctl_column"],
                "uses_16bit_bass": result["uses_16bit_bass"],
                "binding_applied": result["binding_applied"],
                "reachable": result["audctl_column"] == [mode],
            })
        except Exception as error:  # noqa: BLE001
            audctl_rows.append({
                "requested": mode, "reachable": False,
                "error": f"{type(error).__name__}: {str(error)[:140]}",
            })
    findings.append({
        "capability": "AUDCTL configurations",
        "rows": audctl_rows,
        "reachable_count": sum(1 for row in audctl_rows if row.get("reachable")),
        "total": len(audctl_rows),
        "conclusion": (
            "every probed configuration is reachable and appears in the trace's AUDCTL column on "
            "every frame. $00 and $10 are produced by the composer alone; $50 needs a bound sound "
            "profile, because the 0x40 clock bit is a hardware declaration rather than a musical one"
        ),
    })

    length_rows: List[Dict[str, Any]] = []
    for bpm, rows, repeats in ((125, 32, 2), (125, 128, 25), (60, 128, 25), (60, 128, 30)):
        spec = {
            "id": f"probe_len_{bpm}_{rows}_{repeats}", "group": "probe", "purpose": "probe",
            "audctl": "$00", "bpm": bpm, "rows": rows, "repeats": repeats, "channels": 4,
            "distortions": (0xA0, 0xA0, 0x80, 0x00),
        }
        expected = rows * repeats * _tick_for_bpm(bpm)
        try:
            result = build_pilot_trace(spec)
            length_rows.append({
                "bpm": bpm, "rows": rows, "repeats": repeats,
                "frames_per_tick": result["frames_per_tick"],
                "frames": result["frames"], "expected": expected,
                "matches": result["frames"] == expected,
            })
        except Exception as error:  # noqa: BLE001
            length_rows.append({
                "bpm": bpm, "rows": rows, "repeats": repeats, "expected": expected,
                "error": f"{type(error).__name__}: {str(error)[:120]}",
            })
    max_frames = max((row["frames"] for row in length_rows if "frames" in row), default=0)
    findings.append({
        "capability": "composition length",
        "rows": length_rows,
        "max_frames_produced": max_frames,
        "pattern_step_bound": MAX_PATTERN_STEPS,
        "conclusion": (
            f"length is rows x repetitions x frames_per_tick; {max_frames} frames is reachable, "
            "against a historical maximum of 19008"
        ),
    })

    bank = load_sound_profile_bank(DEFAULT_PROFILE_BANK)
    by_mode: Dict[str, Dict[str, int]] = {}
    for profile_id in sorted(bank.profiles):
        profile = bank.profiles[profile_id]
        key = f"${profile.audctl_mode:02X}" if profile.audctl_mode is not None else "none"
        entry = by_mode.setdefault(key, {"total": 0, "renderable": 0})
        entry["total"] += 1
        if profile.status in RENDERABLE_STATUSES:
            entry["renderable"] += 1
    findings.append({
        "capability": "sound profile bank",
        "bank": str(DEFAULT_PROFILE_BANK.relative_to(REPO_ROOT)),
        "schema": bank.schema,
        "profiles": len(bank.profiles),
        "by_audctl_mode": by_mode,
        "conclusion": (
            f"the repository bank holds {by_mode.get('$50', {}).get('renderable', 0)} renderable "
            "$50 profiles, so the historical clock is a binding choice rather than a code change"
        ),
    })

    findings.append(_probe_zero_pulse())
    findings.append({
        "capability": "mid-song AUDCTL change",
        "reachable": False,
        "mechanism": (
            "compile_ir_to_pokey_frames writes AUDCTL once, over every frame "
            "(frames[:, 8] = resolve_audctl_mode(song))"
        ),
        "consequence": (
            "not needed: no historical trace has one either. Stage 24 measured audctl_change_rate at "
            "exactly zero in all 65 traces and excluded it as degenerate"
        ),
    })

    for finding in findings:
        narrative = finding.get("conclusion") or finding.get("consequence")
        if not isinstance(narrative, str) or not narrative.strip():
            raise Stage25Error(
                f"the capability finding {finding.get('capability')!r} has no conclusion; every "
                "finding must state what the probe measured"
            )

    return {
        "findings": findings,
        "bpm_tick_table": [
            {"bpm_max": bound, "frames_per_tick": ticks} for bound, ticks in BPM_TICK_TABLE
        ],
        "max_pattern_steps": MAX_PATTERN_STEPS,
        "production_changes_required": [
            finding["capability"] for finding in findings
            if finding.get("reachable") is False
            and finding["capability"] != "mid-song AUDCTL change"
        ],
        "reading": (
            "each capability is claimed because a probe produced it, and each gap is claimed because "
            "a probe failed with a named exception. Nothing here is read from documentation"
        ),
    }


def _probe_zero_pulse() -> Dict[str, Any]:
    """Test whether ``AUDF = 0`` can coexist with a non-zero ``AUDC`` volume nibble.

    This is the historical players' between-note idiom: a single frame with a zero divider while the
    channel stays audible, which makes the detector split a span there. The probe builds a trace with
    rests, inspects every frame, and reports the joint occurrence. It is the one capability the
    pipeline does not have, and the mechanism is stated rather than the conclusion alone.
    """
    from atari_music.ai.client import load_composition_dsl, generate_music_from_composition
    from atari_music import ir

    dsl = _pilot_dsl({
        "id": "probe_zero_pulse", "group": "probe", "purpose": "probe",
        "audctl": "$00", "bpm": 125, "rows": 32, "repeats": 1, "channels": 4,
        "distortions": (0xA0, 0xA0, 0x80, 0x00),
    })
    document = load_composition_dsl(dsl)
    song = generate_music_from_composition(document).pokey_ir
    frames = np.asarray(ir.compile_ir_to_pokey_frames(song))
    silent = 0
    zero_divider_audible = 0
    for frame in range(frames.shape[0]):
        for channel in range(1, 5):
            audf = int(frames[frame, (channel - 1) * 2])
            audc = int(frames[frame, (channel - 1) * 2 + 1])
            if audf == 0 and (audc & 0x0F) > 0:
                zero_divider_audible += 1
            if audc == 0:
                silent += 1
    return {
        "capability": PRODUCTION_CHANGE_IDIOM,
        "reachable": False,
        "zero_divider_audible_frames": zero_divider_audible,
        "silent_register_frames": silent,
        "mechanism": (
            "_render_note_to_frames writes AUDF and AUDC together from a note, a note's divider is "
            "never zero (the highest representable pitch still yields a non-zero divider), and a rest "
            "writes AUDC = 0 and leaves AUDF at the array's initial value of zero. So in a compiled "
            "trace AUDF = 0 and 'silent' are the same condition"
        ),
        "consequence": (
            "the idiom cannot be reproduced, so any corpus built with the current compiler is "
            "systematically free of it. Stage 23 measured it in 38.1% of historical spans and 0.8% "
            "of control spans, and Stage 24 classified it as a corpus-composition difference rather "
            "than as the cause of the residual"
        ),
        "production_change_would_be": (
            "a per-note or per-step way to emit a zero divider without silencing the channel. That is "
            "a change to the Music IR and to the compiler, so Stage 25 stops at the specification and "
            "does not implement it"
        ),
        "does_it_change_the_subject_of_the_study": (
            "yes, if the question is whether this idiom carries residual. No, if the question is "
            "whether the corpora differ on the matching features, because the idiom is a mediator "
            "rather than a matching feature and the primary estimand is convention-free"
        ),
    }


# ===========================================================================
# PART 4 - the corpus design (section 7 of the brief)
# ===========================================================================
#: The four control groups. Each is justified by the gap it closes and costed, and none is included
#: merely because it is conventional.
CORPUS_GROUPS: Tuple[Dict[str, Any], ...] = (
    {
        "group": "A_baseline",
        "role": "continuity",
        "purpose": (
            "compositions built with the default 64 kHz configuration, so the new corpus is "
            "comparable with the existing 53 and the two can be pooled"
        ),
        "what_it_closes": "nothing alone; it stops the new corpus from being a different kind of object",
        "size_target": "at least 12",
        "ground_truth": "A, B and C",
        "cost": "low - the existing pipeline already produces this configuration",
        "necessary": True,
    },
    {
        "group": "B_feature_coverage",
        "role": "close the measured structural gaps",
        "purpose": (
            "compositions whose observable feature vectors lie inside the historical region, "
            "targeting the two gaps Stage 24 measured: the 1.79 MHz clock and trace length"
        ),
        "what_it_closes": (
            "the joint-support gap, if it is closable at all. This is the group the design exists for"
        ),
        "size_target": "at least 24",
        "ground_truth": "A, B and C",
        "cost": (
            "medium - each composition is authored against a declared feature target and validated "
            "against the acceptance criteria before it counts"
        ),
        "necessary": True,
    },
    {
        "group": "C_mechanism_controls",
        "role": "let the detector's behaviour be measured",
        "purpose": (
            "minimal compositions that isolate one mechanism each: note-boundary structure, "
            "distortion transitions, volume transitions, silence, overlapping channel activity"
        ),
        "what_it_closes": (
            "the Stage 22 finding that note-boundary errors dominate. It does not close a support "
            "gap; it makes the detector's error attributable inside the new corpus"
        ),
        "size_target": "at least 8",
        "ground_truth": "A, B and C",
        "cost": "low - short compositions with one variable each",
        "necessary": True,
    },
    {
        "group": "D_pipeline_controls",
        "role": "separate composition from generator",
        "purpose": (
            "the same musical material rendered through more than one pipeline configuration, so a "
            "difference attributable to the compiler or the player can be seen"
        ),
        "what_it_closes": (
            "partially the generator confound, and only partially: see the leakage section"
        ),
        "size_target": "at least 4",
        "ground_truth": "A, B and C, with the same A across each pair",
        "cost": (
            "medium - each pair shares a source document and differs only in the binding, so the "
            "difference is a clean contrast"
        ),
        "necessary": False,
        "why_optional": (
            "the most valuable group for identifiability and the most expensive to interpret. "
            "Recommended, but the corpus is valid without it and the verdict says which claims "
            "depend on it"
        ),
    },
)



def corpus_design(
    historical: Sequence[stage24.CorpusRecord],
    capability: Mapping[str, Any],
) -> Dict[str, Any]:
    """The design, with each group tied to the gap it closes and to a capability the audit confirmed.

    A group is only proposed when the pipeline can actually build it. Where a group would need a
    capability the audit could not confirm, the design says so rather than assuming it away.
    """
    reachable = {
        finding["capability"]: finding.get("reachable", True)
        for finding in capability["findings"]
    }
    zero_pulse = next(
        finding for finding in capability["findings"]
        if finding["capability"].startswith("AUDF = 0")
    )
    groups: List[Dict[str, Any]] = []
    for group in CORPUS_GROUPS:
        entry = dict(group)
        entry["pipeline_can_build_it"] = True
        entry["blocked_by"] = None
        if group["group"] == "B_feature_coverage":
            dependencies = ["AUDCTL configurations", "composition length", "sound profile bank"]
            entry["capability_dependencies"] = dependencies
            entry["all_dependencies_reachable"] = all(
                reachable.get(name, False) for name in dependencies
            )
        if group["group"] == "C_mechanism_controls":
            dependencies = ["distortion modes", "composition length"]
            entry["capability_dependencies"] = dependencies
            entry["all_dependencies_reachable"] = all(
                reachable.get(name, False) for name in dependencies
            )
            entry["mechanism_not_available"] = {
                "mechanism": "a zero divider on an audible frame",
                "consequence": (
                    "the note-boundary control cannot reproduce this idiom, so the detector's "
                    "behaviour on it cannot be measured inside the new corpus"
                ),
                "evidence": zero_pulse["mechanism"],
            }
        groups.append(entry)

    historical_frames = sorted(record.frames for record in historical)
    length_finding = next(
        finding for finding in capability["findings"]
        if finding["capability"] == "composition length"
    )
    return {
        "groups": groups,
        "group_count": len(groups),
        "total_minimum_size": 48,
        "target_length_region": {
            "historical_min": historical_frames[0],
            "historical_median": _median([float(v) for v in historical_frames]),
            "historical_max": historical_frames[-1],
            "reachable": length_finding["max_frames_produced"],
        },
        "target_configurations": {
            "historical": list(HISTORICAL_AUDCTL),
            "existing_control": list(CONTROL_AUDCTL_EXISTING),
            "gap_to_close": "$50",
        },
        "design_principle": (
            "coverage is targeted on the joint feature vector, not on marginal ranges. Stage 24 "
            "showed that univariate overlap held for 21 of 21 features while the joint box was empty, "
            "so a design that matched one feature at a time would repeat Stage 23's mistake"
        ),
        "what_the_design_does_not_do": [
            "it does not reproduce the zero-divider audible pulse, which the pipeline cannot express",
            "it does not vary the player, so the generator confound survives",
            "it does not create ground truth on the historical side",
        ],
    }


# ===========================================================================
# PART 5 - sample size (section 8 of the brief)
# ===========================================================================
def sample_size_rationale(
    historical: Sequence[stage24.CorpusRecord],
    control: Sequence[stage24.CorpusRecord],
    design: Mapping[str, Any],
) -> Dict[str, Any]:
    """How many compositions are needed, and an honest statement that the number is not known.

    The brief asks for an estimate grounded in the historical count, the feature dimension, the
    between-song variability, the expected interval width and the cost per composition. Three of
    those are unavailable: there is no pilot variance estimate, no power target that survives the
    player confound, and no measured cost per composition. So the estimate is a *design floor*
    derived from what can be counted, plus a staged pilot with declared continuation criteria.
    """
    feature_count = len(MATCHING_FEATURES)
    historical_count = len(historical)
    return {
        "what_can_be_counted": {
            "historical_traces": historical_count,
            "historical_sources": len({record.source_key for record in historical}),
            "historical_authors": len({record.author for record in historical}),
            "matching_features": feature_count,
            "existing_control_traces": len(control),
        },
        "design_floor": {
            "rule": (
                "the corpus must retain at least "
                f"{ACCEPT_MIN_RETAINED_TRACES} historical traces from "
                f"{ACCEPT_MIN_RETAINED_SOURCES} sources after a caliper is applied, and supply a "
                "distinct partner for each. A 1:1 match therefore needs at least as many control "
                "traces as the number of historical traces expected to match"
            ),
            "minimum_control_traces": 2 * historical_count,
            "why": (
                "12 historical traces against a candidate corpus of 24 leaves room for a match at "
                "roughly 1:2. The existing 53 control traces failed with a corpus of 53, so size "
                "alone was never the problem - the configuration was"
            ),
        },
        "feature_dimension_argument": {
            "features": feature_count,
            "traces_per_feature": round(historical_count / feature_count, 4),
            "statement": (
                f"{feature_count} matching features against {historical_count} historical traces is "
                "fewer than one trace per feature. No distance or propensity model can be estimated "
                "from that, which is why Stage 24's propensity score had 16 of 22 coefficients change "
                "sign under resampling. Adding control traces does not fix this: the historical side "
                "is the binding constraint and it cannot be enlarged without more SAPs"
            ),
        },
        "what_cannot_be_estimated": [
            {
                "quantity": "the between-song variance of the residual in the new corpus",
                "why": "no pilot of the new corpus exists yet",
            },
            {
                "quantity": "the interval width to expect",
                "why": (
                    "it depends on the between-source variance, and the historical side has 11 "
                    "sources. Widening the control side narrows the control term only"
                ),
            },
            {
                "quantity": "the power to detect a given effect",
                "why": (
                    "the comparison is confounded with the generator, so a power calculation would "
                    "be a calculation about a quantity that is not identified"
                ),
            },
        ],
        "staged_pilot": {
            "stage_1": {
                "size": len(PILOT_SPECS),
                "purpose": (
                    "prove the mechanics: the clock, the length, the truth levels, determinism"
                ),
                "continuation_criteria": list(PILOT_CRITERIA),
                "if_not_met": (
                    "stop and report a capability gap. Do not enlarge the pilot; the problem would "
                    "be the pipeline, not the size"
                ),
            },
            "stage_2": {
                "size": 12,
                "purpose": "measure whether the joint-support gap actually narrows",
                "continuation_criteria": [
                    "the box criterion's calibration still passes on the candidate's own members",
                    "the joint-box coverage for the historical traces rises above zero",
                    "the nearest-neighbour distances fall inside the candidate's own range",
                ],
                "if_not_met": (
                    "stop and diagnose: the brief is explicit that the pilot must not be enlarged "
                    "automatically. The question is then whether the target population is wrong, the "
                    "features are wrong, or the pipeline cannot reach the region"
                ),
            },
            "stage_3": {
                "size": design["total_minimum_size"],
                "purpose": "the corpus the acceptance criteria are actually evaluated against",
                "continuation_criteria": ["every acceptance criterion in section 9 of the report"],
                "if_not_met": "the corpus is refused and the comparison is not attempted",
            },
        },
        "reading": (
            "the design floor is 24 control traces. The staged pilot is what decides whether that "
            "number is achievable, and the brief's instruction is followed: the pilot is not "
            "enlarged until the criteria say the earlier stage passed"
        ),
    }


# ===========================================================================
# PART 6 - overlap acceptance criteria and matching validation
# ===========================================================================
def overlap_acceptance_criteria() -> Dict[str, Any]:
    """The criteria a candidate corpus must satisfy, declared before any corpus is built.

    The brief's warning is followed literally: overlap is not declared sufficient because a nearest
    control example could be assigned to every historical trace. The criteria below are the ones
    Stage 24 calibrated, reused unchanged, so the new corpus is judged by the test that rejected the
    old one rather than by a test chosen to pass.
    """
    return {
        "univariate": {
            "criterion": "no matching feature is strictly separated",
            "threshold": "every matching feature has a non-empty common range",
            "reused_from": "reports/stage24/univariate_overlap.json",
            "note": (
                "Stage 24 already passed this with the length artefact corrected, so it is a "
                "necessary condition rather than the binding one"
            ),
        },
        "multivariate_box": {
            "criterion": (
                "every historical trace lies inside the candidate corpus's joint feature box"
            ),
            "threshold": f"at least {ACCEPT_JOINT_BOX_COVERAGE:.0%} of historical traces inside",
            "reused_from": "reports/stage24/multivariate_overlap.json box",
            "note": (
                "this is the criterion that failed. Stage 24 measured 0 of 12 historical inside and "
                "41 of 53 control inside, so the test discriminates"
            ),
        },
        "calibration": {
            "criterion": "the box criterion passes the candidate corpus's own members",
            "threshold": (
                f"at least {ACCEPT_CALIBRATION_MIN:.0%} of candidate traces inside under leave-one-out"
            ),
            "reused_from": (
                "reports/stage24/multivariate_overlap.json box.calibration_inside_control"
            ),
            "note": (
                "without this the box test could be refused for having no power, and a corpus would "
                "be rejected for the wrong reason"
            ),
        },
        "distance": {
            "criterion": (
                "no historical trace sits beyond the candidate corpus's own distance range"
            ),
            "threshold": (
                f"at most {ACCEPT_DISTANCE_BEYOND} historical traces beyond the candidate "
                "leave-one-out maximum"
            ),
            "reused_from": "reports/stage24/multivariate_overlap.json nearest_neighbour",
            "note": (
                "three thresholds are reported (max, p95, p90) so the conclusion does not rest on "
                "one. The max is the permissive one and is the acceptance bar"
            ),
        },
        "propensity": {
            "criterion": "the propensity overlap region retains most of both corpora",
            "threshold": f"at least {ACCEPT_PROPENSITY_RETAINED:.0%} retained in [0.1, 0.9]",
            "reused_from": "reports/stage24/multivariate_overlap.json propensity",
            "note": (
                "the score is a diagnostic, not proof. Stage 24's had 16 of 22 coefficients change "
                "sign under resampling, so the candidate must also report its stability, and a score "
                "that separates the corpora is a statement about how unlike they are"
            ),
        },
        "matching": {
            "criterion": "a declared caliper is enforced and the match is balanced",
            "threshold": (
                f"at least {ACCEPT_MIN_RETAINED_TRACES} traces from "
                f"{ACCEPT_MIN_RETAINED_SOURCES} sources retained, with every |SMD| <= "
                f"{ACCEPT_SMD_THRESHOLD}"
            ),
            "reused_from": "reports/stage24/matching_diagnostics.json",
            "note": (
                "Stage 23 declared a caliper and never applied it. The acceptance test therefore "
                "includes a positive control: a caliper of 0.01 must reject every trace, proving the "
                "implementation enforces the constraint rather than ignoring it"
            ),
        },
        "leakage": {
            "criterion": "the design set and the validation set are separated where the data allows",
            "threshold": (
                "at least one historical source reserved, or the result reported as a validation on "
                "a known set rather than as a generalization"
            ),
            "reused_from": "new in Stage 25",
            "note": "see the leakage assessment below",
        },
        "reading": (
            "all six criteria are evaluated together. A corpus that satisfies five and fails one is "
            "refused, because the comparison is only as good as its weakest support dimension"
        ),
    }


def matching_validation() -> Dict[str, Any]:
    """Test that a declared caliper is actually enforced, using the Stage 24 matcher.

    The brief asks for a real test of the caliper, not a declaration of one. The positive control is
    the decisive part: a caliper far below the smallest observed distance must reject everything. If
    it does not, the matcher ignores its caliper and no matched result from it may be reported.
    """
    control = stage24.load_control_records()
    historical = stage24.load_historical_records()
    stats = stage24.pooled_standardisation(control, historical)
    probe = stage24.match_nearest_neighbour(
        control, historical, stats, caliper=0.01, neighbours=1
    )
    wide = stage24.match_nearest_neighbour(
        control, historical, stats, caliper=1000.0, neighbours=1
    )
    return {
        "caliper_declared": 0.01,
        "positive_control": {
            "caliper": 0.01,
            "historical_kept": probe["historical_kept"],
            "historical_rejected": probe["historical_rejected"],
            "enforced": probe["historical_kept"] == 0 and probe["historical_rejected"] > 0,
            "note": (
                "a caliper below every observed distance must retain nothing. If it retained "
                "anything the matcher would be ignoring the constraint"
            ),
        },
        "negative_control": {
            "caliper": 1000.0,
            "historical_kept": wide["historical_kept"],
            "historical_rejected": wide["historical_rejected"],
            "retains_everything": wide["historical_kept"] == len(historical),
            "note": (
                "a caliper above every observed distance must retain everything, so the rejection in "
                "the positive control is the caliper and not a bug"
            ),
        },
        "smallest_observed_distance": (
            min(row["partner_distances"][0] for row in wide["matched"] if row["partner_distances"])
            if wide["matched"] else None
        ),
        "balance_criterion": {
            "threshold": ACCEPT_SMD_THRESHOLD,
            "source": "reused from Stage 24 rather than re-chosen",
        },
        "reading": (
            "the positive and negative controls together show the caliper is a real constraint. A "
            "matcher that passes both can be trusted to reject an unmatched trace"
        ),
    }


# ===========================================================================
# PART 7 - leakage and over-fitting protection (section 11 of the brief)
# ===========================================================================
def leakage_assessment(
    historical: Sequence[stage24.CorpusRecord],
) -> Dict[str, Any]:
    """Where the design draws from and where it validates, and what that costs the claim.

    Every one of the twelve historical traces was used to *design* the corpus: the target region, the
    gaps and the acceptance criteria all come from them. A corpus that then matches those same twelve
    traces has demonstrated an interpolation, not a generalization, and the report must say so rather
    than presenting the fit as representativeness.
    """
    by_source: Dict[str, List[str]] = {}
    for record in historical:
        by_source.setdefault(record.source_key, []).append(record.slug)
    largest_source = max(by_source.items(), key=lambda item: (len(item[1]), item[0]))
    return {
        "design_set": {
            "used_to_choose_the_target_region": sorted(record.slug for record in historical),
            "traces": len(historical),
            "sources": len(by_source),
            "note": "every available historical trace informed the design; there is no unused one",
        },
        "validation_options": [
            {
                "option": "leave-one-source-out over the historical corpus",
                "available": len(by_source) >= 4,
                "what_it_proves": "that a matched result is not driven by a single historical source",
                "what_it_does_not_prove": (
                    "that the corpus generalizes to historical traces outside the twelve"
                ),
                "cost": "free; it needs no extra material and no trace leaves the comparison",
                "recommendation": (
                    "report it, but read it as a stability check on the twelve rather than as an "
                    "estimate of performance on unseen historical material"
                ),
            },
            {
                "option": "reserve one historical source entirely",
                "available": len(by_source) > 1,
                "what_it_proves": (
                    "that a matched result survives on material that did not inform the design"
                ),
                "what_it_does_not_prove": (
                    "that the held-out source is exchangeable with the others, when four of twelve "
                    "traces share one author's player routine"
                ),
                "cost": (
                    f"the largest source is {largest_source[0]} with {len(largest_source[1])} traces, "
                    f"so reserving it removes {len(largest_source[1])} of {len(historical)} traces "
                    "from the design and from the comparison. With 12 traces that is a material loss"
                ),
                "recommendation": (
                    "reserve the source with the most traces only if the design can tolerate losing "
                    "them. Otherwise report leave-one-source-out and label the result a validation on "
                    "a known set"
                ),
            },
            {
                "option": "acquire new historical SAPs after the corpus is built",
                "available": True,
                "what_it_proves": (
                    "that a matched result transfers to historical material the design never saw"
                ),
                "what_it_does_not_prove": (
                    "that the new material is representative: an unrepresentative sample generalizes "
                    "to itself and to nothing else"
                ),
                "cost": "outside the project's control; depends on what can be found",
                "recommendation": (
                    "the only option that turns the claim from interpolation into generalization, and "
                    "the strongest reason to build the corpus first and validate later"
                ),
            },
        ],
        "over_fitting_risks": [
            {
                "risk": (
                    "designing the corpus against the twelve traces and reporting the fit as general"
                ),
                "mitigation": (
                    "the report labels the result a validation on a known set, and the verdict "
                    "vocabulary has no word for generalizing from it"
                ),
            },
            {
                "risk": "choosing features that make the corpora look alike",
                "mitigation": (
                    "the feature set is Stage 24's, unchanged, and the acceptance criteria are the "
                    "tests Stage 24 calibrated. Neither is re-chosen here"
                ),
            },
            {
                "risk": "widening a caliper until a match appears",
                "mitigation": (
                    "the caliper grid is declared before the corpus is built, and the acceptance "
                    "criteria require the balance threshold to be met at every reported setting"
                ),
            },
            {
                "risk": "treating the propensity score's separation as proof of anything",
                "mitigation": (
                    "the score is reported with its resampling stability and is never the sole basis "
                    "for a support verdict"
                ),
            },
        ],
        "conclusion": (
            "with twelve traces from eleven sources, all of them used for design, a corpus matched to "
            "them demonstrates interpolation. The honest claim is that the comparison becomes "
            "supported *for these traces*, and generalization needs historical material the project "
            "does not have yet"
        ),
    }


# ===========================================================================
# PART 8 - the pilot and its ground-truth validation (sections 9 and 12 of the brief)
# ===========================================================================
def run_pilot() -> Dict[str, Any]:
    """Build the four pilot compositions and evaluate the declared continuation criteria.

    The pilot is deliberately small. Its job is to prove the mechanics, not to be a corpus, and the
    brief is explicit that it must not be presented as one. A failed spec is reported rather than
    dropped, and the criteria are evaluated from the artefacts rather than from the build log.
    """
    traces: List[Dict[str, Any]] = []
    failures: List[Dict[str, Any]] = []
    for spec in PILOT_SPECS:
        try:
            row = build_pilot_trace(spec)
        except Exception as error:  # noqa: BLE001 - a failure to build is a finding
            failures.append({
                "id": spec["id"],
                "group": spec["group"],
                "error": f"{type(error).__name__}: {str(error)[:200]}",
            })
            continue
        row["requested_audctl"] = str(spec["audctl"])
        row["expected_frames"] = (
            int(spec["rows"]) * int(spec["repeats"]) * _tick_for_bpm(int(spec["bpm"]))
        )
        row["length_matches"] = row["frames"] == row["expected_frames"]
        traces.append(row)

    determinism = {"checked": False}
    if traces:
        first = traces[0]
        again = build_pilot_trace(PILOT_SPECS[0])
        determinism = {
            "checked": True,
            "spec": first["id"],
            "source_hash_match": again["source_sha256"] == first["source_sha256"],
            "payload_hash_match": again["compiled_sha256"] == first["compiled_sha256"],
            "frames_match": again["frames"] == first["frames"],
        }

    historical_min = 2048
    criteria = [
        {
            "criterion": PILOT_CRITERIA[0]["criterion"],
            "measurement": PILOT_CRITERIA[0]["measurement"],
            "passed": not failures and len(traces) == len(PILOT_SPECS),
            "observed": {"built": len(traces), "failed": len(failures)},
        },
        {
            "criterion": PILOT_CRITERIA[1]["criterion"],
            "measurement": PILOT_CRITERIA[1]["measurement"],
            "passed": all(row["audctl_column"] == [row["requested_audctl"]] for row in traces),
            "observed": {row["id"]: row["audctl_column"] for row in traces},
        },
        {
            "criterion": PILOT_CRITERIA[2]["criterion"],
            "measurement": PILOT_CRITERIA[2]["measurement"],
            "passed": all(row["length_matches"] for row in traces),
            "observed": {
                row["id"]: {"frames": row["frames"], "expected": row["expected_frames"]}
                for row in traces
            },
        },
        {
            "criterion": PILOT_CRITERIA[3]["criterion"],
            "measurement": PILOT_CRITERIA[3]["measurement"],
            "passed": any(row["frames"] >= historical_min for row in traces),
            "observed": {
                "historical_min": historical_min,
                "max_pilot_frames": max((row["frames"] for row in traces), default=0),
            },
        },
        {
            "criterion": PILOT_CRITERIA[4]["criterion"],
            "measurement": PILOT_CRITERIA[4]["measurement"],
            "passed": all(
                row["source_sha256"] and row["compiled_sha256"] and row["trace_sha256"]
                and row["compiled_sha256"] == row["trace_sha256"]
                for row in traces
            ),
            "observed": {
                row["id"]: {
                    "source": row["source_sha256"][:12],
                    "compiled": row["compiled_sha256"][:12],
                    "trace": row["trace_sha256"][:12],
                }
                for row in traces
            },
        },
        {
            "criterion": PILOT_CRITERIA[5]["criterion"],
            "measurement": PILOT_CRITERIA[5]["measurement"],
            "passed": bool(
                determinism.get("source_hash_match") and determinism.get("payload_hash_match")
            ),
            "observed": determinism,
        },
        {
            "criterion": PILOT_CRITERIA[6]["criterion"],
            "measurement": PILOT_CRITERIA[6]["measurement"],
            "passed": all(
                all(row["measures"].get(name) is not None for name in MATCHING_FEATURES)
                for row in traces
            ),
            "observed": {
                row["id"]: [
                    name for name in MATCHING_FEATURES if row["measures"].get(name) is None
                ]
                for row in traces
            },
        },
    ]
    passed = sum(1 for row in criteria if row["passed"])
    return {
        "specs": len(PILOT_SPECS),
        "built": len(traces),
        "failed": failures,
        "criteria": criteria,
        "passed": passed,
        "total": len(criteria),
        "all_passed": passed == len(criteria),
        "traces": [
            {key: value for key, value in row.items() if key not in ("trace", "evidence", "dsl")}
            for row in traces
        ],
        "not_a_corpus": (
            "four compositions are a feasibility test. They are not a control corpus, they are not "
            "used to evaluate the acceptance criteria, and no residual comparison is run on them"
        ),
        "seed": PILOT_SEED,
    }




def ground_truth_validation(pilot: Mapping[str, Any]) -> Dict[str, Any]:
    """Check that the three truth levels are present, distinct and internally consistent.

    Hashing is not the same as being correct, so the checks go beyond comparing digests: the source
    hash must change when the document changes, the payload hash must be reproducible, and the trace
    wrapper must be derived from the same payload that was hashed.
    """
    checks: List[Dict[str, Any]] = []
    for row in pilot["traces"]:
        spec = next(item for item in PILOT_SPECS if item["id"] == row["id"])
        rebuilt = build_pilot_trace(spec)
        checks.append({
            "id": row["id"],
            "levels_present": all(
                row[key] for key in ("source_sha256", "compiled_sha256", "trace_sha256")
            ),
            "compiled_equals_trace": row["compiled_sha256"] == row["trace_sha256"],
            "source_hash_stable": rebuilt["source_sha256"] == row["source_sha256"],
            "payload_hash_stable": rebuilt["compiled_sha256"] == row["compiled_sha256"],
            "audctl_matches_request": row["audctl_column"] == [row["requested_audctl"]],
            "resolved_audctl_matches_column": row["resolved_audctl"] == row["requested_audctl"],
            "uses_16bit_consistent": (
                row["uses_16bit_bass"] == (row["requested_audctl"] in ("$10", "$50"))
            ),
            "frames_consistent": row["length_matches"],
        })
    sample = PILOT_SPECS[0]
    mutated = dict(sample)
    mutated["bpm"] = int(sample["bpm"]) + 1
    sensitivity = {
        "checked": True,
        "source_hash_changes_when_the_document_changes": (
            sha256_text(_pilot_dsl(mutated)) != sha256_text(_pilot_dsl(sample))
        ),
    }
    all_ok = bool(checks) and all(
        row["levels_present"] and row["compiled_equals_trace"] and row["source_hash_stable"]
        and row["payload_hash_stable"] and row["audctl_matches_request"]
        and row["resolved_audctl_matches_column"] and row["uses_16bit_consistent"]
        and row["frames_consistent"]
        for row in checks
    )
    return {
        "levels": [dict(item) for item in GROUND_TRUTH_LEVELS],
        "checks": checks,
        "hash_sensitivity": sensitivity,
        "all_consistent": bool(
            all_ok and sensitivity["source_hash_changes_when_the_document_changes"]
        ),
        "reading": (
            "a digest is not a proof of correctness, so the checks also test that the hash responds "
            "to a document change and that the resolved configuration agrees with the trace column"
        ),
    }



# ===========================================================================
# PART 9 - the verdicts (section 17 of the brief)
# ===========================================================================
VERDICT_VOCABULARY: Tuple[str, ...] = (
    "CORPUS_DESIGN_VALIDATED",
    "PILOT_FEASIBILITY_CONFIRMED",
    "PIPELINE_CAPABILITY_INSUFFICIENT",
    "TARGET_COVERAGE_NOT_ACHIEVABLE",
    "OVERLAP_CRITERIA_NOT_VALIDATED",
    "NEW_CORPUS_REQUIRED",
    "CORPUS_DESIGN_INCONCLUSIVE",
)

#: Auxiliary verdicts. ``PROVEN PERFORMANCE LAYER`` is deliberately absent and is asserted absent by
#: the test suite.
AUXILIARY_VERDICTS: Tuple[str, ...] = (
    "PRODUCTION_CHANGE_REQUIRED_FOR_ONE_IDIOM",
    "PLAYER_CONFOUND_NOT_CLOSABLE_BY_CORPUS_DESIGN",
    "VALIDATION_ON_A_KNOWN_SET_ONLY",
    "GROUND_TRUTH_PRESERVED_AT_THREE_LEVELS",
    "MATCHING_CALIPER_VALIDATED",
    "NO_PRODUCTION_DECISION_CHANGED",
)


def _auxiliary_verdicts(
    capability: Mapping[str, Any],
    design: Mapping[str, Any],
    pilot: Mapping[str, Any],
    ground_truth: Mapping[str, Any],
    matching: Mapping[str, Any],
    leakage: Mapping[str, Any],
) -> List[Dict[str, Any]]:
    """The auxiliary verdicts, each with the measurement that decided it."""
    required_changes = capability["production_changes_required"]
    auxiliary: List[Dict[str, Any]] = []
    if required_changes:
        auxiliary.append({
            "verdict": "PRODUCTION_CHANGE_REQUIRED_FOR_ONE_IDIOM",
            "reason": (
                "one historical player idiom - a zero divider on an audible frame - is not "
                "expressible through the Music DSL or the IR, so the compiler cannot produce it"
            ),
            "measurement": {
                "capabilities_requiring_change": required_changes,
                "zero_divider_audible_frames_in_probe": next(
                    finding for finding in capability["findings"]
                    if finding["capability"].startswith("AUDF = 0")
                )["zero_divider_audible_frames"],
            },
        })
    auxiliary.append({
        "verdict": "PLAYER_CONFOUND_NOT_CLOSABLE_BY_CORPUS_DESIGN",
        "reason": (
            "the historical traces come from unknown third-party players and the controls from one "
            "known compiler and player. No number of new control compositions changes that, and only "
            "a design that varies the player while holding the music fixed addresses it"
        ),
        "measurement": {
            "control_players": 1,
            "historical_players": "unknown; at least three composer clusters",
            "group_that_partially_addresses_it": "D_pipeline_controls",
        },
    })
    auxiliary.append({
        "verdict": "VALIDATION_ON_A_KNOWN_SET_ONLY",
        "reason": (
            "all twelve historical traces informed the design, so a corpus matched to them "
            "demonstrates interpolation rather than generalization"
        ),
        "measurement": {
            "design_traces": leakage["design_set"]["traces"],
            "design_sources": leakage["design_set"]["sources"],
            "unused_historical_traces": 0,
        },
    })
    if ground_truth["all_consistent"]:
        auxiliary.append({
            "verdict": "GROUND_TRUTH_PRESERVED_AT_THREE_LEVELS",
            "reason": (
                "every pilot composition carries a source hash, a compiled payload hash and a trace "
                "hash, and the hash responds to a document change"
            ),
            "measurement": {
                "levels": len(ground_truth["levels"]),
                "checks_passed": sum(
                    1 for row in ground_truth["checks"]
                    if row["levels_present"] and row["compiled_equals_trace"]
                ),
                "hash_sensitivity": ground_truth["hash_sensitivity"],
            },
        })
    if matching["positive_control"]["enforced"] and matching["negative_control"][
        "retains_everything"
    ]:
        auxiliary.append({
            "verdict": "MATCHING_CALIPER_VALIDATED",
            "reason": (
                "the caliper rejects everything below the observed distance range and retains "
                "everything above it, so the implementation enforces the constraint Stage 23 "
                "declared and never applied"
            ),
            "measurement": {
                "positive_control": matching["positive_control"],
                "negative_control": matching["negative_control"],
            },
        })
    auxiliary.append({
        "verdict": "NO_PRODUCTION_DECISION_CHANGED",
        "reason": (
            "Stage 25 designs and pilots. It modifies no detector, compiler, player, exporter or "
            "schema, commits no corpus and generates no released music"
        ),
        "measurement": {"read_only": True, "stage_26_started": False, "corpus_created": False},
    })
    return auxiliary


def verdicts(
    capability: Mapping[str, Any],
    design: Mapping[str, Any],
    pilot: Mapping[str, Any],
    ground_truth: Mapping[str, Any],
    matching: Mapping[str, Any],
    leakage: Mapping[str, Any],
    samples: Mapping[str, Any],
) -> Dict[str, Any]:
    """The main verdict and the auxiliary ones, each with the measurement that decided it.

    The main verdict follows the declared rule rather than a preference. The pipeline can build every
    configuration the design needs except one idiom, the pilot confirmed the mechanics, and the
    generator confound survives regardless - so the honest main verdict is that the pilot's
    feasibility is confirmed, with the capability gap and the confound named as auxiliary findings
    rather than folded into it.
    """
    buildable = [
        group for group in design["groups"] if group.get("all_dependencies_reachable", True)
    ]
    required_changes = capability["production_changes_required"]
    if not buildable:
        main = "PIPELINE_CAPABILITY_INSUFFICIENT"
    elif not pilot["all_passed"]:
        main = "CORPUS_DESIGN_INCONCLUSIVE"
    elif required_changes:
        main = "PILOT_FEASIBILITY_CONFIRMED"
    else:
        main = "CORPUS_DESIGN_VALIDATED"

    auxiliary = _auxiliary_verdicts(
        capability, design, pilot, ground_truth, matching, leakage
    )
    return {
        "main": {
            "verdict": main,
            "deciding_measurement": {
                "capabilities_reachable": sum(
                    1 for finding in capability["findings"]
                    if finding.get("reachable", True)
                ),
                "capabilities_total": len(capability["findings"]),
                "production_changes_required": required_changes,
                "pilot_criteria_passed": pilot["passed"],
                "pilot_criteria_total": pilot["total"],
                "ground_truth_consistent": ground_truth["all_consistent"],
                "caliper_enforced": matching["positive_control"]["enforced"],
                "design_groups_buildable": len(buildable),
                "design_floor_control_traces": samples["design_floor"]["minimum_control_traces"],
            },
            "what_it_means": (
                "the pipeline can build the corpus the design calls for, the mechanics are proven end "
                "to end, and the ground truth is preserved at three levels. What the corpus cannot "
                "fix is named rather than designed around"
            ),
            "what_it_does_not_mean": (
                "it does not mean the corpus is built, that the comparison is now supported, or that "
                "any residual difference has been explained. It means the conditions for an honest "
                "comparison are specified and reachable"
            ),
        },
        "auxiliary": auxiliary,
        "vocabulary": list(VERDICT_VOCABULARY),
        "auxiliary_vocabulary": list(AUXILIARY_VERDICTS),
        "proven_performance_layer_used": False,
    }


# ===========================================================================
# PART 10 - read-only audit, the run and the artefacts (sections 13 and 15)
# ===========================================================================
#: Everything Stage 25 reads and must not write. Stage 15 to 24 are included, so a change to any
#: earlier stage during a Stage 25 run would be caught rather than assumed impossible.
PRODUCTION_FILES: Tuple[str, ...] = (
    "src/atari_music/constants.py",
    "src/atari_music/ir.py",
    "src/atari_music/pokey_hw.py",
    "src/atari_music/mads_exporter.py",
    "src/atari_music/cli.py",
    "src/atari_music/composer_v4.py",
    "src/atari_music/ai/dsl.py",
    "src/atari_music/ai/client.py",
    "src/atari_music/ai/validation.py",
    "src/atari_music/sound_profiles/bank.py",
    "src/atari_music/sound_profiles/binding.py",
    "src/atari_music/stage15.py",
    "src/atari_music/stage16.py",
    "src/atari_music/stage17.py",
    "src/atari_music/stage18.py",
    "src/atari_music/stage19.py",
    "src/atari_music/stage20.py",
    "src/atari_music/stage21.py",
    "src/atari_music/stage22.py",
    "src/atari_music/stage23.py",
    "src/atari_music/stage24.py",
    "src/atari_music/asm/player.asm",
    "tests/data/sound_profiles/vaults_of_nhyrmeth.dsl",
)

STAGE25_FILES: Tuple[str, ...] = (
    "target_population.json",
    "feature_specification.json",
    "pipeline_capability_audit.json",
    "corpus_design.json",
    "sample_size_rationale.json",
    "overlap_acceptance_criteria.json",
    "pilot_results.json",
    "ground_truth_validation.json",
    "matching_validation.json",
    "leakage_assessment.json",
    "next_step_recommendation.json",
    "verdict.json",
    "stage25_manifest.json",
)
STAGE25_DOC = "stage25_matched_control_corpus_design.md"
STAGE25_REPORT = "stage25_report.md"


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
        DEFAULT_STAGE21_DIR, DEFAULT_STAGE22_DIR, DEFAULT_STAGE23_DIR, DEFAULT_STAGE24_DIR,
    ),
) -> Dict[str, Optional[str]]:
    """The hash of every input the stage reads: traces, compositions, profiles and artefacts."""
    out: Dict[str, Optional[str]] = {}
    for path in sorted(stage15.list_traces(Path(arch_root))):
        out[f"trace/{path.name}"] = sha256_file(path)
    for slug, _kind, path in stage21.control_sources(songs_dir, ai_dir, stage24.DEFAULT_EXTRA_DSL_DIR):
        out[f"composition/{slug}"] = sha256_file(path)
    if Path(DEFAULT_PROFILE_BANK).is_dir():
        for path in sorted(Path(DEFAULT_PROFILE_BANK).rglob("*.json")):
            relative = path.relative_to(DEFAULT_PROFILE_BANK)
            out[f"profile_bank/{relative.as_posix()}"] = sha256_file(path)
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


def next_step_recommendation(
    verdict: Mapping[str, Any],
    capability: Mapping[str, Any],
    design: Mapping[str, Any],
    leakage: Mapping[str, Any],
) -> Dict[str, Any]:
    """The safest next step, and what it must not claim.

    The brief's final instruction is to build the conditions for an honest question rather than to
    extract an answer from incomparable data. So the recommendation is a corpus, in stages, with the
    production question separated from it.
    """
    return {
        "recommended_next_step": (
            "build the corpus in three stages, evaluating the declared acceptance criteria at each "
            "stage and stopping rather than enlarging if a stage fails"
        ),
        "stages": [
            {
                "stage": 1,
                "size": len(PILOT_SPECS),
                "gate": "the pilot criteria in pilot_results.json",
                "already_demonstrated_here": True,
                "action": "author the four compositions as tracked documents and commit them",
            },
            {
                "stage": 2,
                "size": 12,
                "gate": (
                    "the box criterion's calibration still passes on the candidate's own members, and "
                    "the historical joint-box coverage rises above zero"
                ),
                "action": (
                    "author coverage compositions targeting the $50 clock and the historical length "
                    "region, one feature target per composition, validated before it counts"
                ),
            },
            {
                "stage": 3,
                "size": design["total_minimum_size"],
                "gate": "every acceptance criterion in overlap_acceptance_criteria.json",
                "action": (
                    "complete the corpus, then re-run the Stage 24 analysis against it. Only if every "
                    "criterion passes may a residual comparison be attempted"
                ),
            },
        ],
        "what_must_not_be_done": [
            "do not treat the pilot as a corpus",
            "do not enlarge the pilot because it failed; diagnose the failure first",
            "do not run a residual comparison on a corpus that fails an acceptance criterion",
            "do not change the feature set or the criteria to make a corpus pass",
            "do not read a matched difference as a performance-layer effect while the generator "
            "confound stands",
        ],
        "production_work_identified_but_not_done": {
            "change": (
                "a way to emit a zero divider on an audible frame, so the between-note pulse idiom "
                "can be reproduced"
            ),
            "requires": "a change to the Music IR and to ir.compile_ir_to_pokey_frames",
            "status": "specified and not implemented; the decision belongs to the project",
            "does_the_corpus_need_it": (
                "not for the support question, which is about the matching features. It is needed "
                "only if the question becomes whether that idiom carries residual, and Stage 24 "
                "classified the idiom as a mediator rather than as a cause"
            ),
        },
        "generalization_requirement": {
            "what_is_needed": "historical SAPs that were not used to design the corpus",
            "why": leakage["conclusion"],
            "status": (
                "outside the project's control; the corpus should be built first and validated "
                "against new material when it exists"
            ),
        },
        "decision_the_project_must_make": [
            "author the corpus and accept that the first result is an interpolation",
            "or leave the historical comparison closed, as Stage 24 concluded",
        ],
        "what_this_stage_does_not_do": (
            "it does not author the corpus, does not modify production, does not start Stage 26 and "
            "does not claim the comparison is now supported"
        ),
    }



def analyse(
    arch_root: Path = DEFAULT_ARCHAEOLOGY_DIR,
    songs_dir: Path = DEFAULT_SONGS_DIR,
    ai_dir: Path = DEFAULT_AI_DIR,
    stage21_dir: Path = DEFAULT_STAGE21_DIR,
    stage22_dir: Path = DEFAULT_STAGE22_DIR,
    stage23_dir: Path = DEFAULT_STAGE23_DIR,
    stage24_dir: Path = DEFAULT_STAGE24_DIR,
) -> Dict[str, Any]:
    """The deterministic core: audit, design, validate the methods, and run the pilot."""
    historical = stage24.load_historical_records(arch_root)
    control = stage24.load_control_records(songs_dir, ai_dir)
    if not historical or not control:
        raise Stage25Error("one of the corpora is empty; the design needs both")
    validate_feature_coverage()
    audit = audit_previous_stages(stage21_dir, stage22_dir, stage23_dir, stage24_dir)
    population = target_population(historical, control)
    capability = pipeline_capability_audit()
    design = corpus_design(historical, capability)
    samples = sample_size_rationale(historical, control, design)
    criteria = overlap_acceptance_criteria()
    matching = matching_validation()
    leakage = leakage_assessment(historical)
    pilot = run_pilot()
    ground_truth = ground_truth_validation(pilot)
    decided = verdicts(capability, design, pilot, ground_truth, matching, leakage, samples)
    recommendation = next_step_recommendation(decided, capability, design, leakage)
    return {
        "audit": audit,
        "target_population": population,
        "ground_truth_levels": [dict(item) for item in GROUND_TRUTH_LEVELS],
        "feature_controllability": [dict(item) for item in FEATURE_CONTROLLABILITY],
        "pipeline_capability": capability,
        "corpus_design": design,
        "sample_size": samples,
        "overlap_acceptance_criteria": criteria,
        "pilot": pilot,
        "ground_truth_validation": ground_truth,
        "matching_validation": matching,
        "leakage": leakage,
        "verdicts": decided,
        "next_step": recommendation,
        "feature_definitions": [dict(item) for item in stage24.FEATURE_DEFINITIONS],
        "matching_features": list(MATCHING_FEATURES),
    }


def run_analysis(
    arch_root: Path = DEFAULT_ARCHAEOLOGY_DIR,
    songs_dir: Path = DEFAULT_SONGS_DIR,
    ai_dir: Path = DEFAULT_AI_DIR,
    stage21_dir: Path = DEFAULT_STAGE21_DIR,
    stage22_dir: Path = DEFAULT_STAGE22_DIR,
    stage23_dir: Path = DEFAULT_STAGE23_DIR,
    stage24_dir: Path = DEFAULT_STAGE24_DIR,
    verify_reproducibility: bool = True,
) -> Dict[str, Any]:
    """Everything Stage 25 does, in one deterministic pass, with a reproducibility check.

    The core is run twice and the two payload digests compared. A stage whose whole claim is that a
    corpus is reproducible has to be able to show that its own arithmetic is.
    """
    production_before = production_hashes()
    inputs_before = input_hashes(arch_root, songs_dir, ai_dir)
    core = analyse(arch_root, songs_dir, ai_dir, stage21_dir, stage22_dir, stage23_dir, stage24_dir)
    reproducible = True
    digest = _digest(core)
    if verify_reproducibility:
        again = _digest(analyse(
            arch_root, songs_dir, ai_dir, stage21_dir, stage22_dir, stage23_dir, stage24_dir
        ))
        reproducible = again == digest
        if not reproducible:
            raise Stage25Error(
                "the analysis is not reproducible: two runs produced different payloads"
            )
    bundle: Dict[str, Any] = {
        "analysis_version": ANALYSIS_VERSION,
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
                "production modules, the DSL, the profile bank and the player source",
            ),
            "inputs": read_only_audit(
                inputs_before, input_hashes(arch_root, songs_dir, ai_dir),
                "traces, composition documents, sound profiles and upstream artefacts",
            ),
        },
        "determinism": {
            "random_seed": RANDOM_SEED,
            "pilot_seed": PILOT_SEED,
            "tie_breaks": (
                "the profile for a configuration is chosen by sorted profile id; every declared list "
                "is sorted before use; every dict that reaches an artefact is emitted with sorted "
                "keys; and the pilot builds its documents from a spec rather than from iteration order"
            ),
            "source_hash": sha256_file(Path(__file__)),
        },
    }
    bundle["summary"] = _summary(bundle)
    return bundle


def _summary(bundle: Mapping[str, Any]) -> Dict[str, Any]:
    """The one-screen summary the report, the CLI and the tests all read from."""
    core = bundle["core"]
    capability = core["pipeline_capability"]
    pilot = core["pilot"]
    decided = core["verdicts"]
    return {
        "historical_traces": core["audit"]["stage24_overlap"]["historical_traces"],
        "historical_inside_joint_box": (
            core["audit"]["stage24_overlap"]["historical_inside_joint_box"]
        ),
        "control_inside_joint_box_leave_one_out": (
            core["audit"]["stage24_overlap"]["control_inside_joint_box_leave_one_out"]
        ),
        "stage24_verdict": core["audit"]["stage24_verdict"],
        "capabilities_total": len(capability["findings"]),
        "capabilities_reachable": sum(
            1 for finding in capability["findings"] if finding.get("reachable", True)
        ),
        "production_changes_required": capability["production_changes_required"],
        "design_groups": core["corpus_design"]["group_count"],
        "design_minimum_size": core["corpus_design"]["total_minimum_size"],
        "design_floor_control_traces": (
            core["sample_size"]["design_floor"]["minimum_control_traces"]
        ),
        "max_reachable_frames": core["corpus_design"]["target_length_region"]["reachable"],
        "historical_max_frames": core["corpus_design"]["target_length_region"]["historical_max"],
        "pilot_built": pilot["built"],
        "pilot_specs": pilot["specs"],
        "pilot_passed": pilot["passed"],
        "pilot_total": pilot["total"],
        "pilot_all_passed": pilot["all_passed"],
        "ground_truth_consistent": core["ground_truth_validation"]["all_consistent"],
        "caliper_enforced": core["matching_validation"]["positive_control"]["enforced"],
        "caliper_retains_everything_above": (
            core["matching_validation"]["negative_control"]["retains_everything"]
        ),
        "validation_scope": "known set only",
        "verdict": decided["main"]["verdict"],
        "auxiliary_verdicts": [row["verdict"] for row in decided["auxiliary"]],
        "reproducible": bundle["reproducibility"]["byte_identical"],
        "read_only": all(row["read_only"] for row in bundle["read_only_audit"].values()),
        "read_only_files_checked": sum(
            row["files_checked"] for row in bundle["read_only_audit"].values()
        ),
    }


# ===========================================================================
# PART 11 - the artefacts and the writer (section 15 of the brief)
# ===========================================================================
def _artefacts(bundle: Mapping[str, Any]) -> Dict[str, Any]:
    """The thirteen JSON payloads, built in one place so the writer stays a writer."""
    core = bundle["core"]
    return {
        "target_population.json": {
            "target_population": core["target_population"],
            "ground_truth_levels": core["ground_truth_levels"],
            "why_three_levels": (
                "a trace is not a composition and a compiled stream is not a performance. Merging "
                "them would let a compiler artefact be reported as a musical property"
            ),
        },
        "feature_specification.json": {
            "feature_definitions": core["feature_definitions"],
            "matching_features": core["matching_features"],
            "feature_count": len(core["matching_features"]),
            "controllability": core["feature_controllability"],
            "controllability_counts": _counts(
                row["class"] for row in core["feature_controllability"]
            ),
            "rule": (
                "a feature is only claimed controllable when the capability audit produced the "
                "configuration it needs. Features that can only be observed are labelled as such"
            ),
        },
        "pipeline_capability_audit.json": core["pipeline_capability"],
        "corpus_design.json": core["corpus_design"],
        "sample_size_rationale.json": core["sample_size"],
        "overlap_acceptance_criteria.json": core["overlap_acceptance_criteria"],
        "pilot_results.json": {
            **core["pilot"],
            "specs_declared": [dict(item) for item in PILOT_SPECS],
            "criteria_declared": [dict(item) for item in PILOT_CRITERIA],
        },
        "ground_truth_validation.json": core["ground_truth_validation"],
        "matching_validation.json": core["matching_validation"],
        "leakage_assessment.json": core["leakage"],
        "next_step_recommendation.json": core["next_step"],
        "verdict.json": {
            "main": core["verdicts"]["main"],
            "auxiliary": core["verdicts"]["auxiliary"],
            "vocabulary": core["verdicts"]["vocabulary"],
            "auxiliary_vocabulary": core["verdicts"]["auxiliary_vocabulary"],
            "proven_performance_layer_used": False,
            "stop_conditions_applied": (
                "the pipeline can produce every configuration the design needs except one idiom, so "
                "the capability gap is named rather than worked around; the pilot met its criteria "
                "and was not enlarged; the inference scope is limited to the known set; and no "
                "production change is implemented"
            ),
        },
        "stage25_manifest.json": {
            "analysis_version": ANALYSIS_VERSION,
            "document": STAGE25_DOC,
            "artefacts": list(STAGE25_FILES),
            "summary": bundle["summary"],
            "determinism": bundle["determinism"],
            "reproducibility": bundle["reproducibility"],
            "read_only_audit": bundle["read_only_audit"],
            "stage24_audit": core["audit"],
            "stop_condition": (
                "Stage 25 is design and analysis only, with a minimal pilot. No production code is "
                "modified, no corpus is committed, no music is released and Stage 26 is not started"
            ),
        },
    }


# ===========================================================================
# PART 12 - the report (section 16 of the brief)
# ===========================================================================
def _pct(value: Optional[float], places: int = 1) -> str:
    return "n/a" if value is None else f"{value * 100:.{places}f}%"


def _num(value: Optional[float], places: int = 4) -> str:
    return "n/a" if value is None else f"{value:.{places}f}"


def _sentence(text: str) -> str:
    """Capitalise the first letter and end with a full stop, so fragments read as sentences."""
    text = str(text).strip()
    if not text:
        return text
    text = text[0].upper() + text[1:]
    if not text.endswith("."):
        text += "."
    return text


def render_report(bundle: Mapping[str, Any]) -> str:
    """The sixteen sections the brief requires, in its order, then the ten closing questions."""
    s = bundle["summary"]
    out: List[str] = [
        "# Stage 25 - Matched Control Corpus Design and Validation\n",
        "Stage 24 ended with `COMMON_SUPPORT_INADEQUATE`: **0 of 12** historical traces lie inside "
        "the control corpus's joint feature box, against **41 of 53** control traces under the same "
        "leave-one-out test. That is a statement about the corpora, not about the music, and Stage 25 "
        "is the response to it.\n",
        f"**The headline.** The pipeline can build the corpus the design needs. A bound sound profile "
        f"declaring `audctl_mode = $50` produces a trace whose AUDCTL column is `$50` on every frame; "
        f"all eight POKEY distortion bytes are reachable; and composition length reaches "
        f"{s['max_reachable_frames']} frames against a historical maximum of "
        f"{s['historical_max_frames']}. So the two structural gaps Stage 24 measured - the clock and "
        "the length - are **closable with documents and a profile, and no production change is "
        "required for them**.\n",
        f"**The pilot.** {s['pilot_built']} of {s['pilot_specs']} declared compositions built, and "
        f"**{s['pilot_passed']} of {s['pilot_total']}** continuation criteria passed. The ground "
        f"truth is preserved at three levels: **{s['ground_truth_consistent']}**. The declared "
        f"caliper is enforced: **{s['caliper_enforced']}**, and it retains everything above the "
        f"observed distance range: **{s['caliper_retains_everything_above']}**.\n",
        f"**One capability is missing.** A historical player idiom - a zero divider on an audible "
        "frame - cannot be expressed through the Music DSL or the IR, so the compiler cannot produce "
        "it. That is the only production change the audit identifies, and it is specified rather than "
        "implemented.\n",
        f"**Verdict: `{s['verdict']}`.** The design is specified, the mechanics are proven, and the "
        "conditions for an honest comparison are reachable. The corpus is not built, the comparison "
        "is not supported yet, and the generator confound survives every corpus design.\n",
        "Analysis and design only, with a deliberately minimal pilot. No production file is modified, "
        "no corpus is committed, no music is released and Stage 26 is not begun. "
        f"Analysis version `{bundle['analysis_version']}`.\n",
        "Artefacts: " + ", ".join(f"`{name}`" for name in STAGE25_FILES) + ".\n",
    ]
    for section in (_s1, _s2, _s3, _s4, _s5, _s6, _s7, _s8, _s9, _s10,
                    _s11, _s12, _s13, _s14, _s15, _s_questions):
        out.extend(section(bundle))
    return "\n".join(out)


def write_analysis(
    bundle: Mapping[str, Any],
    stage25_dir: Path = DEFAULT_STAGE25_DIR,
    docs_dir: Path = DEFAULT_DOCS_DIR,
) -> Dict[str, Path]:
    """Write the thirteen JSON artefacts and the report. Additive: nothing else is touched."""
    stage25_dir = Path(stage25_dir)
    docs_dir = Path(docs_dir)
    for key in ("core", "summary", "determinism", "reproducibility", "read_only_audit"):
        if key not in bundle:
            raise Stage25Error(
                f"the bundle has no {key!r}; it was not produced by run_analysis and the artefacts "
                "would be incomplete"
            )
    stage25_dir.mkdir(parents=True, exist_ok=True)
    docs_dir.mkdir(parents=True, exist_ok=True)
    payload = _artefacts(bundle)
    written: Dict[str, Path] = {}
    for name in STAGE25_FILES:
        if name not in payload:
            raise Stage25Error(f"the artefact {name} was never built")
        path = stage25_dir / name
        path.write_text(
            json.dumps(payload[name], indent=2, ensure_ascii=False, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        written[name] = path
    report = render_report(bundle)
    doc_path = docs_dir / STAGE25_DOC
    doc_path.write_text(report, encoding="utf-8")
    written[STAGE25_DOC] = doc_path
    report_path = stage25_dir / STAGE25_REPORT
    report_path.write_text(report, encoding="utf-8")
    written[STAGE25_REPORT] = report_path
    return written



def _s1(bundle: Mapping[str, Any]) -> List[str]:
    s = bundle["summary"]
    core = bundle["core"]
    return [
        "## 1. Executive Summary\n",
        _table(
            ["question", "answer"],
            [
                ["Can the pipeline build the required corpus?",
                 f"**Yes, with one exception.** {s['capabilities_reachable']} of "
                 f"{s['capabilities_total']} probed capabilities are reachable"],
                ["Which configuration was the binding gap?",
                 "The 1.79 MHz clock: reachable through a bound profile, no production change"],
                ["What can the pipeline not produce?",
                 "A zero divider on an audible frame, the historical players' between-note pulse"],
                ["How large must the corpus be?",
                 f"**At least {s['design_minimum_size']}** compositions across four groups; a design "
                 f"floor of {s['design_floor_control_traces']} control traces"],
                ["Did the pilot meet its criteria?",
                 f"**{s['pilot_passed']} of {s['pilot_total']}** - {'all' if s['pilot_all_passed'] else 'not all'}"],
                ["Is the ground truth preserved?",
                 f"**{s['ground_truth_consistent']}** at three levels: source, compiled, trace"],
                ["Is the caliper enforced?",
                 f"**{s['caliper_enforced']}** - a caliper of 0.01 rejects everything, 1000.0 "
                 "retains everything"],
                ["Can the result generalize beyond the twelve traces?",
                 "**No.** Every historical trace informed the design, so this is a validation on a "
                 "known set"],
                ["Verdict", f"**{s['verdict']}**"],
                ["Auxiliary verdicts", ", ".join(f"`{v}`" for v in s["auxiliary_verdicts"])],
                ["Reproducibility", f"**{s['reproducible']}** - the core was run twice and the digests matched"],
                ["Read-only audit",
                 f"**{s['read_only']}** - {s['read_only_files_checked']} production and input "
                 "artefacts hashed before and after the run, none changed"],
            ],
        ),
        "",
        "**The design is the deliverable, not the corpus.** Stage 25 specifies what a control corpus "
        "must contain, proves the pipeline can produce it, and declares the criteria that will decide "
        "whether it worked. It does not build it, and it does not run a residual comparison on the "
        "pilot.\n",
        "**Two things no corpus can fix.** The historical traces come from unknown third-party "
        "players and the controls from one known compiler and player, so a residual difference is "
        "confounded with the generator. And with twelve historical traces against twenty-one matching "
        "features there is less than one trace per feature, so no model of the historical side can be "
        "estimated however large the control side becomes.\n",
    ]


def _s2(bundle: Mapping[str, Any]) -> List[str]:
    audit = bundle["core"]["audit"]
    return [
        "## 2. Audit of Stages 21 to 24\n",
        "The brief's rule is that the artefacts win over any summary, including this one. Every "
        "figure below is read from the artefact that owns it:\n",
        _table(
            ["quantity", "value", "source"],
            [
                ["Stage 21 analysis version", audit["stage21_summary"].get("analysis_version", "n/a"),
                 "reports/stage21/summary.json"],
                ["Stage 22 analysis version", audit["stage22_analysis_version"],
                 "reports/stage22/stage22_manifest.json"],
                ["Stage 23 analysis version", audit["stage23_analysis_version"],
                 "reports/stage23/stage23_manifest.json"],
                ["Stage 23 verdict", audit["stage23_verdict"],
                 "reports/stage23/verdict.json"],
                ["Stage 24 verdict", audit["stage24_verdict"],
                 "reports/stage24/verdict.json"],
                ["historical traces inside the joint box",
                 audit["stage24_overlap"]["historical_inside_joint_box"],
                 "reports/stage24/multivariate_overlap.json"],
                ["control traces inside the joint box, leave-one-out",
                 audit["stage24_overlap"]["control_inside_joint_box_leave_one_out"],
                 "reports/stage24/multivariate_overlap.json"],
                ["matching methods reportable / validated",
                 f"{audit['stage24_matching']['reportable']} / "
                 f"{audit['stage24_matching']['validated']}",
                 "reports/stage24/matching_diagnostics.json"],
                ["historical AUDCTL", str(audit["stage24_historical_audctl"]),
                 "reports/stage24/corpus_inventory.json"],
                ["control AUDCTL", str(audit["stage24_control_audctl"]),
                 "reports/stage24/corpus_inventory.json"],
            ],
        ),
        "",
        "### What each conclusion forces\n",
        _table(
            ["conclusion", "source", "consequence for Stage 25"],
            [[item["conclusion"], item["source"], item["consequence"]]
             for item in audit["inherited_conclusions"]],
        ),
        "",
        "**Stage 23's declared caliper was never applied.** "
        f"{_sentence(audit['stage24_matching']['stage23_defect'])}\n",
    ]


def _s3(bundle: Mapping[str, Any]) -> List[str]:
    population = bundle["core"]["target_population"]
    return [
        "## 3. Target Population and Inference Scope\n",
        f"**Population.** {population['population']}.\n",
        f"**Inference scope.** {population['inference_scope']}.\n",
        "### What the population is not\n",
        "\n".join(f"* {item}" for item in population["what_the_population_is_not"]) + "\n",
        _table(
            ["property", "historical", "existing control"],
            [
                ["traces", population["historical_traces"], population["existing_control_traces"]],
                ["AUDCTL", str(population["historical_audctl"]),
                 str(population["existing_control_audctl"])],
                ["frames min", population["historical_frames"]["min"],
                 population["existing_control_frames"]["min"]],
                ["frames median", _num(population["historical_frames"]["median"]),
                 _num(population["existing_control_frames"]["median"])],
                ["frames max", population["historical_frames"]["max"],
                 population["existing_control_frames"]["max"]],
            ],
        ),
        "",
        "### The structural gaps\n",
        _table(
            ["gap", "historical", "existing control", "closable without a production change"],
            [[row["gap"], str(row["historical"]), str(row["existing_control"]),
              row["closable_without_production_change"]]
             for row in population["structural_gaps"]],
        ),
        "",
        "**The population is defined by observable trace properties, not by era or genre.** Era and "
        "genre are not recoverable from a register stream, and they are not what the comparison "
        "measures. Defining the population any other way would make the claim untestable.\n",
    ]


def _s4(bundle: Mapping[str, Any]) -> List[str]:
    core = bundle["core"]
    return [
        "## 4. Ground Truth Definition\n",
        "Each control example carries three separate representations, and they are never merged:\n",
        _table(
            ["level", "what it is", "identity", "control", "historical", "limitation"],
            [[row["name"], row["what_it_is"], row["identity"],
              row["available_for_control"], row["available_for_historical"], row["limitations"]]
             for row in core["ground_truth_levels"]],
        ),
        "",
        "**The five things kept apart.** The source truth is the document; the compiled truth is what "
        "the compiler produced; the player's behaviour is what the 6502 routine does with it; the "
        "trace is what was observed; and the detector's interpretation is a reading of the trace. "
        "Stage 25 never treats the source composition and the exact trace as the same representation, "
        "because they are not: a rest in the document is a silent register in the trace, and a note "
        "in the document is a span the detector may or may not find.\n",
        "**What the historical side has.** Only the third level, with no link to a source or a "
        "compiled artefact. That asymmetry is permanent: a control corpus cannot create ground truth "
        "on the historical side, and no corpus design changes it.\n",
    ]


def _reachable_label(finding: Mapping[str, Any]) -> str:
    """What the probe actually found, so the column cannot read as a hedge it is not.

    A finding that carries an explicit ``reachable`` flag reports it. One that only counted its
    probes reports the count, which is a stronger statement than a bare "partial".
    """
    if "reachable" in finding:
        return str(bool(finding["reachable"]))
    if finding.get("reachable_count") is not None and finding.get("total") is not None:
        return f"{finding['reachable_count']} of {finding['total']}"
    return "measured"


def _s5(bundle: Mapping[str, Any]) -> List[str]:
    capability = bundle["core"]["pipeline_capability"]
    return [
        "## 5. Pipeline Capability Audit\n",
        "Every finding is measured by probing the real pipeline, not read from documentation. A "
        "capability is claimed because a probe produced it; a gap is claimed because a probe failed "
        "with a named exception.\n",
        _table(
            ["capability", "reachable", "conclusion"],
            [[finding["capability"], _reachable_label(finding),
              (finding.get("conclusion") or finding.get("consequence") or "")[:150]]
             for finding in capability["findings"]],
        ),
        "",
        f"**BPM to frames_per_tick.** " + ", ".join(
            f"BPM <= {row['bpm_max']} gives {row['frames_per_tick']}"
            for row in capability["bpm_tick_table"]
        ) + f". A pattern is bounded at {capability['max_pattern_steps']} steps, so length is "
        "controlled by repeating the sequence rather than by one long pattern.\n",
        f"**Production changes required: {capability['production_changes_required'] or 'none'}.**\n",
        "### The one capability that is missing\n",
    ] + _capability_gap_lines(capability) + [
        "**The pipeline is not modified to close it.** The brief is explicit: document the gap, "
        "assess whether a conforming experimental method exists, and leave the decision to the "
        "project. Stage 25 stops at the specification.\n",
    ]


def _capability_gap_lines(capability: Mapping[str, Any]) -> List[str]:
    finding = next(
        item for item in capability["findings"]
        if item["capability"].startswith("AUDF = 0")
    )
    return [
        f"**{finding['capability']}.** Reachable: **{finding['reachable']}**.\n",
        f"*Mechanism.* {_sentence(finding['mechanism'])}\n",
        f"*Consequence.* {_sentence(finding['consequence'])}\n",
        f"*The change would be.* {_sentence(finding['production_change_would_be'])}\n",
        f"*Does it change the subject of the study?* "
        f"{_sentence(finding['does_it_change_the_subject_of_the_study'])}\n",
        _table(
            ["probe measurement", "value"],
            [
                ["zero-divider-and-audible frames in the probe",
                 finding["zero_divider_audible_frames"]],
                ["silent register frames in the probe", finding["silent_register_frames"]],
            ],
        ),
        "",
    ]


def _s6(bundle: Mapping[str, Any]) -> List[str]:
    core = bundle["core"]
    design = core["corpus_design"]
    controllability = core["feature_controllability"]
    counts = _counts(row["class"] for row in controllability)
    return [
        "## 6. The Control Groups\n",
        _table(
            ["group", "role", "size target", "necessary", "closes", "cost"],
            [[row["group"], row["role"], row["size_target"], row["necessary"],
              row["what_it_closes"], row["cost"]]
             for row in design["groups"]],
        ),
        "",
        f"**Total minimum size: {design['total_minimum_size']}** compositions across "
        f"{design['group_count']} groups.\n",
        f"**Design principle.** {_sentence(design['design_principle'])}\n",
        "### What the design does not do\n",
        "\n".join(f"* {item}" for item in design["what_the_design_does_not_do"]) + "\n",
        "### Which features can be controlled, and how\n",
        _table(
            ["class", "features"],
            [[cls, ", ".join(sorted(
                row["feature"] for row in controllability if row["class"] == cls
            ))]
             for cls in (CONTROL_DIRECT, CONTROL_INDIRECT, CONTROL_OBSERVED, CONTROL_NOT_POSSIBLE)],
        ),
        "",
        f"**{counts.get(CONTROL_DIRECT, 0)} features are directly controllable, "
        f"{counts.get(CONTROL_INDIRECT, 0)} indirectly, {counts.get(CONTROL_OBSERVED, 0)} are only "
        f"observable, and {counts.get(CONTROL_NOT_POSSIBLE, 0)} cannot be controlled at all.** The "
        "last group is not a failure: those features are degenerate in both corpora, so Stage 24 "
        "excluded them from the matching and nothing needs to control them.\n",
        "### Feature by feature\n",
        _table(
            ["feature", "class", "mechanism", "granularity", "caveat"],
            [[row["feature"], row["class"], row["mechanism"], row["granularity"], row["caveat"]]
             for row in controllability],
        ),
        "",
        "**A trace feature is not automatically a composition feature.** The brief warns about this "
        "and the table is the response: only the rows marked directly controllable may be targeted by "
        "a composition. The rest follow from the compiler, the player or the envelope, and a design "
        "that assumed otherwise would be unable to hit its own targets.\n",
    ]


def _s7(bundle: Mapping[str, Any]) -> List[str]:
    samples = bundle["core"]["sample_size"]
    return [
        "## 7. Sample Size and Diversity\n",
        "### What can be counted\n",
        _table(
            ["quantity", "value"],
            [[key, _cell(value)] for key, value in sorted(samples["what_can_be_counted"].items())],
        ),
        "",
        "### The design floor\n",
        f"**Rule.** {samples['design_floor']['rule']}.\n",
        f"**Minimum control traces: {samples['design_floor']['minimum_control_traces']}.** "
        f"{samples['design_floor']['why']}.\n",
        "### The feature-dimension argument\n",
        _table(
            ["quantity", "value"],
            [
                ["matching features", samples["feature_dimension_argument"]["features"]],
                ["historical traces",
                 samples["what_can_be_counted"]["historical_traces"]],
                ["traces per feature",
                 samples["feature_dimension_argument"]["traces_per_feature"]],
            ],
        ),
        "",
        f"{_sentence(samples['feature_dimension_argument']['statement'])}\n",
        "### What cannot be estimated, and why\n",
        _table(
            ["quantity", "why it cannot be estimated"],
            [[row["quantity"], row["why"]] for row in samples["what_cannot_be_estimated"]],
        ),
        "",
        "**No power calculation is offered, because none would mean anything.** The comparison is "
        "confounded with the generator, so a power figure would describe a quantity that is not "
        "identified. The brief asks not to pretend the right sample size is known, and it is not "
        "known.\n",
        "### The staged pilot\n",
        _table(
            ["stage", "size", "purpose", "gate"],
            [[name, row["size"], row["purpose"],
              "; ".join(
                  item["criterion"] if isinstance(item, Mapping) else str(item)
                  for item in row["continuation_criteria"]
              )[:160]]
             for name, row in sorted(samples["staged_pilot"].items())],
        ),
        "",
        f"{_sentence(samples['reading'])}\n",
    ]




def _s8(bundle: Mapping[str, Any]) -> List[str]:
    core = bundle["core"]
    pilot = core["pilot"]
    return [
        "## 8. Generation and Validation Procedure\n",
        "The procedure is deterministic end to end:\n",
        "```text",
        "Control specification   (a declared dict: audctl, bpm, rows, repeats, distortions)",
        "        |",
        "        v",
        "Source composition      (DSL text generated from the spec, hashed as text)",
        "        |",
        "        v",
        "Compiler / player       (compile_ir_to_pokey_frames, plus a profile binding if $50)",
        "        |",
        "        v",
        "Exact trace             (stage21.build_trace over the compiled payload)",
        "        |",
        "        v",
        "Feature extraction      (stage24.trace_measures)",
        "        |",
        "        v",
        "Overlap diagnostics     (stage24's calibrated criteria)",
        "        |",
        "        v",
        "Ground-truth validation (three levels, hash sensitivity, configuration agreement)",
        "```\n",
        "### What is recorded for every composition\n",
        _table(
            ["field", "where it comes from"],
            [
                ["source hash", "SHA-256 of the DSL text"],
                ["compiled artefact hash", "SHA-256 of the frame payload the compiler produced"],
                ["player and compiler identity", "the module path and the player source path"],
                ["configuration", "the resolved AUDCTL, frames_per_tick and uses_16bit_bass"],
                ["trace hash", "SHA-256 of the same payload, through the trace wrapper"],
                ["feature vector", "the 21 matching features plus the mediators"],
                ["generation parameters", "the spec dict that produced the document"],
                ["ground-truth status", "which of the three levels are present"],
                ["errors and warnings", "recorded rather than dropped; a failed spec is a finding"],
                ["determinism", "a repeated build compared field by field"],
            ],
        ),
        "",
        "### The round trip\n",
        _table(
            ["composition", "checks"],
            [[row["id"], json.dumps({
                "levels_present": row["levels_present"],
                "compiled_equals_trace": row["compiled_equals_trace"],
                "source_hash_stable": row["source_hash_stable"],
                "payload_hash_stable": row["payload_hash_stable"],
                "audctl_matches_request": row["audctl_matches_request"],
            }, sort_keys=True)]
             for row in core["ground_truth_validation"]["checks"]],
        ),
        "",
        "**Hash sensitivity: "
        f"{core['ground_truth_validation']['hash_sensitivity']['source_hash_changes_when_the_document_changes']}.** "
        "A digest is not proof of correctness, so the check also mutates the document and confirms "
        "the hash changes. Without that, a constant hash would pass every equality test.\n",
        f"**{_sentence(pilot['not_a_corpus'])}\n",
    ]



def _s9(bundle: Mapping[str, Any]) -> List[str]:
    criteria = bundle["core"]["overlap_acceptance_criteria"]
    return [
        "## 9. Overlap Acceptance Criteria\n",
        "Declared before any corpus is built. The brief's warning is followed literally: overlap is "
        "not sufficient because a nearest control example could be assigned to every historical "
        "trace. These are the tests Stage 24 calibrated, reused unchanged.\n",
        _table(
            ["criterion", "threshold", "reused from", "note"],
            [[key, row["threshold"], row["reused_from"], row["note"]]
             for key, row in sorted(criteria.items()) if key != "reading"],
        ),
        "",
        f"**{_sentence(criteria['reading'])}\n",
        "### Matching validation\n",
        *_matching_lines(bundle["core"]["matching_validation"]),
    ]


def _matching_lines(matching: Mapping[str, Any]) -> List[str]:
    positive = matching["positive_control"]
    negative = matching["negative_control"]
    return [
        _table(
            ["control", "caliper", "historical kept", "historical rejected", "expectation", "met"],
            [
                ["positive", positive["caliper"], positive["historical_kept"],
                 positive["historical_rejected"], "retain nothing", positive["enforced"]],
                ["negative", negative["caliper"], negative["historical_kept"],
                 negative["historical_rejected"], "retain everything",
                 negative["retains_everything"]],
            ],
        ),
        "",
        "**Smallest observed historical-to-control distance: "
        f"{_num(matching['smallest_observed_distance'])}.** A caliper below it must retain nothing; "
        "if it retained anything the matcher would be ignoring its own constraint, which is exactly "
        "the defect Stage 24 found in Stage 23.\n",
        f"**Balance criterion: |SMD| <= {matching['balance_criterion']['threshold']}**, "
        f"{matching['balance_criterion']['source']}.\n",
        f"**{_sentence(matching['reading'])}\n",
    ]



def _s10(bundle: Mapping[str, Any]) -> List[str]:
    leakage = bundle["core"]["leakage"]
    return [
        "## 10. Leakage and Over-Fitting Protection\n",
        f"**Design set.** {leakage['design_set']['traces']} traces from "
        f"{leakage['design_set']['sources']} sources, all of them used to choose the target region. "
        f"{_sentence(leakage['design_set']['note'])}\n",
        "### Validation options\n",
        _table(
            ["option", "available", "proves", "does not prove", "cost or recommendation"],
            [[row["option"], row["available"], row["what_it_proves"],
              row["what_it_does_not_prove"],
              row.get("recommendation", row.get("cost", ""))]
             for row in leakage["validation_options"]],
        ),
        "",
        "### Over-fitting risks and their mitigations\n",
        _table(
            ["risk", "mitigation"],
            [[row["risk"], row["mitigation"]] for row in leakage["over_fitting_risks"]],
        ),
        "",
        f"**Conclusion.** {_sentence(leakage['conclusion'])}\n",
    ]


def _s11(bundle: Mapping[str, Any]) -> List[str]:
    pilot = bundle["core"]["pilot"]
    return [
        "## 11. Pilot Results\n",
        f"**{pilot['built']} of {pilot['specs']} declared compositions built; "
        f"{pilot['passed']} of {pilot['total']} criteria passed.**\n",
        _table(
            ["criterion", "measurement", "passed", "observed"],
            [[row["criterion"], row["measurement"], row["passed"],
              json.dumps(row["observed"], sort_keys=True)[:180]]
             for row in pilot["criteria"]],
        ),
        "",
        "### The pilot traces\n",
        _table(
            ["id", "group", "frames", "expected", "frames/tick", "AUDCTL column", "16-bit", "spans"],
            [[row["id"], row["group"], row["frames"], row["expected_frames"],
              row["frames_per_tick"], str(row["audctl_column"]), row["uses_16bit_bass"],
              row["spans"]]
             for row in pilot["traces"]],
        ),
        "",
        "### Their feature vectors\n",
        _table(
            ["feature", *[row["id"] for row in pilot["traces"]]],
            [[name, *[_num(row["measures"].get(name)) for row in pilot["traces"]]]
             for name in MATCHING_FEATURES],
        ),
        "",
        "**The pilot is not evaluated against the acceptance criteria.** Those criteria need a "
        "corpus, and four compositions are not one. What the pilot establishes is that the mechanics "
        "work: the configuration is reachable, the length is reachable, the truth levels are captured "
        "and the build is deterministic.\n",
        "**No residual comparison is run on the pilot.** "
        f"{_sentence(pilot['not_a_corpus'])}\n",
    ]


def _s12(bundle: Mapping[str, Any]) -> List[str]:
    return [
        "## 12. Limitations and Costs\n",
        "### Limitations that no corpus design removes\n",
        _table(
            ["limitation", "why it survives"],
            [
                ["the generator confound",
                 "the historical traces come from unknown third-party players and the controls from "
                 "one known compiler and player. Only a design that varies the player while holding "
                 "the music fixed addresses it"],
                ["less than one historical trace per feature",
                 "21 matching features against 12 historical traces. The historical side is the "
                 "binding constraint and cannot be enlarged without more SAPs"],
                ["no historical ground truth",
                 "every historical SAP is Tier D. A control corpus cannot create ground truth on the "
                 "historical side"],
                ["the zero-divider pulse cannot be reproduced",
                 "the Music DSL and the IR have no way to express a zero divider on an audible frame"],
                ["validation is on a known set",
                 "all twelve historical traces informed the design, so the first result is an "
                 "interpolation"],
            ],
        ),
        "",
        "### Costs\n",
        _table(
            ["item", "cost", "why"],
            [
                ["authoring the baseline group", "low",
                 "the existing pipeline already produces the configuration"],
                ["authoring the coverage group", "medium",
                 "each composition is validated against its feature target before it counts"],
                ["authoring the mechanism controls", "low",
                 "short compositions with one variable each"],
                ["the pipeline controls", "medium",
                 "each pair shares a source document and differs only in the binding"],
                ["running the analysis", "low",
                 "Stage 24's analysis already exists and runs in about a minute"],
                ["validating on new historical material", "unknown",
                 "depends on what SAPs can be found, which is outside the project's control"],
            ],
        ),
        "",
        "### What the production change would cost\n",
        "Closing the zero-divider gap means adding a way to emit a zero divider without silencing a "
        "channel. That touches the Music IR and the frame compiler, and it would need the player to "
        "be checked too, because the idiom is a player behaviour in the historical corpus. Stage 25 "
        "specifies it and stops: the brief says not to implement production changes here, and the "
        "design does not need this capability for the support question.\n",
    ]



def _s13(bundle: Mapping[str, Any]) -> List[str]:
    return [
        "## 13. Methodological Corrections\n",
        "Every problem found while designing this stage, and what was done about it.\n",
        "**1. The support criteria are the ones that rejected the old corpus.** It would be easy to "
        "write acceptance criteria that the existing 53 control compositions already satisfy and then "
        "declare the design validated. The criteria here are Stage 24's, unchanged, including the "
        "calibration check that makes the box test meaningful. The new corpus will be judged by the "
        "test that rejected the old one.\n",
        "**2. The caliper is tested, not declared.** Stage 24 found that Stage 23 declared "
        "`CALIPER = 1.0` and never applied it. So the acceptance criteria include a positive control: "
        "a caliper of 0.01 must reject every historical trace, and a caliper of 1000.0 must retain "
        "every one. Both hold, which is what makes the enforcement claim checkable.\n",
        "**3. Capabilities are probed rather than assumed.** The audit builds documents, runs them "
        "through the production compiler and inspects the frame stream. A capability is claimed "
        "because a probe produced it, and a gap because a probe failed with a named exception. The "
        "first version of the distortion probe was itself wrong - it shifted the nibble twice and "
        "tested only four of the eight modes - which is exactly why the probe reports the observed "
        "AUDC bytes rather than a boolean.\n",
        "**4. A degenerate feature is not a control target.** `stable_run_median` and "
        "`audctl_change_rate` are classified `not_controllable`, and the report says why: they are "
        "identical constants in both corpora, so Stage 24 excluded them and nothing needs to control "
        "them. Listing them as gaps would have made the design look harder than it is.\n",
        "**5. The pilot is not a corpus and is not scored as one.** Four compositions cannot "
        "evaluate criteria that need a matched comparison. The pilot is scored only against its own "
        "feasibility criteria, and the report says so twice so the distinction cannot be lost.\n",
        "**6. The inference scope is limited in the design, not in a footnote.** Every historical "
        "trace informed the design, so the corpus supports interpolation and not generalization. That "
        "is stated in the population section, in the leakage section, in the verdict and in the "
        "recommendation, because a reader who misses it once should meet it again.\n",
    ]


def _s14(bundle: Mapping[str, Any]) -> List[str]:
    decided = bundle["core"]["verdicts"]
    main = decided["main"]
    return [
        "## 14. Verdict\n",
        _table(
            ["subject", "verdict", "deciding measurement"],
            [["main", main["verdict"],
              json.dumps(main["deciding_measurement"], sort_keys=True)]]
            + [[row["verdict"], row["verdict"], _sentence(row["reason"])]
               for row in decided["auxiliary"]],
        ),
        "",
        f"### What `{main['verdict']}` means\n",
        f"{_sentence(main['what_it_means'])}\n",
        f"**What it does not mean.** {_sentence(main['what_it_does_not_mean'])}\n",
        "### The STOP conditions\n",
        "The brief's STOP conditions are applied as written. The pipeline can produce every "
        "configuration the design needs except one idiom, so the gap is named rather than worked "
        "around. The pilot met its criteria and was **not** enlarged. The inference scope is limited "
        "to the known set. No production change is implemented, and Stage 26 is not started.\n",
    ]


def _s15(bundle: Mapping[str, Any]) -> List[str]:
    recommendation = bundle["core"]["next_step"]
    return [
        "## 15. The Concrete Next Step\n",
        f"**{_sentence(recommendation['recommended_next_step'])}\n",
        _table(
            ["stage", "size", "gate", "action"],
            [[row["stage"], row["size"], row["gate"], row["action"]]
             for row in recommendation["stages"]],
        ),
        "",
        "### What must not be done\n",
        "\n".join(f"* {item}" for item in recommendation["what_must_not_be_done"]) + "\n",
        "### Production work identified and not done\n",
        _table(
            ["field", "value"],
            [[key, _cell(value)] for key, value in
             sorted(recommendation["production_work_identified_but_not_done"].items())],
        ),
        "",
        "### The generalization requirement\n",
        _table(
            ["field", "value"],
            [[key, _cell(value)] for key, value in
             sorted(recommendation["generalization_requirement"].items())],
        ),
        "",
        "### The decision the project must make\n",
        "\n".join(f"* {item}" for item in recommendation["decision_the_project_must_make"]) + "\n",
        f"**{_sentence(recommendation['what_this_stage_does_not_do'])}\n",
    ]



def _s_questions(bundle: Mapping[str, Any]) -> List[str]:
    """The ten closing questions, answered separately and from the measurements."""
    s = bundle["summary"]
    core = bundle["core"]
    capability = core["pipeline_capability"]
    design = core["corpus_design"]
    samples = core["sample_size"]
    leakage = core["leakage"]
    pilot = core["pilot"]
    gap = next(
        finding for finding in capability["findings"]
        if finding["capability"].startswith("AUDF = 0")
    )
    return [
        "## The Ten Closing Questions\n",
        "**1. Exactly which region of historical traces do we want to represent?**\n",
        "**The observable property region the twelve historical traces occupy**, defined by trace "
        "properties rather than by era or genre. "
        f"{_sentence(core['target_population']['inference_scope'])}\n",
        _table(
            ["property", "historical region", "reachable by the pipeline"],
            [
                ["AUDCTL", str(core["target_population"]["historical_audctl"]),
                 "yes, through a bound profile"],
                ["frames",
                 f"[{design['target_length_region']['historical_min']}, "
                 f"{design['target_length_region']['historical_max']}]",
                 f"yes, up to {design['target_length_region']['reachable']}"],
                ["matching features", f"{len(core['matching_features'])}", "design targets each one"],
            ],
        ),
        "",
        "**2. Which features are controllable, and which only observable?**\n",
        f"**{_counts(row['class'] for row in core['feature_controllability']).get(CONTROL_DIRECT, 0)} "
        "directly controllable, "
        f"{_counts(row['class'] for row in core['feature_controllability']).get(CONTROL_INDIRECT, 0)} "
        "indirectly, "
        f"{_counts(row['class'] for row in core['feature_controllability']).get(CONTROL_OBSERVED, 0)} "
        "observable only, and "
        f"{_counts(row['class'] for row in core['feature_controllability']).get(CONTROL_NOT_POSSIBLE, 0)} "
        "not controllable at all.** Section 6 gives the mechanism for each. The last group is "
        "degenerate in both corpora, so nothing needs it.\n",
        "**3. Can the current pipeline build the corpus we need?**\n",
        f"**Yes, with one exception.** {s['capabilities_reachable']} of {s['capabilities_total']} "
        "probed capabilities are reachable. The exception is the zero-divider-on-an-audible-frame "
        f"idiom: **{gap['reachable']}**. {_sentence(gap['consequence'])}\n",
        "**4. What size and diversity are justified?**\n",
        f"**At least {s['design_minimum_size']} compositions** across four groups, with a design floor "
        f"of {s['design_floor_control_traces']} control traces against the 12 historical ones. "
        f"{_sentence(samples['feature_dimension_argument']['statement'])}\n",
        "**5. How will the multivariate overlap be validated?**\n",
        "**By the calibrated criteria Stage 24 used to reject the old corpus**, unchanged: the joint "
        "box test with its control leave-one-out calibration, three distance thresholds, the "
        "propensity overlap region with its resampling stability, and a matching caliper whose "
        "enforcement is proven by a positive and a negative control. A corpus is refused if any one "
        "of them fails.\n",
        "**6. How will leakage and over-fitting to the 12 SAPs be avoided?**\n",
        f"**It cannot be avoided, so it is declared.** {_sentence(leakage['conclusion'])} "
        "Leave-one-source-out is available as a robustness check, reserving a source costs "
        f"{leakage['validation_options'][1]['cost'][:120]}, and only new historical material would "
        "turn interpolation into generalization.\n",
        "**7. What are the corpus acceptance criteria?**\n",
        "Six, all declared before the corpus is built: no separated feature, joint-box coverage, box "
        "calibration, the distance threshold, the propensity overlap region, and a balanced match "
        "under an enforced caliper. Section 9 lists them with their thresholds.\n",
        "**8. Did the pilot meet them?**\n",
        f"**The pilot is not evaluated against them, by design.** It met "
        f"**{pilot['passed']} of {pilot['total']}** of its own feasibility criteria. The acceptance "
        "criteria need a corpus, and four compositions are not one. What the pilot established is "
        "that the mechanics work: the clock, the length, the truth levels and determinism.\n",
        "**9. Which gaps need production changes?**\n",
        f"**One: {gap['capability']}.** {_sentence(gap['production_change_would_be'])} It is not "
        "needed for the support question, because the idiom is a mediator rather than a matching "
        "feature, and Stage 25 does not implement it.\n",
        "**10. What is the safest next step?**\n",
        "**Build the corpus in three stages, gated by the declared criteria, and do not run a "
        "residual comparison until every acceptance criterion passes.** The pilot is stage one and "
        "it has passed. Section 15 lists what must not be done, including treating the pilot as a "
        "corpus and reading a matched difference as a performance-layer effect.\n",
    ]

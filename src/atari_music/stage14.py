"""Stage 14 — final evidence synthesis and the SoundProfile go/no-go.

Analysis only. This module reads the published Stage 7B/9D/9E/10A/10B/11/12A/13A artifacts
(including the two answer sheets that were filled in after those stages closed) and assembles
the evidence base, the master matrix, the hypothesis verdicts, the direct-transfer assessment,
the context-dependence assessment, the knowledge-base assessment and the architectural
decision. Nothing is rendered, nothing is changed, and no new listening is asked for.
"""

from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_REPORTS_DIR = REPO_ROOT / "reports"
DEFAULT_STAGE14_DIR = DEFAULT_REPORTS_DIR / "stage14"
DEFAULT_DOCS_DIR = REPO_ROOT / "docs"
DEFAULT_ARCHAEOLOGY_DIR = Path(r"C:\Users\grzes\Documents\Projects\pokey-sound-architecture")
DEFAULT_STAGE12A_PACKAGE = REPO_ROOT / "examples" / "stage12a_listening"
DEFAULT_STAGE13A_PACKAGE = REPO_ROOT / "examples" / "stage13a_listening"
DEFAULT_STAGE10A_PACKAGE = REPO_ROOT / "examples" / "sound_profile_rebinding_10a"
DEFAULT_STAGE10B_PACKAGE = REPO_ROOT / "examples" / "sound_profile_volume_contour_10b"

ANALYSIS_VERSION = "stage14/1"

#: The four claims the brief requires keeping apart for every capability.
CLAIMS = (
    "A_technically_representable",
    "B_acoustically_measurable",
    "C_perceptually_detectable",
    "D_perceptually_useful",
)


class Stage14Error(RuntimeError):
    """A required published artefact is missing or malformed."""


def _read_json(path: Path) -> Any:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError as error:
        raise Stage14Error(f"missing artefact: {path}") from error
    except json.JSONDecodeError as error:
        raise Stage14Error(f"malformed JSON: {path}: {error}") from error


def sha256_file(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read_answers(package_dir: Path, sheet_name: str) -> List[Dict[str, str]]:
    path = Path(package_dir) / sheet_name
    if not path.is_file():
        return []
    with path.open(encoding="utf-8", newline="") as handle:
        return [row for row in csv.DictReader(handle) if (row.get("better_overall") or "").strip()]


def decode_sheet(package_dir: Path, sheet_name: str) -> Dict[str, Any]:
    """Resolve a filled answer sheet through its private manifest, then aggregate by pair.

    Observed, and nothing more: which variant each answer named, and how the answers split per
    comparison. Any judgement about what that means is made elsewhere.
    """
    package_dir = Path(package_dir)
    manifest = _read_json(package_dir / "manifest.json")
    trials = {trial["trial_id"]: trial for trial in manifest["trials"]}
    sheet = package_dir / sheet_name
    rows = read_answers(package_dir, sheet_name)

    per_trial: List[Dict[str, Any]] = []
    by_pair: Dict[str, Dict[str, int]] = {}
    for row in rows:
        trial = trials.get(row["trial_id"])
        if trial is None:
            raise Stage14Error(f"{sheet_name} names an unknown trial: {row['trial_id']}")
        sides = trial["sides"]
        picked = (row.get("better_overall") or "").strip().lower()
        variant = sides.get(picked)
        compared = trial.get("compared") or {}
        left, right = compared.get("left"), compared.get("right")
        bucket = by_pair.setdefault(
            f"{left}_vs_{right}", {"left": 0, "right": 0, "none": 0, "n": 0}
        )
        if variant is None:
            bucket["none"] += 1
        elif variant == left:
            bucket["left"] += 1
        else:
            bucket["right"] += 1
        bucket["n"] += 1
        per_trial.append(
            {
                "trial_id": row["trial_id"],
                "level": trial.get("level"),
                "compared": compared,
                "sides": sides,
                "picked": picked,
                "picked_variant": variant,
                "ratings": {
                    key: value
                    for key, value in row.items()
                    if key not in {"trial_id", "better_overall"}
                },
            }
        )
    return {
        "sheet": sheet_name,
        "sheet_sha256": sha256_file(sheet) if sheet.is_file() else None,
        "manifest_sha256": sha256_file(package_dir / "manifest.json"),
        "answered": len(rows),
        "trials": len(trials),
        "by_pair": by_pair,
        "per_trial": per_trial,
    }


# ---------------------------------------------------------------------------
# Part 1 — collecting the published evidence
# ---------------------------------------------------------------------------
def collect_archaeology(arch_root: Path = DEFAULT_ARCHAEOLOGY_DIR) -> Dict[str, Any]:
    """The producer-side evidence: the listener's own ratings and the playability audit."""
    arch_root = Path(arch_root)
    out: Dict[str, Any] = {"available": arch_root.is_dir()}
    summary_path = arch_root / "reports" / "stage7b" / "human_evaluation_summary.json"
    if summary_path.is_file():
        summary = _read_json(summary_path)
        predictors = sorted(
            summary["usefulness_predictors"]["results"],
            key=lambda entry: abs(entry["spearman_rho"]),
            reverse=True,
        )
        out["stage7b"] = {
            "candidates": summary["dataset"]["candidates"],
            "trials": summary["dataset"]["core_trials"] + summary["dataset"]["comparison_trials"],
            "comments": summary["dataset"]["comments"],
            "fidelity_vs_similarity_rho": summary["fidelity_vs_perception"]["similarity"][
                "spearman_rho"
            ],
            "fidelity_vs_character_rho": summary["fidelity_vs_perception"]["character"][
                "spearman_rho"
            ],
            "vocabulary": [
                {"term": group["group"], "comments": group["support"]}
                for group in summary["qualitative_groups"]
            ],
            "top_usefulness_predictors": [
                {"label": entry["label"], "n": entry["n"], "rho": entry["spearman_rho"]}
                for entry in predictors[:4]
            ],
        }
    audit_path = arch_root / "reports" / "stage8c" / "playability_audit.json"
    if audit_path.is_file():
        audit = _read_json(audit_path)
        out["stage8c"] = {
            "status_totals": audit["status_totals"],
            "headline": audit["headline"],
            "consumer_gap_totals": audit["consumer_gap_totals"],
        }
    return out


def collect_composer(reports_dir: Path = DEFAULT_REPORTS_DIR) -> Dict[str, Any]:
    """The consumer-side evidence, read from each stage's own machine record."""
    reports_dir = Path(reports_dir)
    out: Dict[str, Any] = {}

    nine_d = reports_dir / "stage9d"
    if (nine_d / "coverage.json").is_file():
        coverage = _read_json(nine_d / "coverage.json")
        out["stage9d"] = {
            "profiles": coverage["profiles"],
            "distinct_audio_signals": coverage["distinct_audio_signals"],
            "redundant_profiles": coverage["redundant_profiles"],
            "identical_audio_groups": len(coverage["identical_audio_groups"]),
            "largest_group": max(group["size"] for group in coverage["identical_audio_groups"]),
            "verdict": _read_json(nine_d / "verdict.json")["verdict"],
            "mean_usefulness": _read_json(nine_d / "verdict.json")["mean_usefulness"],
            "mean_distinctiveness": _read_json(nine_d / "verdict.json")["mean_distinctiveness"],
            "unmet": _read_json(nine_d / "verdict.json")["unmet"],
        }

    nine_e = reports_dir / "stage9e"
    if (nine_e / "pipeline_fields.json").is_file():
        fields = _read_json(nine_e / "pipeline_fields.json")["propagation"]
        dup = _read_json(nine_e / "duplicate_groups.json")["summary"]
        loss = _read_json(nine_e / "information_loss.json")["loss"]
        out["stage9e"] = {
            "leaf_paths": fields["path_count"],
            "read_by_binding": len(fields["read_paths"]),
            "status_totals": fields["status_totals"],
            "sections": fields["sections"],
            "duplicate_groups": dup["groups"],
            "redundant_profiles": dup["redundant_profiles"],
            "group_sizes": dup["group_sizes"],
            "first_divergence": "bound_ir",
            "loss_points": {point["id"]: point["classified_as"] for point in loss["loss_points"]},
            "gesture_lost": loss["gesture_lost"],
        }

    stage11 = reports_dir / "stage11"
    if (stage11 / "go_no_go.json").is_file():
        out["stage11a"] = {
            "ranking": _read_json(stage11 / "hypothesis_ranking.json"),
            "go_no_go": _read_json(stage11 / "go_no_go.json"),
            "collapse": _read_json(stage11 / "collapse.json"),
            "representation_gap_counts": _read_json(stage11 / "representation_gap.json")["counts"],
            "feature_classes": {
                row["feature"]: row["class"]
                for row in _read_json(stage11 / "feature_classification.json")
            },
        }
    if (stage11 / "spectral_summary.json").is_file():
        out["stage11b"] = _read_json(stage11 / "spectral_summary.json")

    stage12a = reports_dir / "stage12a"
    if (stage12a / "hypotheses.json").is_file():
        out["stage12a"] = {
            "hypotheses": _read_json(stage12a / "hypotheses.json"),
            "summary": _read_json(stage12a / "summary.json"),
        }

    stage13a = reports_dir / "stage13a"
    if (stage13a / "hypotheses.json").is_file():
        out["stage13a"] = {
            "reconnaissance": _read_json(stage13a / "reconnaissance.json"),
            "selection": _read_json(stage13a / "selection.json"),
            "hypotheses": _read_json(stage13a / "hypotheses.json"),
            "listening": _read_json(stage13a / "listening.json"),
        }
    return out


def collect_listening(
    reports_dir: Path = DEFAULT_REPORTS_DIR,
    *,
    stage12a_package: Path = DEFAULT_STAGE12A_PACKAGE,
    stage13a_package: Path = DEFAULT_STAGE13A_PACKAGE,
) -> Dict[str, Any]:
    """The listening results, from the published re-evaluations and the two newer sheets.

    Stage 10A and 10B were re-evaluated in Stage 11A; those records are reused rather than
    recomputed. Stage 12A and 13A closed after Stage 11, so their sheets are decoded here for
    the first time, in the same way.
    """
    reports_dir = Path(reports_dir)
    out: Dict[str, Any] = {}
    for name, key in (
        ("stage10a_reevaluation.json", "stage10a"),
        ("stage10b_reevaluation.json", "stage10b"),
    ):
        path = reports_dir / "stage11" / name
        if path.is_file():
            out[key] = _read_json(path)
    if (Path(stage12a_package) / "manifest.json").is_file():
        out["stage12a"] = decode_sheet(stage12a_package, "evaluation_stage12a.csv")
    if (Path(stage13a_package) / "manifest.json").is_file():
        out["stage13a"] = decode_sheet(stage13a_package, "evaluation_stage13a.csv")
    return out


# ---------------------------------------------------------------------------
# Part 2 — the master evidence matrix
# ---------------------------------------------------------------------------
def _pair_text(decode: Mapping[str, Any], pair: str, level: Optional[int] = None) -> str:
    """A compact ``left-right`` (plus ties) rendering of one compared pair, optionally by level."""
    left = right = none = total = 0
    for trial in decode.get("per_trial", []):
        compared = trial.get("compared") or {}
        if f"{compared.get('left')}_vs_{compared.get('right')}" != pair:
            continue
        if level is not None and trial.get("level") != level:
            continue
        variant = trial.get("picked_variant")
        if variant is None:
            none += 1
        elif variant == compared.get("left"):
            left += 1
        else:
            right += 1
        total += 1
    if not total:
        return "—"
    text = f"{left}-{right}"
    if none:
        text += f" ({none} tie{'' if none == 1 else 's'})"
    return text


def evidence_matrix(
    composer: Mapping[str, Any], listening: Mapping[str, Any]
) -> List[Dict[str, Any]]:
    """One row per capability, with the four claims kept apart.

    Cells are ``POSITIVE`` / ``NEGATIVE`` / ``INCONCLUSIVE`` / ``NOT_TESTED`` as the evidence
    allows, and a ``note`` carries the number behind each judgement.
    """
    a10 = listening.get("stage10a", {})
    a12 = listening.get("stage12a", {})
    a13 = listening.get("stage13a", {})
    return [
        {
            "capability": "generator / distortion",
            "A_technically_representable": "POSITIVE",
            "B_acoustically_measurable": "POSITIVE",
            "C_perceptually_detectable": "POSITIVE",
            "D_perceptually_useful": "INCONCLUSIVE",
            "note": "read by the binding and the frame compiler; 9D `same_generator` vs similarity "
            "rho -0.5993 and disjoint clean/noisy families make it the axis the listener keys on, "
            "but no experiment varied the generator alone and asked for a preference",
            "provenance": "stage9e/pipeline_fields.json; stage9d/correlations.json",
            "evidence_strength": "STRONG (detection), NONE (preference)",
            "verdict": "SUPPORTED as a perceptual axis; preference untested",
        },
        {
            "capability": "static envelope (ADSR)",
            "A_technically_representable": "POSITIVE",
            "B_acoustically_measurable": "POSITIVE",
            "C_perceptually_detectable": "NOT_TESTED",
            "D_perceptually_useful": "NOT_TESTED",
            "note": "the four-number player state machine; 9E measured `envelope.decay_frames` as "
            "inert, and Stage 12A changed the envelope in 3 of 6 cases with no preference test",
            "provenance": "stage9e/information_loss.json (L2); stage12a/summary.json",
            "evidence_strength": "WEAK",
            "verdict": "NOT_TESTED in isolation",
        },
        {
            "capability": "AUDCTL / clock",
            "A_technically_representable": "POSITIVE",
            "B_acoustically_measurable": "POSITIVE",
            "C_perceptually_detectable": "NOT_TESTED",
            "D_perceptually_useful": "NOT_TESTED",
            "note": "one song-global byte; 9E measured the AUDCTL column as audible for PAIR and "
            "inert for VOICE; Stage 12A classified it GLOBAL_CONSTRAINT, not decorative",
            "provenance": "stage9e/pipeline_fields.json; reports/stage12a/summary.json",
            "evidence_strength": "WEAK",
            "verdict": "NOT_TESTED in isolation",
        },
        {
            "capability": "16-bit coupling",
            "A_technically_representable": "POSITIVE",
            "B_acoustically_measurable": "POSITIVE",
            "C_perceptually_detectable": "INCONCLUSIVE",
            "D_perceptually_useful": "INCONCLUSIVE",
            "note": "18 of 61 renderable profiles are PAIR; 9D `same_scope` vs similarity is only "
            "-0.308, the weakest of its six cues, and Stage 13A's donor control was a coupled "
            "trajectory that the listener preferred 2-1 where it was audible",
            "provenance": "stage9d/correlations.json; stage13a listening sheet",
            "evidence_strength": "WEAK",
            "verdict": "INCONCLUSIVE",
        },
        {
            "capability": "volume contour",
            "A_technically_representable": "POSITIVE",
            "B_acoustically_measurable": "POSITIVE",
            "C_perceptually_detectable": "POSITIVE",
            "D_perceptually_useful": "NEGATIVE",
            "note": "transferred frame-for-frame and heard in 7 of 18 pairs; profile-level 0-0-8, "
            "whole-song 1-2-3, resolved verdict NEGATIVE (Stage 10B)",
            "provenance": "stage10b_reevaluation.json; docs/stage10b_volume_contour_listening.md",
            "evidence_strength": "MODERATE (detection), STRONG (negative preference)",
            "verdict": "NEGATIVE",
        },
        {
            "capability": "pitch trajectory",
            "A_technically_representable": "POSITIVE",
            "B_acoustically_measurable": "POSITIVE",
            "C_perceptually_detectable": "POSITIVE",
            "D_perceptually_useful": "NEGATIVE",
            "note": "8 of 8 technically transferred, 6 of 8 measurably beyond static pitch; in the "
            "blind sheet the isolated pairs preferred it 4-0 and it was heard as `modulated` against "
            "a `clean tone`, but the phrase pairs preferred the static side "
            f"{_pair_text(a13, 'C_vs_A', 'L2')} and the profile's own trajectory lost the donor "
            f"control {_pair_text(a13, 'C_vs_D')}",
            "provenance": "stage13a/hypotheses.json; stage13a listening sheet",
            "evidence_strength": "STRONG (detection), STRONG (negative in context)",
            "verdict": "NEGATIVE in context",
        },
        {
            "capability": "spectral structure (centroid / bandwidth / descriptors)",
            "A_technically_representable": "NEGATIVE",
            "B_acoustically_measurable": "INCONCLUSIVE",
            "C_perceptually_detectable": "INCONCLUSIVE",
            "D_perceptually_useful": "INCONCLUSIVE",
            "note": "not a field of PlayableSoundProfile 1.0; the descriptor named `spectral "
            "bandwidth (Hz)` correlates with usefulness at -0.4401 in Stage 7B and +0.6338 in Stage "
            "9D; Stage 11B found the generator already carries the audible spectral axis",
            "provenance": "stage7b/human_evaluation_summary.json; stage9d/correlations.json; "
            "stage11/spectral_summary.json",
            "evidence_strength": "WEAK (unstable sign)",
            "verdict": "INCONCLUSIVE, leaning negative",
        },
        {
            "capability": "profile replacement (the binding as it stands)",
            "A_technically_representable": "POSITIVE",
            "B_acoustically_measurable": "POSITIVE",
            "C_perceptually_detectable": "POSITIVE",
            "D_perceptually_useful": "NEGATIVE",
            "note": "9D preferred the Composer's own instruments 5-0 (one tie) on six songs, "
            "unanimously on all three questions",
            "provenance": "stage9d_human_listening_results.md",
            "evidence_strength": "STRONG (negative)",
            "verdict": "NEGATIVE",
        },
        {
            "capability": "profile decoration (keep the Composer instrument, take the generator)",
            "A_technically_representable": "POSITIVE",
            "B_acoustically_measurable": "POSITIVE",
            "C_perceptually_detectable": "POSITIVE",
            "D_perceptually_useful": "NEGATIVE",
            "note": "mechanical H1 3/6 and H2 4/6; in the blind sheet decoration lost to the "
            f"Composer baseline {_pair_text(a12, 'C_vs_A')} and drew "
            f"{_pair_text(a12, 'C_vs_B')} against replacement",
            "provenance": "stage12a/summary.json; stage12a listening sheet",
            "evidence_strength": "STRONG (negative)",
            "verdict": "NEGATIVE",
        },
        {
            "capability": "direct profile rebinding (evidence-chosen assignment)",
            "A_technically_representable": "POSITIVE",
            "B_acoustically_measurable": "POSITIVE",
            "C_perceptually_detectable": "POSITIVE",
            "D_perceptually_useful": "NEGATIVE",
            "note": f"NEW won {a10.get('primary', {}).get('new')} of "
            f"{a10.get('primary', {}).get('n')} primary pairs (other side "
            f"{a10.get('primary', {}).get('other')}, ties {a10.get('primary', {}).get('none')}); the "
            f"control put the Composer default over the old binding "
            f"{a10.get('control', {}).get('default')}-{a10.get('control', {}).get('old')}",
            "provenance": "stage11/stage10a_reevaluation.json",
            "evidence_strength": "MODERATE (negative)",
            "verdict": "NEGATIVE",
        },
    ]


# ---------------------------------------------------------------------------
# Part 5 — the five major hypotheses
# ---------------------------------------------------------------------------
def elevens_summary(composer: Mapping[str, Any]) -> str:
    """A one-line rendering of the Stage 11B expressibility split."""
    summary = composer.get("stage11b", {})
    counts = summary.get("expressibility_counts", {})
    best = summary.get("best_single_feature_counts", {})
    text = ", ".join(f"{value} {key}" for key, value in sorted(counts.items()))
    best_text = ", ".join(f"{key} ({value})" for key, value in sorted(best.items()))
    return f"the renders as {text} with the best single feature {best_text}"


def hypothesis_verdicts(
    composer: Mapping[str, Any], listening: Mapping[str, Any]
) -> List[Dict[str, Any]]:
    """One verdict per hypothesis, judged only on the published evidence."""
    a10 = listening.get("stage10a", {})
    a12 = listening.get("stage12a", {})
    a13 = listening.get("stage13a", {})
    h13 = composer.get("stage13a", {}).get("hypotheses", {})
    primary = a10.get("primary", {})
    control = a10.get("control", {})
    return [
        {
            "id": "H1",
            "hypothesis": "Profiles should replace the Composer's instruments",
            "stages": ["9D", "10A"],
            "evidence": (
                "9D: the profile-bound render lost 5-0 (one tie) to the Composer's own instruments, "
                "unanimously on all three questions. 10A: the evidence-chosen re-binding won "
                f"{primary.get('new')} of {primary.get('n')} primary pairs against "
                f"{primary.get('other')} for the other side and {primary.get('none')} ties, and its "
                f"control put the Composer default over the old binding "
                f"{control.get('default')}-{control.get('old')}."
            ),
            "verdict": "NEGATIVE",
            "confidence": "STRONG",
            "why": "two independent listening experiments, one with a byte-identical control, both "
            "put the profile-bound side last",
        },
        {
            "id": "H2",
            "hypothesis": "Profiles should decorate the Composer's instruments",
            "stages": ["12A"],
            "evidence": (
                "Mechanically plausible — H1 (decoration keeps the Composer's envelope and clock) 3 "
                "of 6, H2 (it still changes the sound) 4 of 6, and the frame proof shows only the "
                "intended columns changed. Perceptually negative: against the Composer baseline the "
                f"decoration won {_pair_text(a12, 'C_vs_A')}; against replacement it won "
                f"{_pair_text(a12, 'C_vs_B')}."
            ),
            "verdict": "NEGATIVE",
            "confidence": "STRONG",
            "why": "the mechanism worked exactly as designed and the listener still preferred what it "
            "replaced",
        },
        {
            "id": "H3",
            "hypothesis": "The volume contour is an important missing profile capability",
            "stages": ["10B"],
            "evidence": (
                "Transfers frame-for-frame and is audible — heard in 7 of 18 pairs and every "
                "single-side answer named the contour side. Profile-level B-vs-C 0-0-8; whole-song "
                "1-2-3. Resolved verdict NEGATIVE."
            ),
            "verdict": "NEGATIVE",
            "confidence": "STRONG",
            "why": "the isolated and whole-song results are reported separately and neither favours "
            "the contour",
        },
        {
            "id": "H4",
            "hypothesis": "Spectral/timbral information is the main missing dimension",
            "stages": ["11A", "11B"],
            "evidence": (
                "Stage 11A found it inconclusive, leaning negative: the renderer already reproduces "
                "the dominant audible spectral axis (the generator), and the descriptor named "
                "`spectral bandwidth (Hz)` flips sign between datasets (-0.4401 in 7B, +0.6338 in "
                "9D). Stage 11B confirmed the generator dominates the ablation and classified "
                + elevens_summary(composer)
                + "."
            ),
            "verdict": "NOT SUPPORTED",
            "confidence": "MODERATE",
            "why": "the axis that mattered was already expressible, and the finer descriptors are "
            "unstable predictors",
        },
        {
            "id": "H5",
            "hypothesis": "Pitch trajectory is the key missing transferable capability",
            "stages": ["13A"],
            "evidence": (
                "Reconnaissance: 46 non-static trajectories, of which only 14 are musically bounded "
                "— 32 carry ±60–96 semitone divider/pair register artifacts. Technical: transfer "
                f"{h13.get('H1_technical_transfer', {}).get('count')} of "
                f"{h13.get('H1_technical_transfer', {}).get('of')}, measurable movement beyond "
                f"static pitch {h13.get('H2_beyond_static_pitch', {}).get('count')} of "
                f"{h13.get('H2_beyond_static_pitch', {}).get('of')}, reference improvement "
                f"{h13.get('H4_reproduces_the_reference', {}).get('count')} of "
                f"{h13.get('H4_reproduces_the_reference', {}).get('of')}. Perceptual: the isolated "
                f"pairs preferred the trajectory {_pair_text(a13, 'C_vs_A', 1)} and heard it as "
                f"`modulated` against a `clean tone`; the phrase pairs preferred the static side "
                f"{_pair_text(a13, 'C_vs_A', 2)}; and the profile's own trajectory lost the donor "
                f"control {_pair_text(a13, 'C_vs_D')}."
            ),
            "verdict": "ACOUSTICALLY SUPPORTED, PERCEPTUALLY NOT SUPPORTED",
            "confidence": "STRONG",
            "why": "pitch movement is audible and transferable, but archaeology-derived pitch movement "
            "is not useful: it is rejected in musical context and is not distinguishable from a "
            "trajectory taken from another profile",
        },
    ]


# ---------------------------------------------------------------------------
# Parts 4, 6 — the direct-transfer model, reconciled with the representation loss
# ---------------------------------------------------------------------------
def transfer_model(composer: Mapping[str, Any], listening: Mapping[str, Any]) -> Dict[str, Any]:
    """The six questions, and the reconciliation with Stage 9E's representation finding."""
    nine_e = composer.get("stage9e", {})
    a10 = listening.get("stage10a", {})
    a12 = listening.get("stage12a", {})
    a13 = listening.get("stage13a", {})
    return {
        "reconciliation": {
            "finding": (
                f"Stage 9E: {nine_e.get('leaf_paths')} documented leaf paths, "
                f"{nine_e.get('read_by_binding')} read by the binding, first divergence at "
                f"`{nine_e.get('first_divergence')}`, {nine_e.get('redundant_profiles')} of 61 "
                "profiles collapsing into "
                f"{nine_e.get('duplicate_groups')} representation-duplicate audio groups."
            ),
            "why_it_matters": (
                "It proved the library's *audible size* is set by six scalars rather than by the 232 "
                "paths the archaeology measured — a real, measured architectural fact, and the "
                "reason whole families of profiles render identically."
            ),
            "reconciled_with": (
                "Later stages repaired parts of that loss deliberately and measured the result. "
                "Volume contour (10B) and pitch trajectory (13A) are exactly the information Stage "
                "9E said was discarded: both were transferred, both reached the audio, and neither "
                "survived a listening comparison. Decoration (12A) kept the Composer's tuning and "
                "still lost to the Composer's plain sound."
            ),
            "conclusion": (
                "Representation loss was real. Fixing representation loss is not itself evidence "
                "that the recovered information is desirable in a new composition."
            ),
        },
        "questions": [
            {
                "question": "1. Does the profile contain transferable information?",
                "answer": "YES",
                "evidence": "a profile is self-sufficient and renders without the trace (Stages 3-4); "
                "8 of 8 pitch trajectories transferred frame-exactly; the contour transferred "
                "frame-for-frame (10B).",
            },
            {
                "question": "2. Is that information independent of the original musical context?",
                "answer": "NOT ESTABLISHED — the evidence points the other way",
                "evidence": "the same trajectory that was preferred on an isolated note was rejected "
                "on the same note inside a phrase: "
                f"{_pair_text(a13, 'C_vs_A', 1)} isolated versus {_pair_text(a13, 'C_vs_A', 2)} in "
                "a phrase, where the listener called it 'not harmonized' and 'broken'.",
            },
            {
                "question": "3. Does transferring it improve new music?",
                "answer": "NO",
                "evidence": "9D 5-0 to the Composer's defaults; 10A re-binding down "
                f"{a10.get('primary', {}).get('new')}-{a10.get('primary', {}).get('other')} with a "
                "default-winning control; 10B whole-song 1-2-3; 12A decoration down "
                f"{_pair_text(a12, 'C_vs_A')}.",
            },
            {
                "question": "4. Does it preserve musical character?",
                "answer": "LESS WELL THAN THE COMPOSER'S OWN INSTRUMENTS",
                "evidence": "replacement overwrites the character-derived envelope and clock (9E L1); "
                "the listener's own words were 'clean', 'harmonized' and 'typical Atari tone' for the "
                "Composer side.",
            },
            {
                "question": "5. Does the listener prefer it?",
                "answer": "NO — in every whole-song comparison",
                "evidence": "9D 0-5-1, 10A, 10B 1-2-3, 12A, 13A phrase 1-3. The only wins for a "
                "profile-derived feature are the isolated pitch trials and one 10B song pair.",
            },
            {
                "question": "6. Is the benefit reproducible?",
                "answer": "THERE IS NO BENEFIT TO REPRODUCE",
                "evidence": "what replicates is the failure: independent listening experiments across "
                "five stages converge on the same direction, which is itself a reproducible result.",
            },
        ],
        "verdict": "DIRECT TRANSFER NOT SUPPORTED",
    }


# ---------------------------------------------------------------------------
# Part 7 — the context-dependence hypothesis
# ---------------------------------------------------------------------------
def context_dependence(listening: Mapping[str, Any]) -> Dict[str, Any]:
    """Is the measured behaviour a property of the sound, or of its musical context?"""
    a13 = listening.get("stage13a", {})
    return {
        "hypothesis": (
            "Many measured properties of a historical sound are not independent instrument "
            "characteristics but properties of the interaction between a timbre, pitch, melody, "
            "rhythm, envelope and musical context."
        ),
        "classification": "SUPPORTED",
        "confidence": "STRONG",
        "evidence": [
            {
                "observation": "The same pitch trajectory, applied to the same note, is preferred on "
                "its own and rejected inside a phrase.",
                "measurement": f"isolated {_pair_text(a13, 'C_vs_A', 1)} for the trajectory; phrase "
                f"{_pair_text(a13, 'C_vs_A', 2)}",
                "source": "Stage 13A listening sheet, both levels",
            },
            {
                "observation": "A trajectory taken from a different profile performs at least as "
                "well as the profile's own.",
                "measurement": f"profile-vs-donor {_pair_text(a13, 'C_vs_D')}",
                "source": "Stage 13A donor control",
            },
            {
                "observation": "Profiles cluster by generator family rather than by anything "
                "musical, and the clusters are what the listener hears.",
                "measurement": "9D clean vs noisy families disjoint; same_generator vs similarity "
                "rho -0.5993",
                "source": "Stage 9D correlations",
            },
            {
                "observation": "Percussive behaviour, 'repetition' and 'faster' are properties of the "
                "arrangement, not of any field the renderer reads.",
                "measurement": "7B 'repetition' 11 comments; the profile's timing series is never read",
                "source": "Stage 7B vocabulary; Stage 9E field census",
            },
        ],
        "not_claimed": (
            "This is not proof. It is the best-supported explanation of five negative transfer "
            "results, and it is called SUPPORTED only because a direct, controlled contrast "
            "(isolated versus phrase, profile versus donor) points at the context rather than at the "
            "profile."
        ),
    }


# ---------------------------------------------------------------------------
# Parts 8-9 — profile transfer versus sound-design knowledge
# ---------------------------------------------------------------------------
def knowledge_base_assessment(composer: Mapping[str, Any]) -> Dict[str, Any]:
    """Is there enough evidence to convert the producer from transfer into knowledge?"""
    nine_e = composer.get("stage9e", {})
    return {
        "question": (
            "Does the evidence justify converting Sound Archaeology from a profile-transfer system "
            "into a sound-design knowledge system?"
        ),
        "evidence_for": [
            "The generator family is the one relationship that replicates across independent ratings "
            "and stages: 7B and 9D both put it first, and 9D measured the clean and noisy families "
            "as disjoint (same_generator vs similarity rho -0.5993).",
            "The listener's own vocabulary (lead_tonal, percussive_noisy, clean, loud) is a real, "
            "repeated description of that axis.",
            "The corpus supplies measurable configuration conventions: every VOICE profile is AUDCTL "
            "$00, every PAIR profile is $50, and the audit classified 22 PLAYABLE plus 39 "
            "PLAYABLE_WITH_LIMITATION of 67.",
            "Percussion <-> noise and lead/bass <-> tone are cross-checked by the corpus itself: the "
            "Composer's own character map already encodes the same pairing.",
        ],
        "evidence_against": [
            f"{nine_e.get('redundant_profiles')} of 61 renderable profiles are audio-duplicates, so "
            "the corpus is far smaller than its file count suggests.",
            "The Stage 13A context contrast shows a measured property can reverse between isolated "
            "and musical use, which is fatal to a rule that says 'this feature means this'.",
            "The corpus carries no semantic labels: no field says a sound is a kick, a snare or a "
            "bass, and 9E's finding is precisely that the musical meaning was not recorded.",
            "The one descriptor that looked like a general rule (spectral bandwidth vs usefulness) "
            "flips sign between the two datasets (-0.4401 in 7B, +0.6338 in 9D).",
            "Every perceptual datapoint in the project comes from one listener in a handful of "
            "sessions.",
        ],
        "answer": (
            "NOT YET. The generator-family relationship is real, but the Composer's own "
            "character-to-distortion map already encodes it, so a knowledge base built on today's "
            "evidence would mostly restate an existing production rule. Everything else the corpus "
            "measures is context-bound and unlabelled."
        ),
        "classification": "PLAUSIBLE, NOT SUPPORTED",
        "gate_to_revisit": [
            "semantic labelling of a sample of segments (what a human says the sound *is*), not a new "
            "metric",
            "evidence that a measured feature predicts a labelled category across independent songs",
            "a second listener, so a rule is not one person's vocabulary",
        ],
    }


# ---------------------------------------------------------------------------
# Parts 12-13 — the architectural options
# ---------------------------------------------------------------------------
def option_assessment() -> List[Dict[str, Any]]:
    """Four directions, scored qualitatively against the brief's nine criteria."""
    return [
        {
            "option": "A",
            "name": "Continue direct SoundProfile transfer",
            "statement": "archaeology -> playable profile -> new composition",
            "criteria": {
                "empirical_support": "NONE",
                "perceptual_evidence": "NONE",
                "technical_complexity": "MODERATE",
                "risk_of_overfitting": "STRONG",
                "preservation_of_musical_intent": "WEAK",
                "compatibility_with_composer": "MODERATE",
                "value_of_existing_investment": "MODERATE",
                "reproducibility": "STRONG",
                "future_research_potential": "WEAK",
            },
            "why": "five independent listening experiments, including byte-identical and donor "
            "controls, put the profile-derived side last in every whole-song comparison.",
        },
        {
            "option": "B",
            "name": "Stop direct transfer; use the archaeology as a sound-design knowledge base",
            "statement": "archaeology -> rules / priors -> Composer",
            "criteria": {
                "empirical_support": "WEAK",
                "perceptual_evidence": "MODERATE",
                "technical_complexity": "MODERATE",
                "risk_of_overfitting": "STRONG",
                "preservation_of_musical_intent": "MODERATE",
                "compatibility_with_composer": "STRONG",
                "value_of_existing_investment": "MODERATE",
                "reproducibility": "MODERATE",
                "future_research_potential": "MODERATE",
            },
            "why": "the one relationship with real support (generator family) is already a rule in the "
            "Composer's character map, and the corpus has no semantic labels to build more from.",
        },
        {
            "option": "C",
            "name": "Keep the profiles as a validated reference / research artifact",
            "statement": "archaeology -> SoundProfile library -> analysis, visualisation, research",
            "criteria": {
                "empirical_support": "STRONG",
                "perceptual_evidence": "MODERATE",
                "technical_complexity": "NONE",
                "risk_of_overfitting": "NONE",
                "preservation_of_musical_intent": "STRONG",
                "compatibility_with_composer": "STRONG",
                "value_of_existing_investment": "STRONG",
                "reproducibility": "STRONG",
                "future_research_potential": "MODERATE",
            },
            "why": "the extraction, fingerprinting, audit and rendering pipeline all work and are "
            "reproducible; it is the *transfer* that failed, not the archaeology.",
        },
        {
            "option": "D",
            "name": "Abandon the SoundProfile direction entirely",
            "statement": "stop the line",
            "criteria": {
                "empirical_support": "WEAK",
                "perceptual_evidence": "MODERATE",
                "technical_complexity": "NONE",
                "risk_of_overfitting": "NONE",
                "preservation_of_musical_intent": "STRONG",
                "compatibility_with_composer": "STRONG",
                "value_of_existing_investment": "NONE",
                "reproducibility": "STRONG",
                "future_research_potential": "WEAK",
            },
            "why": "it discards a working, reproducible measurement pipeline whose only failure is the "
            "last mile; A's failure is not a reason to burn the dataset.",
        },
    ]


# ---------------------------------------------------------------------------
# Parts 10-11 — what worked, and what failed
# ---------------------------------------------------------------------------
def what_worked() -> List[Dict[str, str]]:
    """Research infrastructure that succeeded, kept apart from perceptual transfer."""
    return [
        {"item": "POKEY trace extraction and register-level analysis", "kind": "infrastructure",
         "evidence": "SAP corpus -> traces -> segments, reproducible across stages"},
        {"item": "deterministic SoundProfile generation", "kind": "infrastructure",
         "evidence": "schema 2.0 with a content fingerprint; byte-identical rebuilds"},
        {"item": "PlayableSoundProfile + registry as a portable artifact", "kind": "infrastructure",
         "evidence": "self-sufficient documents that render without the corpus"},
        {"item": "playability audit", "kind": "infrastructure",
         "evidence": "22 PLAYABLE + 39 PLAYABLE_WITH_LIMITATION + 6 MEASUREMENT_ONLY of 67, with "
         "per-profile reasons"},
        {"item": "renderer / binding diagnostics", "kind": "infrastructure",
         "evidence": "9E's field census (13 of 232 read) and the frame-column perturbation proof"},
        {"item": "identifying and excluding pitch register artifacts", "kind": "finding",
         "evidence": "32 of 46 non-static trajectories leave a one-octave musical bound"},
        {"item": "the generator family as the audible spectral axis", "kind": "finding",
         "evidence": "7B and 9D agree; the 9D families are disjoint; 11B shows the generator "
         "dominates the ablation"},
        {"item": "exact, deterministic transfer of a measured contour and trajectory into the frame "
                 "stream", "kind": "finding",
         "evidence": "10B frame-for-frame volume; 13A 8 of 8 AUDF-only"},
        {"item": "the listener's ratings are stable enough to compare groups", "kind": "finding",
         "evidence": "9D ICC(1,1) 0.73-0.92 on the same sound presented twice"},
    ]


def what_failed() -> List[Dict[str, str]]:
    """The negative experiments, recorded so the knowledge is not lost."""
    return [
        {"attempt": "Direct profile replacement (the binding as it stands)", "stages": "9D",
         "result": "the Composer's own instruments won 5-0 on six songs, unanimously on all three "
         "questions"},
        {"attempt": "Evidence-chosen profile rebinding", "stages": "10A",
         "result": "NEW won 2 of 12 primary pairs; the control put the Composer default over the old "
         "binding 4-1"},
        {"attempt": "Volume-contour transfer", "stages": "10B",
         "result": "profile-level 0-0-8 and whole-song 1-2-3; resolved verdict NEGATIVE"},
        {"attempt": "Profile decoration (keep the Composer instrument, take the generator)",
         "stages": "12A",
         "result": "mechanically sound (H1 3/6, H2 4/6) but the listener preferred the Composer "
         "baseline, and drew no win against replacement"},
        {"attempt": "Pitch trajectory as a transferable feature", "stages": "13A",
         "result": "transferred 8/8 and audible, preferred 4-0 in isolation, but rejected 1-3 inside "
         "a phrase and beaten 1-2 by a donor trajectory from another profile"},
    ]


# ---------------------------------------------------------------------------
# Parts 14-17 — the single recommendation
# ---------------------------------------------------------------------------
def recommendation() -> Dict[str, Any]:
    """The one primary direction, with what follows and what must not."""
    return {
        "option": "C",
        "headline": "RECOMMENDATION: OPTION C",
        "statement": (
            "Keep the SoundProfile work as a validated reference and research artifact. Stop "
            "developing direct profile transfer; do not, on this evidence, convert the corpus into a "
            "sound-design rules engine."
        ),
        "why": [
            "Direct transfer is not supported in the only terms that matter: five independent "
            "listening experiments across four stages put the profile-derived side level with or "
            "behind the Composer's own sound, including two controls that could not have favoured "
            "the Composer by construction.",
            "The mechanism is not the problem: contours and trajectories transfer frame-exactly, and "
            "the representation loss diagnosed in 9E was repaired deliberately in 10B and 13A. The "
            "information is real, measured and faithfully carried — it simply does not survive the "
            "move into a new musical context.",
            "The knowledge-base alternative is attractive but unevidenced: the one replicated "
            "relationship (generator family) is already a production rule, and the corpus has no "
            "semantic labels, so a rules engine would be built on one listener's vocabulary.",
            "The archaeology itself is a genuine asset: reproducible extraction, fingerprints, a "
            "per-profile playability audit and a working renderer path.",
        ],
        "why_alternatives_weaker": {
            "A": "no empirical or perceptual support remains; continuing would mean re-running "
            "experiments that have already failed four times",
            "B": "the evidence is plausible but not sufficient; adopting it now would be choosing the "
            "more interesting project over the measured result",
            "D": "it discards a working measurement pipeline whose only failure is the last mile",
        },
        "what_happens_next": [
            "Freeze the profiles, the schemas, the fingerprints and the audit as a published "
            "reference library, with the existing reports as its documentation.",
            "Publish this synthesis as the closing record of the transfer hypothesis, so the result "
            "is not lost.",
            "If the knowledge direction is ever revisited, go through the explicit gate in "
            "`knowledge_base_assessment.gate_to_revisit`: semantic labels and a second listener "
            "first, not a rules engine first.",
        ],
        "what_must_not_happen_next": [
            "no further transfer mechanism (a new contour, trajectory, modulation or spectral "
            "channel) without evidence that was missing before",
            "no production binding change, no DSL change, no new profile field",
            "no automatic conversion of the corpus into rules, thresholds or recommendations",
            "no profile-driven default in the Composer",
            "no re-running of the completed listening experiments to look for a friendlier reading",
        ],
    }


def future_architecture_if_option_c() -> Dict[str, Any]:
    """Part 17 — the stable research artifact Option C preserves."""
    return {
        "artifact": "the SoundProfile library and its supporting records, unchanged",
        "layers": [
            {"layer": "raw POKEY traces", "status": "exists", "where": "the producer's corpus"},
            {"layer": "SoundSegment / SoundFingerprint", "status": "exists",
             "where": "producer reports/segments.jsonl and fingerprints.jsonl"},
            {"layer": "SoundProfile / PlayableSoundProfile", "status": "exists",
             "where": "schema 2.0 / 1.0 with content fingerprints"},
            {"layer": "playability audit", "status": "exists",
             "where": "producer reports/stage8c/playability_audit.json"},
            {"layer": "Composer binding", "status": "exists, experimental and off by default",
             "where": "sound_profiles/binding.py, unchanged"},
        ],
        "what_is_missing_for_a_knowledge_base": [
            "semantic labels on segments (what a sound *is*, not what it measures)",
            "a second listener, so the vocabulary is not one person's",
            "evidence that a measured feature predicts a labelled category across independent songs",
        ],
        "what_must_remain_empirical": [
            "no hand-tuned threshold presented as a finding",
            "no rule published without the measurement and the sample size behind it",
        ],
        "reproducibility": "every stage writes timestamp-free, hash-pinned reports; two runs are "
        "byte-identical",
    }


# ---------------------------------------------------------------------------
# Assembly
# ---------------------------------------------------------------------------
_INPUT_FILES = (
    "reports/stage9d/coverage.json",
    "reports/stage9d/verdict.json",
    "reports/stage9d/correlations.json",
    "reports/stage9e/pipeline_fields.json",
    "reports/stage9e/duplicate_groups.json",
    "reports/stage9e/information_loss.json",
    "reports/stage11/hypothesis_ranking.json",
    "reports/stage11/go_no_go.json",
    "reports/stage11/collapse.json",
    "reports/stage11/representation_gap.json",
    "reports/stage11/feature_classification.json",
    "reports/stage11/spectral_summary.json",
    "reports/stage11/stage10a_reevaluation.json",
    "reports/stage11/stage10b_reevaluation.json",
    "reports/stage12a/hypotheses.json",
    "reports/stage12a/summary.json",
    "reports/stage13a/reconnaissance.json",
    "reports/stage13a/selection.json",
    "reports/stage13a/hypotheses.json",
    "reports/stage13a/listening.json",
    "examples/stage12a_listening/evaluation_stage12a.csv",
    "examples/stage12a_listening/manifest.json",
    "examples/stage13a_listening/evaluation_stage13a.csv",
    "examples/stage13a_listening/manifest.json",
)


def _input_hashes(arch_root: Path) -> Dict[str, str]:
    out: Dict[str, str] = {}
    for rel in _INPUT_FILES:
        path = REPO_ROOT / rel
        if path.is_file():
            out[rel] = sha256_file(path)
    for rel in (
        "reports/stage7b/human_evaluation_summary.json",
        "reports/stage8c/playability_audit.json",
    ):
        path = Path(arch_root) / rel
        if path.is_file():
            out["archaeology/" + rel] = sha256_file(path)
    return out


def run_synthesis(
    *,
    reports_dir: Path = DEFAULT_REPORTS_DIR,
    arch_root: Path = DEFAULT_ARCHAEOLOGY_DIR,
    stage12a_package: Path = DEFAULT_STAGE12A_PACKAGE,
    stage13a_package: Path = DEFAULT_STAGE13A_PACKAGE,
) -> Dict[str, Any]:
    """Assemble the whole synthesis. Deterministic; nothing is written here."""
    arch = collect_archaeology(arch_root)
    composer = collect_composer(reports_dir)
    listening = collect_listening(
        reports_dir, stage12a_package=stage12a_package, stage13a_package=stage13a_package
    )
    matrix = evidence_matrix(composer, listening)
    hypotheses = hypothesis_verdicts(composer, listening)
    model = transfer_model(composer, listening)
    context = context_dependence(listening)
    knowledge = knowledge_base_assessment(composer)
    options = option_assessment()
    recommendation_block = recommendation()

    negatives = [row["capability"] for row in matrix if row["D_perceptually_useful"] == "NEGATIVE"]
    positives = [row["capability"] for row in matrix if row["D_perceptually_useful"] == "POSITIVE"]
    return {
        "analysis_version": ANALYSIS_VERSION,
        "experiment": "stage14",
        "archaeology": arch,
        "composer": composer,
        "listening": listening,
        "evidence_matrix": matrix,
        "hypothesis_verdicts": hypotheses,
        "transfer_model": model,
        "context_dependence": context,
        "knowledge_base_assessment": knowledge,
        "option_assessment": options,
        "what_worked": what_worked(),
        "what_failed": what_failed(),
        "recommendation": recommendation_block,
        "future_architecture": future_architecture_if_option_c(),
        "summary": {
            "capabilities_judged": len(matrix),
            "perceptually_useful_negative": negatives,
            "perceptually_useful_positive": positives,
            "hypotheses": {
                row["id"]: row["verdict"] for row in hypotheses
            },
            "direct_transfer": model["verdict"],
            "context_dependence": context["classification"],
            "knowledge_base": knowledge["classification"],
            "recommendation": recommendation_block["headline"],
            "listening_trials_analysed": {
                "stage10a": listening.get("stage10a", {}).get("answered"),
                "stage10b": listening.get("stage10b", {}).get("answered"),
                "stage12a": listening.get("stage12a", {}).get("answered"),
                "stage13a": listening.get("stage13a", {}).get("answered"),
            },
        },
        "inputs": _input_hashes(arch_root),
    }


def write_synthesis(
    bundle: Mapping[str, Any],
    *,
    stage14_dir: Path = DEFAULT_STAGE14_DIR,
    docs_dir: Path = DEFAULT_DOCS_DIR,
) -> Dict[str, Path]:
    """Write the seven machine records and the document. Deterministic byte-for-byte."""
    stage14_dir = Path(stage14_dir)
    docs_dir = Path(docs_dir)
    stage14_dir.mkdir(parents=True, exist_ok=True)
    docs_dir.mkdir(parents=True, exist_ok=True)

    written: Dict[str, Path] = {}
    for name, payload in (
        ("evidence_matrix.json", bundle["evidence_matrix"]),
        ("hypothesis_verdicts.json", bundle["hypothesis_verdicts"]),
        ("transfer_model.json", bundle["transfer_model"]),
        ("context_dependence.json", bundle["context_dependence"]),
        ("knowledge_base_assessment.json", bundle["knowledge_base_assessment"]),
        ("option_assessment.json", bundle["option_assessment"]),
        ("summary.json", bundle["summary"]),
    ):
        path = stage14_dir / name
        path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        written[name] = path

    doc = docs_dir / "stage14_final_synthesis.md"
    doc.write_text(render_report(bundle), encoding="utf-8", newline="\n")
    written["stage14_final_synthesis.md"] = doc
    return written


# ---------------------------------------------------------------------------
# The document
# ---------------------------------------------------------------------------
def _md_table(header: Sequence[str], rows: Sequence[Sequence[Any]]) -> str:
    lines = ["| " + " | ".join(header) + " |", "| " + " | ".join([":---"] * len(header)) + " |"]
    for row in rows:
        lines.append("| " + " | ".join("—" if cell is None else str(cell) for cell in row) + " |")
    return "\n".join(lines)


def render_report(bundle: Mapping[str, Any]) -> str:
    """`docs/stage14_final_synthesis.md`, in the seventeen-section structure the brief fixes."""
    summary = bundle["summary"]
    matrix = bundle["evidence_matrix"]
    hypotheses = bundle["hypothesis_verdicts"]
    model = bundle["transfer_model"]
    context = bundle["context_dependence"]
    knowledge = bundle["knowledge_base_assessment"]
    options = bundle["option_assessment"]
    rec = bundle["recommendation"]
    future = bundle["future_architecture"]
    lines: List[str] = []
    add = lines.append

    add("# Stage 14 — final evidence synthesis and SoundProfile go/no-go")
    add("")
    add(f"**{rec['headline']}**")
    add("")
    add(
        "An analysis-only close of the transfer hypothesis. Nothing is rendered, nothing is changed, "
        "and no new listening is asked for; the evidence is Stages 7B through 13A, including the "
        "Stage 12A and 13A answer sheets, which are decoded here for the first time."
    )
    add("")

    add("## 1. Executive conclusion")
    add("")
    add(
        "**Inference.** Archaeology-derived SoundProfiles contain real, correctly measured "
        "information, and that information can be transferred into the Composer's renderer "
        "frame-exactly. It is **not** context-independent enough to improve a new composition: in "
        "five independent listening experiments across four stages the profile-derived side was "
        "level with or behind the Composer's own sound, and the two newest experiments used controls "
        "(a byte-identical baseline, a donor trajectory from another profile) that could not have "
        "favoured the Composer by construction."
    )
    add("")
    add(
        "This is not a claim that the profiles are worthless, that the renderer is inadequate, or "
        "that the representation is wrong. It is the narrower, supported claim that the measured "
        "properties are largely properties of the *interaction* the archaeology recorded, not "
        "portable instrument characteristics."
    )
    add("")
    add("| | |")
    add("| :--- | :--- |")
    add(f"| capability rows judged | {summary['capabilities_judged']} |")
    add(
        "| judged NEGATIVE on perceptual usefulness | "
        + f"{len(summary['perceptually_useful_negative'])} — "
        + ", ".join(summary["perceptually_useful_negative"])
        + " |"
    )
    add(
        "| judged POSITIVE on perceptual usefulness | "
        + (", ".join(summary["perceptually_useful_positive"]) or "none")
        + " |"
    )
    add(f"| direct profile transfer | **{summary['direct_transfer']}** |")
    add(f"| context dependence | **{summary['context_dependence']}** |")
    add(f"| sound-design knowledge base | **{summary['knowledge_base']}** |")
    add(f"| recommendation | **{summary['recommendation']}** |")
    add("")

    add("## 2. Evidence base")
    add("")
    add(
        "**Observed.** Every artefact below was read directly rather than summarised, and hashed so "
        "the synthesis is reproducible:"
    )
    add("")
    add("```json")
    add(json.dumps(bundle["inputs"], indent=2, sort_keys=True))
    add("```")
    add("")
    nine_d = bundle["composer"].get("stage9d", {})
    nine_e = bundle["composer"].get("stage9e", {})
    l10a = bundle["listening"].get("stage10a", {})
    l10b = bundle["listening"].get("stage10b", {})
    l12 = bundle["listening"].get("stage12a", {})
    l13 = bundle["listening"].get("stage13a", {})
    add(
        _md_table(
            ("stage", "what it contributed", "trials", "key measurement"),
            (
                ("7B", "candidate usefulness, distinctiveness, fidelity, vocabulary",
                 f"{bundle['archaeology'].get('stage7b', {}).get('candidates')} candidates",
                 f"fidelity vs similarity rho "
                 f"{bundle['archaeology'].get('stage7b', {}).get('fidelity_vs_similarity_rho')}"),
                ("9D", "profile rendering, profile- and song-level listening",
                 "60 ratings, 30 A/B, 6 songs",
                 f"{nine_d.get('distinct_audio_signals')} distinct signals of "
                 f"{nine_d.get('profiles')}"),
                ("9E", "representation gap", "none",
                 f"{nine_e.get('read_by_binding')} of {nine_e.get('leaf_paths')} paths read, first "
                 f"divergence {nine_e.get('first_divergence')}"),
                ("10A", "evidence-chosen re-binding", f"{l10a.get('answered')} pairs",
                 f"NEW {l10a.get('primary', {}).get('new')} of {l10a.get('primary', {}).get('n')}"),
                ("10B", "volume contour", f"{l10b.get('answered')} pairs",
                 f"profile {l10b.get('profile_level_b_vs_c', {}).get('c')}-"
                 f"{l10b.get('profile_level_b_vs_c', {}).get('other')}-"
                 f"{l10b.get('profile_level_b_vs_c', {}).get('none')}, song "
                 f"{l10b.get('song_level_b_vs_c', {}).get('c')}-"
                 f"{l10b.get('song_level_b_vs_c', {}).get('other')}-"
                 f"{l10b.get('song_level_b_vs_c', {}).get('none')}"),
                ("11", "synthesis and controlled spectral ablation", "none",
                 "generator dominates the ablation; 5 PARTIALLY_EXPRESSIBLE, 3 UNTESTED"),
                ("12A", "decoration versus replacement", f"{l12.get('answered')} pairs",
                 f"C-vs-A {_pair_text(l12, 'C_vs_A')}, C-vs-B {_pair_text(l12, 'C_vs_B')}"),
                ("13A", "pitch trajectory", f"{l13.get('answered')} pairs",
                 f"isolated {_pair_text(l13, 'C_vs_A', 1)}, phrase {_pair_text(l13, 'C_vs_A', 2)}, "
                 f"donor {_pair_text(l13, 'C_vs_D')}"),
            ),
        )
    )
    add("")

    add("## 3. Master evidence matrix")
    add("")
    add(
        "Four claims, kept apart deliberately: **A** technically representable, **B** acoustically "
        "measurable, **C** perceptually detectable, **D** perceptually useful. A capability can be "
        "A-B-C and still fail D — which is what the evidence shows."
    )
    add("")
    add(
        _md_table(
            ("capability", "A", "B", "C", "D", "evidence strength", "verdict"),
            [
                (
                    row["capability"],
                    row["A_technically_representable"],
                    row["B_acoustically_measurable"],
                    row["C_perceptually_detectable"],
                    row["D_perceptually_useful"],
                    row["evidence_strength"],
                    row["verdict"],
                )
                for row in matrix
            ],
        )
    )
    add("")
    add("**Observed.** The number behind each row:")
    add("")
    for row in matrix:
        add(f"* **{row['capability']}** — {row['note']} _({row['provenance']})_")
    add("")

    by_id = {row["id"]: row for row in hypotheses}

    add("## 4. Direct profile transfer verdict")
    add("")
    add(f"**{model['verdict']}.**")
    add("")
    add(
        "**Observed — the representation finding, and why it matters.** "
        + model["reconciliation"]["finding"]
        + " " + model["reconciliation"]["why_it_matters"]
    )
    add("")
    add("**Observed — reconciled with the later experiments.** " + model["reconciliation"]["reconciled_with"])
    add("")
    add("**Inference.** " + model["reconciliation"]["conclusion"])
    add("")
    add(
        _md_table(
            ("question", "answer", "evidence"),
            [(q["question"], q["answer"], q["evidence"]) for q in model["questions"]],
        )
    )
    add("")

    for number, heading, key in (
        (5, "Profile replacement verdict", "H1"),
        (6, "Profile decoration verdict", "H2"),
        (7, "Volume contour verdict", "H3"),
        (8, "Spectral/timbral verdict", "H4"),
        (9, "Pitch trajectory verdict", "H5"),
    ):
        row = by_id[key]
        add(f"## {number}. {heading}")
        add("")
        add(f"**{row['hypothesis']}** — stages {', '.join(row['stages'])}.")
        add("")
        add(f"**Observed.** {row['evidence']}")
        add("")
        why = row["why"]
        add(
            f"**Inference.** `{row['verdict']}` (confidence: {row['confidence']}). "
            f"{why[:1].upper()}{why[1:]}."
        )
        add("")
    add("")

    add("## 10. Context-dependence assessment")
    add("")
    add(f"**Hypothesis.** {context['hypothesis']}")
    add("")
    add(f"**Classification: `{context['classification']}`** (confidence: {context['confidence']}).")
    add("")
    add(
        _md_table(
            ("observation", "measurement", "source"),
            [(e["observation"], e["measurement"], e["source"]) for e in context["evidence"]],
        )
    )
    add("")
    add(f"**Experimental choice / caveat.** {context['not_claimed']}")
    add("")

    add("## 11. What worked")
    add("")
    add(
        "**Observed.** Research *infrastructure* that succeeded, kept apart from perceptual transfer:"
    )
    add("")
    add(
        _md_table(
            ("item", "kind", "evidence"),
            [(w["item"], w["kind"], w["evidence"]) for w in bundle["what_worked"]],
        )
    )
    add("")
    add(
        "**Inference.** The project built a working measurement and publication pipeline. What it "
        "did not build is a transfer that a listener prefers — those are different claims and only "
        "the first is established."
    )
    add("")

    add("## 12. What failed")
    add("")
    add(
        "**Observed.** Recorded here so the knowledge is not lost. Every one of these is a negative "
        "result that a later stage must not quietly re-run as if it were untested."
    )
    add("")
    add(
        _md_table(
            ("attempt", "stage", "result"),
            [(f["attempt"], f["stages"], f["result"]) for f in bundle["what_failed"]],
        )
    )
    add("")

    add("## 13. SoundProfile vs sound-design knowledge")
    add("")
    add(f"**Question.** {knowledge['question']}")
    add("")
    add("**Observed — evidence for.**")
    add("")
    for item in knowledge["evidence_for"]:
        add(f"* {item}")
    add("")
    add("**Observed — evidence against.**")
    add("")
    for item in knowledge["evidence_against"]:
        add(f"* {item}")
    add("")
    add(f"**Inference.** {knowledge['answer']}")
    add("")
    add(f"**Classification: `{knowledge['classification']}`.**")
    add("")
    add("**The gate that would have to be passed before this is revisited:**")
    add("")
    for item in knowledge["gate_to_revisit"]:
        add(f"* {item}")
    add("")

    add("## 14. Architectural options")
    add("")
    add(
        "**Observed.** Scored qualitatively against the brief's nine criteria; no weighted total is "
        "computed, because the weights would be arbitrary."
    )
    add("")
    add(
        _md_table(
            ("option", "direction", "empirical", "perceptual", "complexity", "overfit risk",
             "musical intent", "composer fit", "investment", "reproducible", "future research"),
            [
                (
                    o["option"], o["name"],
                    o["criteria"]["empirical_support"], o["criteria"]["perceptual_evidence"],
                    o["criteria"]["technical_complexity"], o["criteria"]["risk_of_overfitting"],
                    o["criteria"]["preservation_of_musical_intent"],
                    o["criteria"]["compatibility_with_composer"],
                    o["criteria"]["value_of_existing_investment"], o["criteria"]["reproducibility"],
                    o["criteria"]["future_research_potential"],
                )
                for o in options
            ],
        )
    )
    add("")
    for option in options:
        add(f"* **{option['option']} — {option['name']}** (`{option['statement']}`): {option['why']}")
    add("")

    add("## 15. Final recommendation")
    add("")
    add(f"> **{rec['headline']}**")
    add("")
    add(rec["statement"])
    add("")
    add("**Why the evidence supports it.**")
    add("")
    for item in rec["why"]:
        add(f"* {item}")
    add("")
    add("**Why the alternatives are weaker.**")
    add("")
    for key, item in rec["why_alternatives_weaker"].items():
        add(f"* **{key}** — {item}")
    add("")

    add("## 16. What happens next")
    add("")
    for item in rec["what_happens_next"]:
        add(f"* {item}")
    add("")
    add("**The research artifact this preserves, and what it still lacks:**")
    add("")
    add(
        _md_table(
            ("layer", "status", "where"),
            [(layer["layer"], layer["status"], layer["where"]) for layer in future["layers"]],
        )
    )
    add("")
    add("Still missing before a knowledge base could be justified:")
    add("")
    for item in future["what_is_missing_for_a_knowledge_base"]:
        add(f"* {item}")
    add("")

    add("## 17. Explicit non-goals")
    add("")
    for item in rec["what_must_not_happen_next"]:
        add(f"* {item}")
    add("")
    add(
        "Also explicitly out of scope for this stage: implementing any option, changing any schema, "
        "composer or renderer file, and running another listening experiment."
    )
    add("")

    add("### Reproducibility")
    add("")
    add(
        "This document and the seven `reports/stage14/*.json` records are a pure function of the "
        "artefacts hashed in §2. There is no timestamp, no sampling and no dependence on directory "
        "iteration order; two consecutive runs are byte-identical, and no existing artefact is "
        "modified by running or reading this stage."
    )
    add("")
    return "\n".join(lines) + "\n"

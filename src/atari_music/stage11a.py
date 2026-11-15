"""Stage 11A — perceptual synthesis.

Reads the *existing* evidence (Stages 7B, 8C, 9D, 9E, 10A, 10B) and answers, without
running or changing any renderer, where the perceptual character of a POKEY sound is lost
in the current pipeline. It is analysis-only: it opens published artefacts, measures
nothing new by listening, and writes only its own ``reports/stage11/`` and one document.

The three kinds of statement every Stage 11 artefact keeps apart are **observed** (a value
taken from a published artefact, with its path), **inference** (what follows) and
**experimental choice** (what this stage decided, which no measurement forces).
"""

from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

REPO_ROOT = Path(__file__).resolve().parents[2]

#: The published profile bank the composer consumes (read-only).
DEFAULT_BANK_DIR = REPO_ROOT / "tests" / "data" / "sound_profiles" / "bank"
#: Where the composer stages publish their machine record (read-only inputs here).
DEFAULT_REPORTS_DIR = REPO_ROOT / "reports"
#: Where Stage 11A writes its own record.
DEFAULT_STAGE11_DIR = DEFAULT_REPORTS_DIR / "stage11"
#: The two listening packages whose answer sheets are re-analysed (read-only).
DEFAULT_STAGE10A_PACKAGE = REPO_ROOT / "examples" / "sound_profile_rebinding_10a"
DEFAULT_STAGE10B_PACKAGE = REPO_ROOT / "examples" / "sound_profile_volume_contour_10b"
#: Where the document is written.
DEFAULT_DOCS_DIR = REPO_ROOT / "docs"
#: The producer repository, read for the perceptual (7B) and playability (8C) evidence.
DEFAULT_ARCHAEOLOGY_DIR = Path(r"C:\Users\grzes\Documents\Projects\pokey-sound-architecture")

ANALYSIS_VERSION = "stage11a/1"


class Stage11AError(RuntimeError):
    """A required published artefact is missing or malformed."""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _read_json(path: Path) -> Any:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError as error:
        raise Stage11AError(f"missing artefact: {path}") from error
    except json.JSONDecodeError as error:
        raise Stage11AError(f"malformed JSON: {path}: {error}") from error


def sha256_file(path: Path) -> str:
    """SHA-256 of a file's bytes, so a run can be tied to the exact inputs it read."""
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _read_answer_sheet(path: Path) -> List[Dict[str, str]]:
    path = Path(path)
    if not path.is_file():
        return []
    with path.open(encoding="utf-8", newline="") as handle:
        return [row for row in csv.DictReader(handle) if (row.get("better_overall") or "").strip()]


def _dumps(payload: Any) -> str:
    return json.dumps(payload, indent=2, sort_keys=True) + "\n"


# ---------------------------------------------------------------------------
# A3 — the renderer / representation gap (verified against Stage 9E's own record)
# ---------------------------------------------------------------------------
def representation_gap(reports_dir: Path = DEFAULT_REPORTS_DIR) -> Dict[str, Any]:
    """Which profile fields are consumed, ignored, player-only or unrepresentable.

    Observed: read from ``reports/stage9e/pipeline_fields.json`` (the field census) and
    ``reports/stage9e/information_loss.json`` (the boundary measurements). Nothing is
    re-derived here; the values are the published ones.
    """
    reports_dir = Path(reports_dir)
    fields_doc = _read_json(reports_dir / "stage9e" / "pipeline_fields.json")
    loss_doc = _read_json(reports_dir / "stage9e" / "information_loss.json")

    propagation = fields_doc["propagation"]
    fields = propagation["paths"]
    by_status: Dict[str, List[str]] = {}
    for field in fields:
        by_status.setdefault(field["status"], []).append(field["path"])

    counts = {status: len(paths) for status, paths in by_status.items()}
    loss_points = {point["id"]: point for point in loss_doc["loss"]["loss_points"]}

    return {
        "source": "reports/stage9e/pipeline_fields.json, reports/stage9e/information_loss.json",
        "leaf_paths_total": propagation["path_count"],
        "counts": counts,
        "sections": propagation["sections"],
        "read_by_binding_paths": sorted(propagation["read_paths"]),
        "read_by_binding_count": len(propagation["read_paths"]),
        "used_paths": sorted(by_status.get("USED", [])),
        "ignored_paths": sorted(by_status.get("IGNORED", [])),
        "player_only_paths": sorted(by_status.get("PLAYER_ONLY", [])),
        "unrepresentable_paths": sorted(by_status.get("UNREPRESENTABLE", [])),
        "loss_points": {
            "l1_first_loss": {
                "instance": loss_points["L1"]["module"],
                "boundary": loss_points["L1"]["stage"],
                "classified_as": loss_points["L1"]["classified_as"],
                "measurement": loss_points["L1"]["measurement"],
                "what_is_lost": loss_points["L1"]["what_is_lost"],
            },
            "l2_renderer": {
                "instance": loss_points["L2"]["module"],
                "classification": loss_points["L2"]["classified_as"],
                "measurement": loss_points["L2"]["measurement"],
            },
            "l3_no_gap": {
                "instance": loss_points["L3"]["module"],
                "classification": loss_points["L3"]["classified_as"],
                "measurement": loss_points["L3"]["measurement"],
            },
            "l4_out_of_repository": {
                "instance": loss_points["L4"]["module"],
                "classification": loss_points["L4"]["classified_as"],
                "measurement": loss_points["L4"]["measurement"],
            },
        },
        "gesture_lost_by_binding": loss_doc["loss"]["gesture_lost"],
        "first_information_loss": (
            "PlayableSoundProfile -> bound POKEY IR "
            "(sound_profiles/binding.py:_rebuild_song)"
        ),
    }


# ---------------------------------------------------------------------------
# A4 — the 61 -> 37 collapse
# ---------------------------------------------------------------------------
def collapse(reports_dir: Path = DEFAULT_REPORTS_DIR) -> Dict[str, Any]:
    """Why 61 renderable profiles produce only 37 distinct audio signals.

    Observed: ``reports/stage9e/duplicate_groups.json`` classifies every duplicate group;
    ``reports/stage9d/coverage.json`` records the same 37 signals and 24 redundant profiles
    measured from the audio alone. The two agree, which is the point.
    """
    reports_dir = Path(reports_dir)
    dup = _read_json(reports_dir / "stage9e" / "duplicate_groups.json")
    coverage = _read_json(reports_dir / "stage9d" / "coverage.json")

    groups = dup["groups"]
    classification_counts: Dict[str, int] = {}
    first_divergence_counts: Dict[str, int] = {}
    for group in groups:
        classification_counts[group["classification"]] = (
            classification_counts.get(group["classification"], 0) + 1
        )
        first_divergence_counts[group["first_divergence"]] = (
            first_divergence_counts.get(group["first_divergence"], 0) + 1
        )

    return {
        "source": "reports/stage9e/duplicate_groups.json, reports/stage9d/coverage.json",
        "profiles_probed": dup["profiles_probed"],
        "distinct_audio_signals": coverage["distinct_audio_signals"],
        "redundant_profiles": dup["summary"]["redundant_profiles"],
        "profiles_in_duplicate_groups": dup["summary"]["profiles_in_groups"],
        "groups": dup["summary"]["groups"],
        "group_sizes": dup["summary"]["group_sizes"],
        "classification_counts": classification_counts,
        "first_divergence_counts": first_divergence_counts,
        "groups_explained_by_the_binding": dup["summary"]["groups_explained_by_the_binding"],
        "largest_group": dup["summary"]["largest_group"],
        "sections_that_differ": dup["summary"]["sections_that_differ"],
        "agrees_with_the_audio_only_measurement": bool(dup["reproduces_package_grouping"]),
        "conclusion": (
            "primarily representation: the groups' documents differ but their bound IR is "
            "identical, because the binding carries only distortion, four envelope numbers, "
            "AUDCTL and the pair flag. It is not a renderer limit (the audio is a pure "
            "function of the nine register bytes the binding does write) and not an "
            "archaeology limit (the documents do differ)."
        ),
    }


# ---------------------------------------------------------------------------
# A5 — re-evaluate Stage 10A from the actual listening data
# ---------------------------------------------------------------------------
def reevaluate_10a(package_dir: Path = DEFAULT_STAGE10A_PACKAGE) -> Dict[str, Any]:
    """What the Stage 10A answer sheet actually says, decoded against its private key.

    Experimental choice: the three sides are ``default`` (the composer's own instrument),
    ``old`` (the Stage 9C generator-family binding) and ``new`` (the evidence-based
    re-binding). ``default_vs_old`` is the control; the twelve ``*_vs_new`` pairs are the
    primary comparisons.
    """
    package_dir = Path(package_dir)
    manifest = _read_json(package_dir / "manifest.json")
    sheet = package_dir / "evaluation_rebinding_10a.csv"
    rows = _read_answer_sheet(sheet)
    trials = {trial["trial_id"]: trial for trial in manifest["trials"]}

    by_kind: Dict[str, Dict[str, int]] = {}
    per_trial: List[Dict[str, Any]] = []
    for row in rows:
        trial = trials.get(row["trial_id"])
        if trial is None:
            raise Stage11AError(f"Stage 10A sheet names an unknown trial: {row['trial_id']}")
        kind = trial["trial_kind"]
        sides = trial["sides"]
        choice = (row.get("better_overall") or "").strip().lower()
        chosen = sides.get(choice)
        bucket = by_kind.setdefault(kind, {"default": 0, "old": 0, "new": 0, "none": 0, "n": 0})
        bucket["none" if chosen is None else chosen] += 1
        bucket["n"] += 1
        per_trial.append(
            {
                "trial_id": row["trial_id"],
                "trial_kind": kind,
                "song": trial["song"],
                "sides": sides,
                "chosen": choice,
                "chosen_side": chosen,
                "difference_1_5": row.get("difference_1_5"),
            }
        )

    def _sum(kinds: Sequence[str]) -> Dict[str, int]:
        out = {"default": 0, "old": 0, "new": 0, "none": 0, "n": 0}
        for kind in kinds:
            for key, value in by_kind.get(kind, {}).items():
                out[key] += value
        out["other"] = out["default"] + out["old"]
        return out

    primary = _sum(("default_vs_new", "old_vs_new"))
    control = _sum(("default_vs_old",))
    return {
        "source": "examples/sound_profile_rebinding_10a/{manifest.json,evaluation_rebinding_10a.csv}",
        "sheet_sha256": sha256_file(sheet) if sheet.is_file() else None,
        "manifest_sha256": sha256_file(package_dir / "manifest.json"),
        "answered": len(rows),
        "trials": len(trials),
        "by_kind": by_kind,
        "primary": primary,
        "control": control,
        "per_trial": per_trial,
        "reading": (
            "the evidence-based re-binding (NEW) won 2 of the 12 primary pairs; the other side "
            "won 6 and 4 were ties. On the 6 control pairs the composer's DEFAULT beat the Stage "
            "9C OLD binding 4-1 (1 tie), reproducing the Stage 9C result with audio that is "
            "byte-identical to it — so a one- or two-pair difference here is inside the "
            "listener's own instability and is not evidence that re-binding helps."
        ),
    }


# ---------------------------------------------------------------------------
# A6 — re-evaluate Stage 10B from the actual listening data
# ---------------------------------------------------------------------------
def reevaluate_10b(package_dir: Path = DEFAULT_STAGE10B_PACKAGE) -> Dict[str, Any]:
    """What the Stage 10B answer sheet says, split by stimulus level.

    Observed: the profile trials and the whole-song trials are counted separately, because
    the two are not interchangeable (the profile contours are slow, the songs' are decimated
    by the frame grid). ``C`` is the side carrying the transferred contour.
    """
    package_dir = Path(package_dir)
    manifest = _read_json(package_dir / "manifest.json")
    sheet = package_dir / "evaluation_volume_contour_10b.csv"
    rows = _read_answer_sheet(sheet)
    trials = {trial["trial_id"]: trial for trial in manifest["trials"]}

    per_trial: List[Dict[str, Any]] = []
    for row in rows:
        trial = trials.get(row["trial_id"])
        if trial is None:
            raise Stage11AError(f"Stage 10B sheet names an unknown trial: {row['trial_id']}")
        sides = trial["sides"]
        choice = (row.get("better_overall") or "").strip().lower()
        chosen = sides.get(choice)
        movement = (row.get("audible_movement") or "").strip().lower()
        per_trial.append(
            {
                "trial_id": row["trial_id"],
                "trial_kind": trial["trial_kind"],
                "subject": trial.get("subjects") or trial.get("subject"),
                "chosen_side": chosen,
                "preference": "c" if chosen == "c" else ("none" if chosen is None else "other"),
                "audible_movement": movement,
                "heard_the_contour": movement in {"a", "b", "both"},
                "difference_1_5": row.get("difference_1_5"),
            }
        )

    def _split(predicate) -> Dict[str, int]:
        out = {"c": 0, "other": 0, "none": 0, "heard": 0, "n": 0}
        for entry in per_trial:
            if not predicate(entry):
                continue
            out[entry["preference"]] += 1
            out["n"] += 1
            out["heard"] += 1 if entry["heard_the_contour"] else 0
        return out

    primary = _split(lambda e: e["trial_kind"].endswith("current_vs_contour"))
    control = _split(lambda e: e["trial_kind"].endswith("default_vs_contour"))
    profile_primary = _split(lambda e: e["trial_kind"] == "profile_current_vs_contour")
    song_primary = _split(lambda e: e["trial_kind"] == "song_current_vs_contour")
    heard = [e for e in per_trial if e["heard_the_contour"]]

    return {
        "source": (
            "examples/sound_profile_volume_contour_10b/"
            "{manifest.json,evaluation_volume_contour_10b.csv}"
        ),
        "sheet_sha256": sha256_file(sheet) if sheet.is_file() else None,
        "manifest_sha256": sha256_file(package_dir / "manifest.json"),
        "answered": len(rows),
        "trials": len(trials),
        "primary_b_vs_c": primary,
        "profile_level_b_vs_c": profile_primary,
        "song_level_b_vs_c": song_primary,
        "a_vs_c_controls": control,
        "audibility": {
            "heard": len(heard),
            "neither": len(per_trial) - len(heard),
            "heard_trials": [e["trial_id"] for e in heard],
        },
        "per_trial": per_trial,
        "reading": (
            "the volume contour is technically expressible and changes the waveform (proved in "
            "the Stage 10B preparation), but at the profile level all 8 B-vs-C pairs were 'no "
            "clear difference' (only 2 were even heard), and at the song level C won 1 of 6 "
            "against 2 losses and 3 ties. The resolved verdict of Stage 10B is NEGATIVE."
        ),
    }


# ---------------------------------------------------------------------------
# A2 / B7 — the perceptual evidence (archaeology producer, read-only)
# ---------------------------------------------------------------------------
def perceptual_evidence(arch_root: Path = DEFAULT_ARCHAEOLOGY_DIR) -> Dict[str, Any]:
    """The listener evidence, read from the producer repository and Stage 9D.

    Observed only. The single-listener caveat travels with every number here.
    """
    arch_root = Path(arch_root)
    result: Dict[str, Any] = {
        "archaeology_root": str(arch_root),
        "available": arch_root.is_dir(),
        "one_listener": "every rating is from one listener; no population claim is made",
    }
    if not arch_root.is_dir():
        result["note"] = "producer repository not found; perceptual evidence omitted"
        return result

    summary_path = arch_root / "reports" / "stage7b" / "human_evaluation_summary.json"
    if summary_path.is_file():
        summary = _read_json(summary_path)
        predictors = sorted(
            summary["usefulness_predictors"]["results"],
            key=lambda entry: abs(entry["spearman_rho"]),
            reverse=True,
        )
        result["seven_b"] = {
            "source": "reports/stage7b/human_evaluation_summary.json",
            "candidates": summary["dataset"]["candidates"],
            "strongest_usefulness_predictors": [
                {
                    "label": entry["label"],
                    "n": entry["n"],
                    "spearman_rho": entry["spearman_rho"],
                }
                for entry in predictors[:6]
            ],
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
        }

    nine_d_path = DEFAULT_REPORTS_DIR / "stage9d" / "correlations.json"
    if nine_d_path.is_file():
        nine_d = _read_json(nine_d_path)
        result["nine_d"] = {
            "source": "reports/stage9d/correlations.json",
            "table": nine_d["table"],
            "listener_language": nine_d.get("listener_language"),
            "unavailable_metrics": nine_d.get("unavailable_metrics"),
        }

    audit_path = arch_root / "reports" / "stage8c" / "playability_audit.json"
    if audit_path.is_file():
        audit = _read_json(audit_path)
        result["eight_c"] = {
            "source": "reports/stage8c/playability_audit.json",
            "status_totals": audit["status_totals"],
            "headline": audit["headline"],
            "issue_code_totals": audit["issue_code_totals"],
            "consumer_gap_totals": audit["consumer_gap_totals"],
        }
    return result


# ---------------------------------------------------------------------------
# A1 — the evidence matrix (every cell traceable to a published artefact)
# ---------------------------------------------------------------------------
def evidence_matrix(gap: Mapping[str, Any], coll: Mapping[str, Any]) -> List[Dict[str, Any]]:
    """One row per profile feature, with the pipeline fact and the perceptual fact.

    Cells are taken from the artefacts named in ``provenance`` (or "yes"/"no" for
    structural facts). The perceptual column keeps *changes the waveform* apart from *a
    listener preferred the waveform containing it* — they are not equivalent.
    """
    used = set(gap["used_paths"])

    def ir_reach(*substrings: str) -> str:
        hits = [path for path in used if any(sub in path for sub in substrings)]
        return "yes (" + ", ".join(sorted(hits)[:3]) + ")" if hits else "no"

    return [
        {
            "feature": "generator / distortion",
            "in_sound_profile": "yes (synthesis.hardware.distortion)",
            "in_playable_profile": "yes (pokey.hardware.distortion, .waveform)",
            "used_by_binding": "yes (IRInstrument.distortion)",
            "reaches_pokey_ir": ir_reach("hardware.distortion"),
            "changes_wav": "yes (AUDC high nibble -> one of six waveforms)",
            "perceptual_experiment": "7B character vocabulary; 9D same_generator",
            "evidence": "the one spectral axis the listener demonstrably keys on: 9D same_generator vs "
            "similarity rho -0.5993, and the clean/noisy families are disjoint",
            "provenance": "reports/stage9e/pipeline_fields.json; reports/stage9d/correlations.json",
        },
        {
            "feature": "static envelope (ADSR)",
            "in_sound_profile": "yes (synthesis.envelope)",
            "in_playable_profile": "yes (envelope.*)",
            "used_by_binding": "yes (four numbers -> IRInstrument.envelope)",
            "reaches_pokey_ir": ir_reach("envelope"),
            "changes_wav": "yes, but envelope.decay_frames alters no frame (9E L2)",
            "perceptual_experiment": "not tested in isolation",
            "evidence": "the player's four-number state machine is the only envelope the renderer has; "
            "the measured shape in milliseconds is neither stored nor used",
            "provenance": "reports/stage9e/information_loss.json (L2)",
        },
        {
            "feature": "AUDCTL (clock / coupling byte)",
            "in_sound_profile": "yes (synthesis.hardware.audctl_mode)",
            "in_playable_profile": "yes (pokey.hardware.audctl_mode)",
            "used_by_binding": "yes (IRInstrument.audctl)",
            "reaches_pokey_ir": ir_reach("audctl_mode"),
            "changes_wav": "yes for PAIR (AUDCTL column); no effect for VOICE (9E L3)",
            "perceptual_experiment": "not tested in isolation",
            "evidence": "audible only through 16-bit coupling and the 9/17-bit noise selection",
            "provenance": "reports/stage9e/pipeline_fields.json (frame_column_usage)",
        },
        {
            "feature": "16-bit coupling",
            "in_sound_profile": "yes (scope PAIR; observed.combined_divider)",
            "in_playable_profile": "yes (pairing.*, pokey.channels.*)",
            "used_by_binding": "yes (is_16bit, pair flag)",
            "reaches_pokey_ir": ir_reach("pokey.channels.pair"),
            "changes_wav": "yes (PAIR audio is built from AUDF1 + AUDF2)",
            "perceptual_experiment": "9D same_scope; 10B carried one PAIR profile",
            "evidence": "real and expressed; the listener's 'bass' language partly tracks it, but "
            "same_scope vs similarity is only -0.308",
            "provenance": "reports/stage9d/correlations.json; tests/data/sound_profiles/bank",
        },
        {
            "feature": "pitch trajectory",
            "in_sound_profile": "yes (gesture.pitch.runs; pitch.*)",
            "in_playable_profile": "yes (gesture.pitch, pitch.*)",
            "used_by_binding": "no",
            "reaches_pokey_ir": "no (IRInstrument has no per-frame divider)",
            "changes_wav": "no (never rendered)",
            "perceptual_experiment": "not tested (never heard by a listener)",
            "evidence": "carried by 30 profiles / 525 leaf paths / 6 duplicate groups; the listener's "
            "word 'rising' is pitch; Stage 6 measured pitch-shape transfer (cross-song 0.8321)"
            "but never a listener preference",
            "provenance": "reports/stage9e/missing_capabilities.json; producer docs/stage6_transferability.md",
        },
        {
            "feature": "volume contour",
            "in_sound_profile": "yes (gesture.volume.runs)",
            "in_playable_profile": "yes (gesture.volume, volume.*)",
            "used_by_binding": "only when asked (Stage 10B switch; default off)",
            "reaches_pokey_ir": "yes (IRInstrument.volume_contour)",
            "changes_wav": "yes (proved frame-for-frame in Stage 10B)",
            "perceptual_experiment": "Stage 10B, profile-level and whole-song",
            "evidence": "technically expressible and waveform-changing, but perceptually rejected: "
            "8/8 profile B-vs-C pairs were 'no clear difference', song-level C 1-2-3, verdict NEGATIVE",
            "provenance": "reports/stage10b/*; docs/stage10b_volume_contour_listening.md",
        },
        {
            "feature": "noise character",
            "in_sound_profile": "yes (hardware.waveform / distortion family)",
            "in_playable_profile": "yes (pokey.hardware.waveform)",
            "used_by_binding": "yes (via the distortion nibble)",
            "reaches_pokey_ir": "yes (the synth decodes the waveform)",
            "changes_wav": "yes (pure / poly4 / poly5 / poly9 / poly17)",
            "perceptual_experiment": "7B ('noise'); 9D clean vs noisy",
            "evidence": "the listener's clean-vs-noisy split follows the generator family and the two "
            "families are disjoint — already expressible",
            "provenance": "reports/stage9d/correlations.json (listener_language)",
        },
        {
            "feature": "spectral structure (centroid / flatness / bandwidth)",
            "in_sound_profile": "yes in the research record (observed, measured)",
            "in_playable_profile": "no (not a field of PlayableSoundProfile 1.0)",
            "used_by_binding": "no",
            "reaches_pokey_ir": "no (never a register value)",
            "changes_wav": "indirectly: an emergent consequence of generator + frequency + level",
            "perceptual_experiment": "descriptor correlations only (never a rendered, toggled feature)",
            "evidence": "unstable predictor: 7B 'spectral bandwidth (Hz) vs usefulness' -0.4401 while "
            "9D 'bandwidth_hz vs usefulness' is +0.6338 — opposite signs on the same named descriptor",
            "provenance": "reports/stage7b/human_evaluation_summary.json; reports/stage9d/correlations.json",
        },
        {
            "feature": "timing / repetition",
            "in_sound_profile": "yes (gesture.resolution, timing)",
            "in_playable_profile": "yes (timing.*)",
            "used_by_binding": "no (the composition's tempo sets frames_per_tick)",
            "reaches_pokey_ir": "no (profile timing is never read)",
            "changes_wav": "no (never rendered)",
            "perceptual_experiment": "7B ('repetition' 11 comments; 'faster')",
            "evidence": "the listener hears repetition, but it is produced by the arrangement, not by "
            "any profile field the renderer consumes",
            "provenance": "reports/stage7b/human_evaluation_summary.json (qualitative_groups)",
        },
    ]


# ---------------------------------------------------------------------------
# A2 — classify the perceptual evidence per feature
# ---------------------------------------------------------------------------
def feature_classification() -> List[Dict[str, Any]]:
    """For each feature: does it change the waveform, and did a listener prefer it?

    The two are kept apart deliberately. "Not tested" is used where the feature has never
    been rendered and heard; "technically relevant but perceptually unvalidated" where it
    changes the WAV but no isolated listening evidence exists for it.
    """
    return [
        {
            "feature": "generator / distortion",
            "class": "positive evidence",
            "why": "9D: same_generator vs perceived similarity rho -0.5993 (a generator change "
            "predicts a heard difference); the clean and noisy families are disjoint; 7B's "
            "character vocabulary follows the family. It changes the waveform and the listener "
            "keys on it.",
        },
        {
            "feature": "noise character",
            "class": "positive evidence",
            "why": "The same axis as the generator seen from the listener's side: 'clean' "
            "(centroid median 6018 Hz) vs 'noisy' (4135 Hz), Cliff's delta 0.5619, disjoint "
            "families (9D correlations.json). Already expressible by the distortion nibble.",
        },
        {
            "feature": "static envelope (ADSR)",
            "class": "technically relevant but perceptually unvalidated",
            "why": "It changes the WAV (per-frame volume) but has never been toggled in "
            "isolation; and 9E measured that envelope.decay_frames alters no frame at all, so "
            "part of it may be inert.",
        },
        {
            "feature": "AUDCTL",
            "class": "technically relevant but perceptually unvalidated",
            "why": "Audible only through 16-bit coupling and the 9/17-bit noise selection; never "
            "heard in isolation.",
        },
        {
            "feature": "16-bit coupling",
            "class": "technically relevant but perceptually unvalidated",
            "why": "Expressed and audible, but the only perceptual handle is 9D same_scope vs "
            "similarity -0.308, the weakest of the six cues there.",
        },
        {
            "feature": "pitch trajectory",
            "class": "not tested",
            "why": "Never rendered, therefore never heard. The largest *untested* representable "
            "gap (30 profiles, 6 duplicate groups); the listener has a word for it ('rising') "
            "but no preference data exists.",
        },
        {
            "feature": "volume contour",
            "class": "negative evidence",
            "why": "Rendered and heard in Stage 10B: 8/8 profile B-vs-C pairs were 'no clear "
            "difference', the whole-song pairs preferred the no-contour side, verdict NEGATIVE. "
            "It changes the waveform; it was not preferred.",
        },
        {
            "feature": "spectral structure (centroid / flatness / bandwidth)",
            "class": "inconclusive",
            "why": "The named descriptor's correlation with usefulness flips sign between the two "
            "listening datasets (7B -0.4401, 9D +0.6338), and the strongest 9D cue may reflect "
            "correlation between the descriptor and the generator family rather than an "
            "independent perceptual dimension.",
        },
        {
            "feature": "timing / repetition",
            "class": "inconclusive",
            "why": "The listener hears repetition and 'faster', but those are produced by the "
            "arrangement and the player's row timing, not by any profile field the renderer reads.",
        },
    ]


# ---------------------------------------------------------------------------
# A7 — rank the candidates for the missing dimension
# ---------------------------------------------------------------------------
def hypothesis_ranking() -> List[Dict[str, Any]]:
    """Rank candidate missing dimensions by the evidence, not by prior belief.

    The evidence column is measured; the confidence is this stage's judgement and is
    labelled as an experimental choice.
    """
    return [
        {
            "rank": 1,
            "dimension": "pitch trajectory (temporal)",
            "why": "the largest representable gap that has never been heard: 30 profiles / 525 "
            "leaf paths / 6 duplicate groups collapse partly because the measured pitch series "
            "is discarded; the listener has the word 'rising' for it",
            "evidence_strength": "strong as a representation gap, unknown perceptually",
            "confidence": "medium",
            "kind": "representation gap",
        },
        {
            "rank": 2,
            "dimension": "spectral / timbral structure",
            "why": "the renderer already reproduces the dominant audible spectral axis, the "
            "generator family (six waveforms); the finer spectral descriptors are emergent and "
            "their correlation with usefulness is unstable across the two listening datasets",
            "evidence_strength": "positive for the generator axis; inconclusive for the descriptor axis",
            "confidence": "medium",
            "kind": "partly already expressible",
        },
        {
            "rank": 3,
            "dimension": "volume contour (temporal)",
            "why": "tested and rejected: technically expressible and waveform-changing, but the "
            "listener showed no advantage at the profile level and a loss at the song level",
            "evidence_strength": "negative",
            "confidence": "high",
            "kind": "representation gap, closed",
        },
        {
            "rank": 4,
            "dimension": "noise character",
            "why": "already expressed: it is the same axis as the generator, which the renderer "
            "reproduces and the listener responds to",
            "evidence_strength": "positive (already present)",
            "confidence": "high",
            "kind": "already expressible",
        },
        {
            "rank": 5,
            "dimension": "16-bit coupling / AUDCTL",
            "why": "expressed and audible; no independent perceptual weight measured",
            "evidence_strength": "weak",
            "confidence": "medium",
            "kind": "already expressible",
        },
        {
            "rank": 6,
            "dimension": "timing / gesture gating",
            "why": "heard as repetition, but arrangement-driven; Stage 10B found the gating "
            "(level-0) contours the most audible potential class and refused them",
            "evidence_strength": "inconclusive",
            "confidence": "low",
            "kind": "representation gap with no policy",
        },
    ]


# ---------------------------------------------------------------------------
# Assembly
# ---------------------------------------------------------------------------
#: The hypothesis Stage 11 was asked to test, quoted verbatim from the brief.
STAGE_11_HYPOTHESIS = "the remaining perceptual gap may be primarily spectral/timbral rather than temporal"

_INPUT_FILES = (
    "tests/data/sound_profiles/bank/registry.json",
    "reports/stage9e/pipeline_fields.json",
    "reports/stage9e/information_loss.json",
    "reports/stage9e/duplicate_groups.json",
    "reports/stage9e/missing_capabilities.json",
    "reports/stage9d/correlations.json",
    "reports/stage9d/coverage.json",
    "examples/sound_profile_rebinding_10a/manifest.json",
    "examples/sound_profile_rebinding_10a/evaluation_rebinding_10a.csv",
    "examples/sound_profile_volume_contour_10b/manifest.json",
    "examples/sound_profile_volume_contour_10b/evaluation_volume_contour_10b.csv",
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


def build_synthesis(
    *,
    bank_dir: Path = DEFAULT_BANK_DIR,
    reports_dir: Path = DEFAULT_REPORTS_DIR,
    stage10a: Path = DEFAULT_STAGE10A_PACKAGE,
    stage10b: Path = DEFAULT_STAGE10B_PACKAGE,
    archaeology: Path = DEFAULT_ARCHAEOLOGY_DIR,
) -> Dict[str, Any]:
    """Assemble every Stage 11A artefact into one bundle (deterministic; no timestamps)."""
    gap = representation_gap(reports_dir)
    coll = collapse(reports_dir)
    evidence = perceptual_evidence(archaeology)
    reeval_a = reevaluate_10a(stage10a)
    reeval_b = reevaluate_10b(stage10b)
    return {
        "analysis_version": ANALYSIS_VERSION,
        "experiment": "stage11a",
        "hypothesis": STAGE_11_HYPOTHESIS,
        "inputs": _input_hashes(archaeology),
        "evidence_matrix": evidence_matrix(gap, coll),
        "feature_classification": feature_classification(),
        "representation_gap": gap,
        "collapse": coll,
        "stage10a": reeval_a,
        "stage10b": reeval_b,
        "perceptual_evidence": evidence,
        "hypothesis_ranking": hypothesis_ranking(),
        "go_no_go": {
            "decision": "PROCEED (scoped to the existing renderer)",
            "reason": (
                "the spectral hypothesis is not the strongest one the evidence supports, but a "
                "controlled spectral experiment is cheap, uses the existing renderer unchanged, "
                "and answers the one question the brief asks: can the current POKEY model "
                "reproduce the measured spectral character? It is run nonetheless, and its result "
                "is recorded against the ranked candidates rather than assumed."
            ),
            "constraints": [
                "no renderer, IR, player or DSL change (Stage 11B is ablation with existing code)",
                "no profile/schema field added; experimental data lives in reports/stage11/",
                "a variant the renderer cannot express is marked NOT EXPRESSIBLE, never approximated",
            ],
        },
    }


def write_synthesis(
    bundle: Mapping[str, Any],
    *,
    stage11_dir: Path = DEFAULT_STAGE11_DIR,
    docs_dir: Path = DEFAULT_DOCS_DIR,
) -> Dict[str, Path]:
    """Write the machine record and the document. Deterministic byte-for-byte."""
    stage11_dir = Path(stage11_dir)
    docs_dir = Path(docs_dir)
    stage11_dir.mkdir(parents=True, exist_ok=True)
    docs_dir.mkdir(parents=True, exist_ok=True)

    written: Dict[str, Path] = {}
    files = {
        "synthesis.json": bundle,
        "evidence_matrix.json": bundle["evidence_matrix"],
        "feature_classification.json": bundle["feature_classification"],
        "representation_gap.json": bundle["representation_gap"],
        "collapse.json": bundle["collapse"],
        "stage10a_reevaluation.json": bundle["stage10a"],
        "stage10b_reevaluation.json": bundle["stage10b"],
        "perceptual_evidence.json": bundle["perceptual_evidence"],
        "hypothesis_ranking.json": bundle["hypothesis_ranking"],
        "go_no_go.json": bundle["go_no_go"],
    }
    for name, payload in files.items():
        path = stage11_dir / name
        path.write_text(_dumps(payload), encoding="utf-8")
        written[name] = path

    doc = docs_dir / "stage11_perceptual_synthesis.md"
    doc.write_text(render_report(bundle), encoding="utf-8", newline="\n")
    written["stage11_perceptual_synthesis.md"] = doc
    return written


# ---------------------------------------------------------------------------
# The document
# ---------------------------------------------------------------------------
def _md_table(header: Sequence[str], rows: Sequence[Sequence[Any]]) -> str:
    lines = ["| " + " | ".join(header) + " |", "| " + " | ".join([":---"] * len(header)) + " |"]
    for row in rows:
        lines.append("| " + " | ".join(str(cell) for cell in row) + " |")
    return "\n".join(lines)


def render_report(bundle: Mapping[str, Any]) -> str:
    """`docs/stage11_perceptual_synthesis.md` — Stage 11A, analysis only."""
    gap = bundle["representation_gap"]
    coll = bundle["collapse"]
    a = bundle["stage10a"]
    b = bundle["stage10b"]
    ev = bundle["perceptual_evidence"]
    lines: List[str] = []
    add = lines.append

    add("# Stage 11A — perceptual synthesis")
    add("")
    add(
        "Where does the perceptual character of an archaeology POKEY sound go missing in the "
        "current composer pipeline? This document answers that from the published evidence only. "
        "Nothing is rendered, no renderer is changed, no profile is selected and no listening is "
        "done here."
    )
    add("")
    add(f"* experiment: `{bundle['experiment']}` (`{bundle['analysis_version']}`)")
    add(f"* hypothesis under test: *{bundle['hypothesis']}*")
    add(f"* input artefacts hashed: {len(bundle['inputs'])}")
    add(f"* go / no-go for Stage 11B: **{bundle['go_no_go']['decision']}**")
    add("")
    add(
        "Three kinds of statement are kept apart: **Observed** (a value read from a named "
        "published artefact), **Inference** (what follows) and **Experimental choice** (what this "
        "stage decided, which no measurement forces)."
    )
    add("")

    add("## A1. Evidence matrix")
    add("")
    add(
        "One row per profile feature. *reaches IR* is computed from Stage 9E's field census; "
        "everything else is quoted from the artefact named in *provenance*."
    )
    add("")
    add(
        _md_table(
            ("feature", "in SoundProfile", "in Playable", "used by binding", "reaches IR", "changes WAV", "perceptual experiment"),
            [
                (
                    row["feature"],
                    row["in_sound_profile"],
                    row["in_playable_profile"],
                    row["used_by_binding"],
                    row["reaches_pokey_ir"],
                    row["changes_wav"],
                    row["perceptual_experiment"],
                )
                for row in bundle["evidence_matrix"]
            ],
        )
    )
    add("")

    add("## A2. Changing the waveform is not the same as being preferred")
    add("")
    add(
        "A feature that changes the waveform has not thereby been shown useful: the listener "
        "must prefer it. Stage 10B is the worked example — the volume contour changes the "
        "waveform frame-for-frame and was *rejected*."
    )
    add("")
    add(
        _md_table(
            ("feature", "class", "why"),
            [(row["feature"], row["class"], row["why"]) for row in bundle["feature_classification"]],
        )
    )
    add("")

    add("## A3. The renderer / representation gap")
    add("")
    add(
        f"**Observed.** The binding reads **{gap['read_by_binding_count']} of "
        f"{gap['leaf_paths_total']}** documented leaf paths. The census: "
        + ", ".join(f"{count} {status}" for status, count in sorted(gap["counts"].items()))
        + "."
    )
    add("")
    add(
        f"* the first information loss is at **{gap['first_information_loss']}** — "
        f"{gap['loss_points']['l1_first_loss']['measurement']}"
    )
    add(
        "* the renderer does not lose anything the binding writes: "
        + gap["loss_points"]["l3_no_gap"]["measurement"]
    )
    add(
        "* whole sections the binding ignores: "
        + ", ".join(
            f"`{name}` ({data['paths']} paths)"
            for name, data in sorted(gap["sections"].items())
            if data["statuses"].get("IGNORED") or data["statuses"].get("UNREPRESENTABLE")
        )
        + "; the measured gesture loss is "
        + ", ".join(f"**{key}**" for key in sorted(gap["gesture_lost_by_binding"]))
        + "."
    )
    add("")

    add("## A4. Why 61 renderable profiles collapse to 37 audio signals")
    add("")
    add(
        f"**Observed.** {coll['profiles_probed']} renderable profiles produce "
        f"{coll['distinct_audio_signals']} distinct audio signals; {coll['redundant_profiles']} "
        f"profiles are redundant across {coll['groups']} groups "
        f"(sizes {', '.join(str(size) for size in coll['group_sizes'])}). Every group is a "
        f"`{next(iter(coll['classification_counts']))}`, first diverging at "
        f"`{next(iter(coll['first_divergence_counts']))}`; the audio-only measurement agrees: "
        f"{coll['agrees_with_the_audio_only_measurement']}."
    )
    add("")
    add(f"**Inference.** {coll['conclusion']}")
    add("")

    add("## A5. Stage 10A, re-evaluated from the actual answers")
    add("")
    add(
        f"**Observed.** {a['answered']} of {a['trials']} pairs answered. Primary "
        f"(`default_vs_new` + `old_vs_new`, 12 pairs): NEW won **{a['primary']['new']}**, the "
        f"other side **{a['primary']['other']}**, ties **{a['primary']['none']}**. Control "
        f"(`default_vs_old`, 6 pairs): DEFAULT **{a['control']['default']}**, OLD "
        f"**{a['control']['old']}**, ties **{a['control']['none']}**."
    )
    add("")
    add(f"**Inference.** {a['reading']}")
    add("")

    add("## A6. Stage 10B, re-evaluated from the actual answers")
    add("")
    add(
        f"**Observed.** Profile-level B-vs-C ({b['profile_level_b_vs_c']['n']} pairs): C "
        f"**{b['profile_level_b_vs_c']['c']}**, other **{b['profile_level_b_vs_c']['other']}**, "
        f"no difference **{b['profile_level_b_vs_c']['none']}**. Song-level B-vs-C "
        f"({b['song_level_b_vs_c']['n']} pairs): C **{b['song_level_b_vs_c']['c']}**, other "
        f"**{b['song_level_b_vs_c']['other']}**, no difference **{b['song_level_b_vs_c']['none']}**. "
        f"Contour heard in {b['audibility']['heard']} of {b['answered']} pairs."
    )
    add("")
    add(f"**Inference.** {b['reading']}")
    add("")

    add("## A7. The strongest remaining hypothesis")
    add("")
    add(
        _md_table(
            ("rank", "dimension", "kind", "evidence", "confidence", "why"),
            [
                (
                    row["rank"],
                    row["dimension"],
                    row["kind"],
                    row["evidence_strength"],
                    row["confidence"],
                    row["why"],
                )
                for row in bundle["hypothesis_ranking"]
            ],
        )
    )
    add("")

    add("## A8. The listener's vocabulary against measurable structure")
    add("")
    sb = ev.get("seven_b", {})
    add(
        "**Observed.** Stage 7B's own comment groups (counts from its summary): "
        + ", ".join(f"{entry['term']} ({entry['comments']})" for entry in sb.get("vocabulary", []))
        + "."
    )
    add("")
    if "nine_d" in ev:
        table = ev["nine_d"]["table"]
        add(
            "**Observed.** Selected rows of the Stage 9D human-vs-machine table (Spearman, n=60): "
            + "; ".join(
                f"{row['metric']} vs {row['scale']} = {row['spearman']}"
                for row in table
                if row["metric"] in {"bandwidth_hz", "centroid_hz", "flatness", "rolloff_hz"}
                and row["scale"] in {"usefulness", "distinctiveness"}
            )
            + "."
        )
        add("")
    add(
        "**Inference.** The listener's *noise / high frequency / clean* vocabulary maps onto the "
        "generator family and the spectral centroid — already expressible. The *rising* vocabulary "
        "maps onto pitch trajectory — measured, carried by 30 profiles, and never rendered. The "
        "*repetition* vocabulary maps onto the arrangement, not onto any profile field the "
        "renderer reads."
    )
    add("")
    add(
        "**Observed — the one instability that matters.** The descriptor named *spectral "
        "bandwidth (Hz)* correlates with usefulness at **-0.4401** in Stage 7B (20 candidates) and "
        "at **+0.6338** in Stage 9D (61 profiles): opposite signs under the same name. Any claim "
        "that a spectral descriptor predicts usefulness must survive that."
    )
    add("")

    add("## A9. Go / no-go for Stage 11B")
    add("")
    add(f"**Experimental choice.** **{bundle['go_no_go']['decision']}.** {bundle['go_no_go']['reason']}")
    add("")
    for item in bundle["go_no_go"]["constraints"]:
        add(f"* {item}")
    add("")
    add(
        "The hypothesis the brief asked to test — that the gap is principally spectral — is **not "
        "the strongest one the evidence supports**: the renderer already reproduces the dominant "
        "audible spectral axis (the generator family), and the temporal gesture is the larger "
        "representation gap. Stage 11B is run anyway, precisely because the brief asks to *test* "
        "the hypothesis rather than assume it, and its result is recorded against the ranked "
        "candidates above."
    )
    add("")

    add("## A10. Reproducibility")
    add("")
    add(
        "This document and every `reports/stage11/*.json` are a pure function of the artefacts "
        "below (SHA-256), with no timestamp in any of them, so two runs are byte-identical:"
    )
    add("")
    add("```json")
    add(json.dumps(bundle["inputs"], indent=2, sort_keys=True))
    add("```")
    add("")
    return "\n".join(lines) + "\n"

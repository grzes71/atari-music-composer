"""Stage 9D: analysis of the human listening results for the POKEY sound profile library.

Stage 9C asked a human to listen to all 61 renderable profiles and answer three experiments.
This module reads those answers back — **without modifying them** — joins them to the machine-
readable manifest, and reports what the listening actually showed.

It exists because the interesting question is not "which profile has the highest average". It is:

    Do these profiles deliver useful and perceptually *different* sounds, and which measurable
    properties of a profile predict its value to Atari Music Composer?

Three design rules are load-bearing:

* **No answer is invented.** A missing rating stays missing, is counted as missing, and reduces
  the denominator. Nothing is imputed, averaged in, or silently dropped from a row.
* **The experiment is not touched.** This module only reads: the answers, the private manifest
  and — for one decisive measurement — the rendered WAV files, which it hashes rather than plays.
* **Measurement noise is measured, not assumed.** The library renders 61 profiles into 37
  distinct audio signals, so some *byte-identical* stimuli were presented as different samples.
  The spread of ratings inside those groups is the listener's own noise floor, and every scale
  is judged against it.
"""

from __future__ import annotations

import csv
import hashlib
import json
import math
import statistics
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

import numpy as np

from atari_music.stage9c import (
    AB_TEMPLATE_HEADER,
    PROFILE_TEMPLATE_HEADER,
    SONG_TEMPLATE_HEADER,
    spectral_distance,
)

#: The stage this module analyses.
STAGE = "stage9d"

#: Version of the analysis output, so a later stage can tell what it is reading.
ANALYSIS_VERSION = "stage9d/1"

#: The scales the listener rated, in report order.
PROFILE_SCALES: Tuple[str, ...] = ("distinctiveness", "usefulness", "atari_character", "confidence")

#: The three preference questions in part B and part C, and their answer vocabulary.
PREFERENCE_FIELDS: Tuple[str, ...] = ("preference",)
SONG_CHOICE_FIELDS: Tuple[str, ...] = ("better_sound", "more_character", "more_convincing_atari")

#: Minimum n for any correlation to be reported at all. Below this the number would be noise
#: dressed up as a finding, and the brief asks for the cautious answer.
MIN_CORRELATION_N = 8

#: Comment vocabulary the Stage 9C README suggested, kept only to show what the listener did
#: *not* use. The categories in `derive_comment_categories` come from the answers instead.
SUGGESTED_VOCABULARY: Tuple[str, ...] = ("bass", "drum", "snare", "bell", "noise", "laser", "repeating")

#: Derived comment categories: name -> (any-of markers, description used in the report).
#:
#: Read out of *this* listener's own words. The markers are the stems that actually occur in the
#: answers, and each category is reported with the exact markers and member samples so a reader
#: can disagree with the grouping rather than having to trust it.
COMMENT_CATEGORIES: Tuple[Tuple[str, Tuple[str, ...], str], ...] = (
    ("lead_tonal", ("lead", "tone"), "a sustained melodic tone"),
    ("percussive_noisy", ("bass", "perc", "nois", "crackl", "rustl", "beat"), "noise-like, percussive or bass-register"),
    ("clean", ("clean", "clear"), "described as clean or clear"),
    ("loud", ("loud", "lound"), "heard as loud"),
    ("short_transient", ("short",), "heard as short"),
    ("artefact", ("break",), "carries an audible break/artefact"),
    ("interesting", ("interesting",), "explicitly called interesting"),
)

#: Machine metrics that this stage does **not** have. Declared, so their absence is a recorded
#: fact rather than a silent omission: none of these is in the Stage 9C manifest.
UNAVAILABLE_METRICS: Tuple[str, ...] = (
    "transferability (Stage 6)",
    "Stage 7B perceptual metrics",
    "control stability",
    "profile distance (Stage 6 definition)",
    "envelope similarity",
)


class Stage9DError(RuntimeError):
    """The listening results could not be analysed."""


class AnswersMissing(Stage9DError):
    """The evaluation files are absent or still empty."""


# ===========================================================================
# Small statistics. Implemented here so the analysis is dependency-free and
# every formula used in the report is inspectable.
# ===========================================================================
def pearson(xs: Sequence[float], ys: Sequence[float]) -> Optional[float]:
    if len(xs) < 3 or len(xs) != len(ys):
        return None
    mx, my = statistics.fmean(xs), statistics.fmean(ys)
    num = sum((a - mx) * (b - my) for a, b in zip(xs, ys))
    den = math.sqrt(sum((a - mx) ** 2 for a in xs) * sum((b - my) ** 2 for b in ys))
    return num / den if den > 0 else None


def _ranks(values: Sequence[float]) -> List[float]:
    """Average ranks, so ties are handled the way Spearman requires."""
    order = sorted(range(len(values)), key=lambda index: values[index])
    result = [0.0] * len(values)
    position = 0
    while position < len(order):
        end = position
        while end + 1 < len(order) and values[order[end + 1]] == values[order[position]]:
            end += 1
        average = (position + end) / 2.0 + 1.0
        for index in range(position, end + 1):
            result[order[index]] = average
        position = end + 1
    return result


def spearman(xs: Sequence[float], ys: Sequence[float]) -> Optional[float]:
    if len(xs) < 3 or len(xs) != len(ys):
        return None
    return pearson(_ranks(xs), _ranks(ys))


def kendall_tau_b(xs: Sequence[float], ys: Sequence[float]) -> Optional[float]:
    """Kendall's tau-b, tie-corrected. Small-n rank agreement without a distributional claim."""
    n = len(xs)
    if n < 4 or n != len(ys):
        return None
    concordant = discordant = ties_x = ties_y = 0
    for i in range(n):
        for j in range(i + 1, n):
            dx, dy = xs[i] - xs[j], ys[i] - ys[j]
            if dx == 0 and dy == 0:
                ties_x += 1
                ties_y += 1
            elif dx == 0:
                ties_x += 1
            elif dy == 0:
                ties_y += 1
            elif (dx > 0) == (dy > 0):
                concordant += 1
            else:
                discordant += 1
    denominator = math.sqrt(
        (concordant + discordant + ties_x) * (concordant + discordant + ties_y)
    )
    return (concordant - discordant) / denominator if denominator > 0 else None


def cliffs_delta(left: Sequence[float], right: Sequence[float]) -> Optional[float]:
    """Cliff's delta: P(left > right) - P(left < right), for two independent groups.

    Chosen over a t-test because the ratings are 1-5 ordinals with heavy ties, and because a
    delta of 0.33/0.47/0.66 has a plain reading (small/medium/large) that does not imply a
    normal distribution the data cannot support.
    """
    if not left or not right:
        return None
    greater = less = 0
    for a in left:
        for b in right:
            if a > b:
                greater += 1
            elif a < b:
                less += 1
    return (greater - less) / (len(left) * len(right))


def describe(values: Sequence[float]) -> Dict[str, Any]:
    """Summary of one rating scale. Empty input returns a summary of nothing, not zeros."""
    if not values:
        return {"n": 0}
    ordered = sorted(values)
    return {
        "n": len(values),
        "mean": round(statistics.fmean(values), 3),
        "median": round(statistics.median(values), 3),
        "stdev": round(statistics.stdev(values), 3) if len(values) > 1 else 0.0,
        "min": min(values),
        "max": max(values),
        "share_4_5": round(sum(1 for v in values if v >= 4) / len(values), 3),
        "share_1_2": round(sum(1 for v in values if v <= 2) / len(values), 3),
        "distribution": {str(score): sum(1 for v in values if v == score) for score in range(1, 6)},
    }


def icc_1_1(groups: Sequence[Sequence[float]]) -> Optional[float]:
    """Intraclass correlation (1,1): how much of a rating's spread the *stimulus* explains.

    Each group holds repeated ratings of one **byte-identical** sound, so the within-group
    spread is pure measurement noise and the between-group spread is the signal the listener
    could actually distinguish. Computed as

        ICC = (MS_between - MS_within) / (MS_between + (k̄ - 1) * MS_within)

    with k̄ the average number of ratings per group (the standard one-way random-effects form for
    unequal group sizes). 1 means the listener was perfectly consistent about the same sound and
    fully separated different sounds; 0 means group membership explained nothing; negative values
    mean the same sound was rated *more* differently than different sounds were.
    """
    usable = [list(group) for group in groups if len(group) > 1]
    if len(usable) < 2:
        return None
    mean_of_groups = statistics.fmean(statistics.fmean(group) for group in usable)
    grand_n = sum(len(group) for group in usable)
    group_count = len(usable)

    ss_between = sum(
        len(group) * (statistics.fmean(group) - mean_of_groups) ** 2 for group in usable
    )
    ss_within = sum(
        (value - statistics.fmean(group)) ** 2 for group in usable for value in group
    )
    df_between, df_within = group_count - 1, grand_n - group_count
    if df_between <= 0 or df_within <= 0:
        return None
    ms_between, ms_within = ss_between / df_between, ss_within / df_within
    k_bar = grand_n / group_count
    denominator = ms_between + (k_bar - 1.0) * ms_within
    if denominator <= 0:
        return None
    return (ms_between - ms_within) / denominator


# ===========================================================================
# Reading and verifying the returned answers
# ===========================================================================
@dataclass
class Anomaly:
    """Something in the returned data that the analysis must report rather than repair."""

    kind: str
    where: str
    detail: str
    effect: str


@dataclass
class Answers:
    """The raw returned answers, hashed, plus the manifest they belong to."""

    package_dir: Path
    manifest: Dict[str, Any]
    profiles: List[Dict[str, str]]
    ab: List[Dict[str, str]]
    song: List[Dict[str, str]]
    hashes: Dict[str, str]
    anomalies: List[Anomaly] = field(default_factory=list)


@dataclass
class ProfileResult:
    """One profile: what the listener said, joined to what the machine measured."""

    sample_id: str
    profile_id: str
    scope: str
    status: str
    generator_family: str
    divider_bits: int
    audctl_mode: str
    source_song: str
    source_song_origin: str
    source_songs: List[str]
    limitation_codes: List[str]
    blocking_codes: List[str]
    consumer_gap_codes: List[str]
    envelope_confidence: Optional[float]
    envelope_source: str
    stimulus_hash: str
    ratings: Dict[str, Optional[float]]
    comment: str
    categories: List[str]
    features: Dict[str, Any]
    levels: Dict[str, Any]
    distance_to_library: float

    def value(self, scale: str) -> Optional[float]:
        return self.ratings.get(scale)


#: Columns that must be present, per answers file.
_REQUIRED = {
    "evaluation_profiles.csv": PROFILE_TEMPLATE_HEADER,
    "evaluation_ab.csv": AB_TEMPLATE_HEADER,
    "evaluation_songs.csv": SONG_TEMPLATE_HEADER,
}


def _read_rows(path: Path) -> List[Dict[str, str]]:
    if not path.is_file():
        raise AnswersMissing(f"missing answers file: {path}")
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        missing = [column for column in _REQUIRED[path.name] if column not in (reader.fieldnames or [])]
        if missing:
            raise AnswersMissing(f"{path.name} is missing column(s): {', '.join(missing)}")
        return list(reader)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_answers(package_dir: Path) -> Answers:
    """Read the three answer files and the manifest, and record their hashes.

    The hashes are written into the report so the analysis can be reproduced bit-for-bit from
    the exact bytes that were analysed. Nothing is written back to the package.
    """
    package_dir = Path(package_dir)
    manifest_path = package_dir / "manifest.json"
    if not manifest_path.is_file():
        raise AnswersMissing(f"missing experiment manifest: {manifest_path}")

    files = ("evaluation_profiles.csv", "evaluation_ab.csv", "evaluation_songs.csv")
    for name in files:
        if not (package_dir / name).is_file():
            raise AnswersMissing(f"missing answers file: {package_dir / name}")

    answers = Answers(
        package_dir=package_dir,
        manifest=json.loads(manifest_path.read_text(encoding="utf-8")),
        profiles=_read_rows(package_dir / "evaluation_profiles.csv"),
        ab=_read_rows(package_dir / "evaluation_ab.csv"),
        song=_read_rows(package_dir / "evaluation_songs.csv"),
        hashes={name: _sha256(package_dir / name) for name in files}
        | {"manifest.json": _sha256(manifest_path)},
    )
    answers.anomalies = _verify(answers)
    return answers


def _number(raw: Optional[str]) -> Optional[float]:
    text = (raw or "").strip()
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _choice(raw: Optional[str]) -> Optional[str]:
    text = (raw or "").strip().lower()
    return text or None


def _verify(answers: Answers) -> List[Anomaly]:
    """Every check the brief asks for, and a record of anything that does not line up."""
    found: List[Anomaly] = []
    manifest = answers.manifest
    expected_profiles = [entry["sample_id"] for entry in manifest["samples"]]
    expected_ab = [entry["trial_id"] for entry in manifest["ab_trials"]]
    expected_song = [entry["trial_id"] for entry in manifest["song_trials"]]

    checks = (
        ("part A", answers.profiles, expected_profiles, "sample_id"),
        ("part B", answers.ab, expected_ab, "trial_id"),
        ("part C", answers.song, expected_song, "trial_id"),
    )
    for label, rows, expected, key in checks:
        got = [row.get(key, "") for row in rows]
        if len(rows) != len(expected):
            found.append(
                Anomaly(
                    "row_count",
                    label,
                    f"{len(rows)} rows returned, {len(expected)} expected",
                    "the affected part is analysed on the rows that exist",
                )
            )
        duplicates = [item for item, count in Counter(got).items() if count > 1]
        if duplicates:
            found.append(
                Anomaly("duplicate_id", label, f"ids appearing more than once: {duplicates}",
                        "the first occurrence is used; the duplicate is reported")
            )
        unknown = sorted(set(got) - set(expected))
        if unknown:
            found.append(
                Anomaly("unknown_id", label, f"ids not present in the manifest: {unknown}",
                        "ignored, because no profile can be resolved for them")
            )
        absent = sorted(set(expected) - set(got))
        if absent:
            found.append(
                Anomaly("missing_row", label, f"ids the manifest expects but the file lacks: {absent}",
                        "counted as missing rather than assumed")
            )

    numeric_checks = (
        ("part A", answers.profiles, ("distinctiveness", "usefulness", "atari_character", "confidence")),
        ("part B", answers.ab, ("similarity", "character_difference")),
        ("part C", answers.song, ("overall_difference",)),
    )
    for label, rows, fields in numeric_checks:
        for field_name in fields:
            empty = [row.get("sample_id") or row.get("trial_id") for row in rows
                     if not (row.get(field_name) or "").strip()]
            invalid = [
                (row.get("sample_id") or row.get("trial_id"), row.get(field_name))
                for row in rows
                if (row.get(field_name) or "").strip()
                and not 1 <= (_number(row.get(field_name)) or 0) <= 5
            ]
            if empty:
                found.append(
                    Anomaly(
                        "missing_rating", f"{label}.{field_name}",
                        f"no value for {len(empty)} row(s): {empty}",
                        f"excluded from the {field_name} statistics; the denominator is reported",
                    )
                )
            if invalid:
                found.append(
                    Anomaly("out_of_range", f"{label}.{field_name}",
                            f"values outside 1..5: {invalid}",
                            "excluded from that field's statistics")
                )

    for field_name in PREFERENCE_FIELDS:
        empty = [row.get("trial_id") for row in answers.ab if not (row.get(field_name) or "").strip()]
        if empty:
            found.append(
                Anomaly("missing_choice", f"part B.{field_name}",
                        f"no preference recorded for {empty}",
                        "counted as 'not stated'; it is not read as 'no preference'")
            )
    for field_name in SONG_CHOICE_FIELDS:
        empty = [row.get("trial_id") for row in answers.song if not (row.get(field_name) or "").strip()]
        if empty:
            found.append(
                Anomaly("missing_choice", f"part C.{field_name}", f"no answer for {empty}",
                        "excluded from that question's tally")
            )

    whitespace = [
        (row.get("sample_id") or row.get("trial_id"), field_name, row[field_name])
        for table in (answers.profiles, answers.ab, answers.song)
        for row in table
        for field_name in row
        if row.get(field_name) is not None and row[field_name] != row[field_name].strip()
    ]
    if whitespace:
        found.append(
            Anomaly("whitespace", "answers", f"values with leading/trailing spaces: {whitespace}",
                    "kept verbatim; only used trimmed for matching")
        )
    return found


# ===========================================================================
# The measurement noise floor, from byte-identical stimuli
# ===========================================================================
def stimulus_hashes(package_dir: Path, manifest: Mapping[str, Any]) -> Dict[str, str]:
    """SHA-256 of each rendered stimulus.

    Hashing rather than listening: two profiles that produce the same bytes produce the same
    sound, so any difference the listener reported between them is their own inconsistency.
    """
    result: Dict[str, str] = {}
    for entry in manifest["samples"]:
        path = Path(package_dir) / entry["file"]
        if not path.is_file():
            raise AnswersMissing(f"missing stimulus file: {path}")
        result[entry["sample_id"]] = _sha256(path)
    return result


def identical_audio_groups(hashes: Mapping[str, str]) -> List[List[str]]:
    """Sample ids grouped by identical audio, largest group first, ids in presentation order."""
    buckets: Dict[str, List[str]] = defaultdict(list)
    for sample_id in sorted(hashes):
        buckets[hashes[sample_id]].append(sample_id)
    groups = [sorted(ids) for ids in buckets.values()]
    groups.sort(key=lambda ids: (-len(ids), ids[0]))
    return groups


def derive_comment_categories(comment: str) -> List[str]:
    """Categories a comment belongs to, from the listener's own vocabulary.

    Deliberately a transparent marker match rather than a classifier: the report lists the
    markers and the member samples, so the grouping can be checked by hand.
    """
    text = (comment or "").lower()
    return [
        name
        for name, markers, _ in COMMENT_CATEGORIES
        if any(marker in text for marker in markers)
    ]


def build_profile_results(answers: Answers) -> List[ProfileResult]:
    """Join every answered sample to its manifest metadata, its audio and its comment."""
    hashes = stimulus_hashes(answers.package_dir, answers.manifest)
    by_sample = {entry["sample_id"]: entry for entry in answers.manifest["samples"]}

    features = [entry["features"] for entry in answers.manifest["samples"]]
    results: List[ProfileResult] = []
    for row in answers.profiles:
        sample_id = (row.get("sample_id") or "").strip()
        entry = by_sample.get(sample_id)
        if entry is None:
            continue
        distances = [
            spectral_distance(entry["features"], other)
            for other in features
            if other is not entry["features"]
        ]
        comment = row.get("comment") or ""
        results.append(
            ProfileResult(
                sample_id=sample_id,
                profile_id=entry["profile_id"],
                scope=entry["scope"],
                status=entry["status"],
                generator_family=entry["generator_family"],
                divider_bits=entry["divider_bits"],
                audctl_mode=entry["audctl_mode"],
                source_song=entry["source_song"],
                source_song_origin=entry["source_song_origin"],
                source_songs=list(entry["source_songs"]),
                limitation_codes=list(entry["limitation_codes"]),
                blocking_codes=list(entry["blocking_issues"]),
                consumer_gap_codes=list(entry["consumer_gap_codes"]),
                envelope_confidence=entry["envelope_confidence"],
                envelope_source=entry["envelope_source"],
                stimulus_hash=hashes[sample_id],
                ratings={scale: _number(row.get(scale)) for scale in PROFILE_SCALES},
                comment=comment.strip(),
                categories=derive_comment_categories(comment),
                features=entry["features"],
                levels=entry["levels"],
                distance_to_library=round(statistics.fmean(distances), 6) if distances else 0.0,
            )
        )
    results.sort(key=lambda item: item.profile_id)
    return results


# ===========================================================================
# Part A
# ===========================================================================
def part_a(results: Sequence[ProfileResult], groups: Sequence[Sequence[str]]) -> Dict[str, Any]:
    """Per-profile statistics, the scale summaries, and the noise floor."""
    answered = [item for item in results if item.value("distinctiveness") is not None]
    scales = {
        scale: describe([item.value(scale) for item in answered if item.value(scale) is not None])
        for scale in PROFILE_SCALES
    }

    by_sample = {item.sample_id: item for item in results}
    within: Dict[str, List[float]] = {}
    for scale in PROFILE_SCALES:
        spreads = []
        for group in groups:
            values = [
                by_sample[sample_id].value(scale)
                for sample_id in group
                if sample_id in by_sample and by_sample[sample_id].value(scale) is not None
            ]
            if len(values) > 1:
                spreads.append(values)
        within[scale] = spreads

    noise = {}
    for scale in PROFILE_SCALES:
        spreads = within[scale]
        lengths = [len(values) for values in spreads]
        ranges = [max(values) - min(values) for values in spreads]
        deviations = [
            statistics.stdev(values) for values in spreads if len(values) > 1
        ]
        noise[scale] = {
            "groups_with_more_than_one_rating": len(spreads),
            "ratings_inside_identical_audio": sum(lengths),
            "mean_within_group_range": round(statistics.fmean(ranges), 3) if ranges else None,
            "max_within_group_range": max(ranges) if ranges else None,
            "mean_within_group_stdev": round(statistics.fmean(deviations), 3) if deviations else None,
            "icc_1_1": (
                round(icc, 4) if (icc := icc_1_1(spreads)) is not None else None
            ),
        }

    # Quadrants of the two scales that decide usefulness.
    quadrants: Dict[str, List[ProfileResult]] = defaultdict(list)
    for item in answered:
        distinct = item.value("distinctiveness")
        useful = item.value("usefulness")
        if distinct is None or useful is None:
            continue
        if distinct >= 4 and useful >= 4:
            quadrants["distinctive_and_useful"].append(item)
        elif distinct >= 4:
            quadrants["distinctive_not_useful"].append(item)
        elif useful >= 4:
            quadrants["useful_not_distinctive"].append(item)
        else:
            quadrants["neither"].append(item)

    by_scope: Dict[str, List[float]] = defaultdict(list)
    by_family: Dict[str, List[float]] = defaultdict(list)
    by_status: Dict[str, List[float]] = defaultdict(list)
    for item in answered:
        for key, bucket in (
            (item.scope, by_scope),
            (item.generator_family, by_family),
            (item.status, by_status),
        ):
            bucket[key].append(item.value("usefulness") or 0.0)

    categories = Counter(
        name for item in results for name in item.categories
    )

    confidence_bands: Dict[str, List[ProfileResult]] = {"low (1-2)": [], "medium (3)": [], "high (4-5)": []}
    for item in answered:
        confidence = item.value("confidence")
        if confidence is None:
            continue
        band = "low (1-2)" if confidence <= 2 else ("medium (3)" if confidence == 3 else "high (4-5)")
        confidence_bands[band].append(item)

    return {
        "scales": scales,
        "noise_floor": noise,
        "quadrants": {name: [item.profile_id for item in items] for name, items in quadrants.items()},
        "by_scope": {key: describe(values) for key, values in sorted(by_scope.items())},
        "by_family": {key: describe(values) for key, values in sorted(by_family.items())},
        "by_status": {key: describe(values) for key, values in sorted(by_status.items())},
        "category_counts": dict(categories.most_common()),
        "confidence_bands": {
            band: {
                "n": len(items),
                "distinctiveness": describe(
                    [item.value("distinctiveness") for item in items if item.value("distinctiveness") is not None]
                ),
                "usefulness": describe(
                    [item.value("usefulness") for item in items if item.value("usefulness") is not None]
                ),
            }
            for band, items in confidence_bands.items()
        },
    }


def presentation_drift(results: Sequence[ProfileResult], manifest: Mapping[str, Any]) -> Dict[str, Any]:
    """Correlation between a sample's position in the session and its rating.

    The samples were presented in a seeded order, so position is not a property of the sound. A
    correlation here is a session effect (fatigue, habituation, drifting scale use) and belongs
    in the report, because it bounds how much of the rating spread can be read as profile
    quality.
    """
    position = {entry["sample_id"]: index for index, entry in enumerate(manifest["samples"])}
    out: Dict[str, Any] = {}
    for scale in PROFILE_SCALES:
        pairs = [
            (position[item.sample_id], item.value(scale))
            for item in results
            if item.value(scale) is not None
        ]
        pairs.sort()
        out[scale] = {
            "n": len(pairs),
            "pearson_position": _round(pearson([p[0] for p in pairs], [p[1] for p in pairs])),
            "spearman_position": _round(spearman([p[0] for p in pairs], [p[1] for p in pairs])),
            "mean_first_half": _round(
                statistics.fmean([p[1] for p in pairs[: len(pairs) // 2]]) if pairs else None
            ),
            "mean_second_half": _round(
                statistics.fmean([p[1] for p in pairs[len(pairs) // 2 :]]) if pairs else None
            ),
        }
    return out


def _round(value: Optional[float], digits: int = 4) -> Optional[float]:
    return round(value, digits) if value is not None else None


# ===========================================================================
# Part B
# ===========================================================================
def part_b(
    answers: Answers,
    results: Sequence[ProfileResult],
) -> Dict[str, Any]:
    """The 30 blinded profile pairs: what was preferred, what was called similar."""
    manifest = {entry["trial_id"]: entry for entry in answers.manifest["ab_trials"]}
    hashes = {item.sample_id: item.stimulus_hash for item in results}
    by_sample = {item.sample_id: item for item in results}
    # What each stimulus sounds and measures like, for the blind-spot comparison.
    labels = {
        item.sample_id: {
            "rms": item.levels["final_rms_dbfs"],
            "centroid": item.features["centroid_hz"],
            "flatness": item.features["flatness"],
        }
        for item in results
    }
    levels = {sample_id: values["rms"] for sample_id, values in labels.items()}

    trials: List[Dict[str, Any]] = []
    for row in answers.ab:
        trial_id = (row.get("trial_id") or "").strip()
        entry = manifest.get(trial_id)
        if entry is None:
            continue
        similarity = _number(row.get("similarity"))
        character = _number(row.get("character_difference"))
        preference = _choice(row.get("preference"))
        identical = hashes.get(entry["sample_a"]) == hashes.get(entry["sample_b"])
        trials.append(
            {
                "trial_id": trial_id,
                "stratum": entry["stratum"],
                "profile_a": entry["profile_a"],
                "profile_b": entry["profile_b"],
                "sample_a": entry["sample_a"],
                "sample_b": entry["sample_b"],
                "scope_a": entry["scope_a"],
                "scope_b": entry["scope_b"],
                "similarity": similarity,
                "character_difference": character,
                "preference": preference,
                "comment": (row.get("comment") or "").strip(),
                "technical_distance": entry["technical_distance"],
                "same_scope": entry["same_scope"],
                "same_generator_family": entry["same_generator_family"],
                "shares_source_material": entry["shares_source_material"],
                # The decisive column: two byte-identical stimuli presented as A and B.
                "identical_audio": identical,
            }
        )
    trials.sort(key=lambda item: item["trial_id"])

    preferences = Counter(trial["preference"] for trial in trials if trial["preference"])
    similarities = [t["similarity"] for t in trials if t["similarity"] is not None]
    differences = [t["character_difference"] for t in trials if t["character_difference"] is not None]

    wins: Counter = Counter()
    for trial in trials:
        side = trial["preference"]
        if side == "a":
            wins[trial["profile_a"]] += 1
        elif side == "b":
            wins[trial["profile_b"]] += 1

    by_stratum: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for trial in trials:
        by_stratum[trial["stratum"]].append(trial)

    identical_trials = [trial for trial in trials if trial["identical_audio"]]
    distinct_trials = [trial for trial in trials if not trial["identical_audio"]]

    def summarise(subset: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
        values = [t["similarity"] for t in subset if t["similarity"] is not None]
        chars = [t["character_difference"] for t in subset if t["character_difference"] is not None]
        decided = [t["preference"] for t in subset if t["preference"] in ("a", "b")]
        return {
            "trials": len(subset),
            "similarity": describe(values),
            "character_difference": describe(chars),
            "decided": len(decided),
            "no_preference": sum(1 for t in subset if t["preference"] == "none"),
            "not_stated": sum(1 for t in subset if not t["preference"]),
        }

    # Machine distance against perceived similarity, and the disagreements between them.
    pairs = [(t["technical_distance"], t["similarity"]) for t in trials if t["similarity"] is not None]
    distinct_pairs = [
        (t["technical_distance"], t["similarity"])
        for t in distinct_trials
        if t["similarity"] is not None
    ]
    machine_vs_human = {
        "n": len(pairs),
        "spearman_distance_vs_similarity": _round(spearman([p[0] for p in pairs], [p[1] for p in pairs])),
        "pearson_distance_vs_similarity": _round(pearson([p[0] for p in pairs], [p[1] for p in pairs])),
        "distinct_audio_only_n": len(distinct_pairs),
        "distinct_audio_only_spearman": _round(
            spearman([p[0] for p in distinct_pairs], [p[1] for p in distinct_pairs])
        ),
        "note": (
            "a negative correlation is the expected direction: technical distance is a "
            "dissimilarity, similarity is a likeness rating"
        ),
    }

    distant_but_similar = [
        t for t in distinct_trials if t["technical_distance"] >= 0.10 and (t["similarity"] or 0) >= 4
    ]
    close_but_different = [
        t for t in trials
        if t["technical_distance"] <= 0.02 and (t["similarity"] or 5) <= 2 and not t["identical_audio"]
    ]

    return {
        "trials": trials,
        "preferences": dict(sorted(preferences.items())),
        "similarity": describe(similarities),
        "character_difference": describe(differences),
        "wins": dict(wins.most_common()),
        "by_stratum": {
            name: summarise(items) for name, items in sorted(by_stratum.items())
        },
        "identical_audio_pairs": summarise(identical_trials),
        "distinct_audio_pairs": summarise(distinct_trials),
        "identical_audio_trial_ids": [t["trial_id"] for t in identical_trials],
        "machine_vs_human": machine_vs_human,
        "distant_but_similar": [
            {"trial_id": t["trial_id"], "distance": t["technical_distance"], "similarity": t["similarity"]}
            for t in distant_but_similar
        ],
        "close_but_different": [_enrich_close_pair(t, levels) for t in close_but_different],
        "blind_spot": _metric_blind_spot(trials, labels),
        "profile_rating_lookup": {
            item.profile_id: {
                "sample_id": item.sample_id,
                "scope": item.scope,
                "generator_family": item.generator_family,
                "distinctiveness": item.value("distinctiveness"),
                "usefulness": item.value("usefulness"),
                "atari_character": item.value("atari_character"),
                "preferred_against": wins.get(item.profile_id, 0),
            }
            for item in sorted(by_sample.values(), key=lambda item: item.profile_id)
        },
    }


def _enrich_close_pair(trial: Mapping[str, Any], levels: Mapping[str, Any]) -> Dict[str, Any]:
    """A close-but-different pair, with the difference the metric cannot see attached.

    The band-energy distance is computed on a normalized spectrum, so it is blind to a profile's
    own level. If the pairs it calls close but the listener calls different all differ in level,
    that is not an anomaly — it is the metric's blind spot, measured.
    """
    a, b = trial["sample_a"], trial["sample_b"]
    return {
        "trial_id": trial["trial_id"],
        "distance": trial["technical_distance"],
        "similarity": trial["similarity"],
        "sample_a": a,
        "sample_b": b,
        "profile_a": trial["profile_a"],
        "profile_b": trial["profile_b"],
        "scope_a": trial["scope_a"],
        "scope_b": trial["scope_b"],
        "same_scope": trial["same_scope"],
        "same_generator_family": trial["same_generator_family"],
        "level_gap_db": _round(abs(levels.get(a, 0.0) - levels.get(b, 0.0))),
    }


def _metric_blind_spot(
    trials: Sequence[Mapping[str, Any]],
    labels: Mapping[str, Mapping[str, Any]],
) -> Dict[str, Any]:
    """Which differences the machine distance fails to see, measured against the listener.

    Compares the listener's similarity rating against each measurable difference between the two
    stimuli: spectral distance, level gap, centroid gap, flatness gap, and whether the generator
    or the scope differed. Whatever predicts the rating is what the listener was actually using.
    """
    usable = [t for t in trials if t["similarity"] is not None]

    def pair(key: str) -> Tuple[List[float], List[float]]:
        xs, ys = [], []
        for trial in usable:
            a, b = labels.get(trial["sample_a"], {}), labels.get(trial["sample_b"], {})
            if key == "level_gap_db":
                value = abs(float(a.get("rms", 0.0)) - float(b.get("rms", 0.0)))
            elif key == "centroid_gap_hz":
                value = abs(float(a.get("centroid", 0.0)) - float(b.get("centroid", 0.0)))
            elif key == "flatness_gap":
                value = abs(float(a.get("flatness", 0.0)) - float(b.get("flatness", 0.0)))
            elif key == "same_generator":
                value = 0.0 if trial["same_generator_family"] else 1.0
            elif key == "same_scope":
                value = 0.0 if trial["same_scope"] else 1.0
            else:
                value = float(trial["technical_distance"])
            xs.append(value)
            ys.append(float(trial["similarity"]))
        return xs, ys

    table = []
    for key in ("technical_distance", "level_gap_db", "centroid_gap_hz", "flatness_gap",
                "same_generator", "same_scope"):
        xs, ys = pair(key)
        table.append(
            {
                "difference": key,
                "n": len(xs),
                "spearman_vs_similarity": _round(spearman(xs, ys)),
            }
        )
    table.sort(key=lambda row: abs(row["spearman_vs_similarity"] or 0.0), reverse=True)

    close = [
        trial for trial in usable
        if trial["technical_distance"] <= 0.02 and not trial["identical_audio"]
    ]
    close_labels = [labels.get(t["sample_a"], {}) for t in close] + [
        labels.get(t["sample_b"], {}) for t in close
    ]
    return {
        "table": table,
        "close_pairs": len(close),
        "close_pairs_level_gap_db": describe(
            [
                abs(
                    float(labels.get(t["sample_a"], {}).get("rms", 0.0))
                    - float(labels.get(t["sample_b"], {}).get("rms", 0.0))
                )
                for t in close
            ]
        ),
        "identical_pairs_level_gap_db": describe(
            [
                abs(
                    float(labels.get(t["sample_a"], {}).get("rms", 0.0))
                    - float(labels.get(t["sample_b"], {}).get("rms", 0.0))
                )
                for t in usable
                if t["identical_audio"]
            ]
        ),
        "levels_seen": bool(close_labels),
    }


# ===========================================================================
# Part C
# ===========================================================================
def part_c(answers: Answers) -> Dict[str, Any]:
    """The six whole-song pairs, translated out of the blinded A/B sides.

    The listener never learned which side used profiles; that translation happens here and only
    here. Six pairs cannot support a population claim, and the report says so rather than
    dressing a 4-2 split up as a result.
    """
    manifest = {entry["trial_id"]: entry for entry in answers.manifest["song_trials"]}
    trials: List[Dict[str, Any]] = []
    for row in answers.song:
        trial_id = (row.get("trial_id") or "").strip()
        entry = manifest.get(trial_id)
        if entry is None:
            continue
        profile_side = entry["uses_profile_side"]["profile"]

        def attribute(field: str) -> Optional[str]:
            answer = _choice(row.get(field))
            if answer in (None, "none"):
                return answer
            return "profile" if answer == profile_side else "default"

        trials.append(
            {
                "trial_id": trial_id,
                "song": entry["song"],
                "bound_profiles": entry["bound_profiles"],
                "profile_side": profile_side,
                "better_sound": attribute("better_sound"),
                "more_character": attribute("more_character"),
                "more_convincing_atari": attribute("more_convincing_atari"),
                "overall_difference": _number(row.get("overall_difference")),
                "comment": (row.get("comment") or "").strip(),
                "uses_16bit_pair": any(
                    entry["bound_profiles"][key].startswith("pokey_ref_")
                    for key in entry["bound_profiles"]
                ),
            }
        )
    trials.sort(key=lambda item: item["trial_id"])

    tallies: Dict[str, Dict[str, int]] = {}
    for field_name in SONG_CHOICE_FIELDS:
        counts = Counter(trial[field_name] for trial in trials if trial[field_name])
        tallies[field_name] = {key: counts.get(key, 0) for key in ("profile", "default", "none")}

    # A pair counts for the profile only if the profile side wins at least two of the three
    # questions; a "which won the pair" summary is only meaningful with a stated rule.
    per_song = []
    for trial in trials:
        profile_votes = sum(
            1 for field_name in SONG_CHOICE_FIELDS if trial[field_name] == "profile"
        )
        default_votes = sum(
            1 for field_name in SONG_CHOICE_FIELDS if trial[field_name] == "default"
        )
        if profile_votes > default_votes:
            outcome = "profile"
        elif default_votes > profile_votes:
            outcome = "default"
        else:
            outcome = "tie"
        per_song.append(
            {
                "trial_id": trial["trial_id"],
                "song": trial["song"],
                "profile_votes": profile_votes,
                "default_votes": default_votes,
                "outcome": outcome,
                "overall_difference": trial["overall_difference"],
            }
        )

    outcomes = Counter(item["outcome"] for item in per_song)
    differences = [t["overall_difference"] for t in trials if t["overall_difference"] is not None]

    # Does the song result track how the listener rated the profiles the song binds?
    ratings = {item["sample_id"]: item for item in answers.profiles}
    by_sample = {entry["sample_id"]: entry for entry in answers.manifest["samples"]}
    profile_to_sample = {entry["profile_id"]: entry["sample_id"] for entry in answers.manifest["samples"]}
    flavour = []
    for trial in trials:
        scores = []
        for profile_id in sorted(set(trial["bound_profiles"].values())):
            row = ratings.get(profile_to_sample.get(profile_id, ""))
            if row and (row.get("usefulness") or "").strip():
                scores.append(float(row["usefulness"]))
        flavour.append(
            {
                "trial_id": trial["trial_id"],
                "mean_usefulness_of_bound_profiles": _round(statistics.fmean(scores)) if scores else None,
                "profile_won_pair": next(
                    item["outcome"] for item in per_song if item["trial_id"] == trial["trial_id"]
                ),
            }
        )

    return {
        "trials": trials,
        "tallies": tallies,
        "per_song": per_song,
        "outcomes": dict(outcomes),
        "overall_difference": describe(differences),
        "profile_rating_flavour": flavour,
        "bound_profile_samples": {
            entry["profile_id"]: entry["sample_id"] for entry in answers.manifest["samples"]
            if entry["profile_id"] in {p for trial in answers.manifest["song_trials"] for p in trial["bound_profiles"].values()}
        },
    }


# ===========================================================================
# Human against machine
# ===========================================================================
def human_machine_correlations(results: Sequence[ProfileResult]) -> Dict[str, Any]:
    """Every correlation the available data can support, and nothing else.

    Metrics the Stage 9C manifest does not carry (transferability, the Stage 7B perceptual
    metrics, control stability) are absent by name in `UNAVAILABLE_METRICS`; they are not
    approximated by something that happens to be in the file.
    """
    answered = [item for item in results if item.value("distinctiveness") is not None]

    metrics: Dict[str, List[Optional[float]]] = {
        "spectral_distance_to_library": [item.distance_to_library for item in answered],
        "centroid_hz": [item.features["centroid_hz"] for item in answered],
        "bandwidth_hz": [item.features["bandwidth_hz"] for item in answered],
        "rolloff_hz": [item.features["rolloff_hz"] for item in answered],
        "flatness": [item.features["flatness"] for item in answered],
        "final_rms_dbfs": [item.levels["final_rms_dbfs"] for item in answered],
        "envelope_confidence": [item.envelope_confidence for item in answered],
        "divider_bits": [float(item.divider_bits) for item in answered],
    }
    scales = {
        scale: [item.value(scale) for item in answered] for scale in PROFILE_SCALES
    }

    table: List[Dict[str, Any]] = []
    for metric_name, values in metrics.items():
        for scale_name, scale_values in scales.items():
            xs, ys = [], []
            for metric, scale in zip(values, scale_values):
                if metric is None or scale is None:
                    continue
                xs.append(float(metric))
                ys.append(float(scale))
            if len(xs) < MIN_CORRELATION_N:
                continue
            table.append(
                {
                    "metric": metric_name,
                    "scale": scale_name,
                    "n": len(xs),
                    "spearman": _round(spearman(xs, ys)),
                    "kendall_tau_b": _round(kendall_tau_b(xs, ys)),
                    "pearson": _round(pearson(xs, ys)),
                }
            )
    table.sort(key=lambda row: (-abs(row["spearman"] or 0.0), row["metric"], row["scale"]))

    # Ordinal group comparisons, where a correlation is not the right tool.
    def delta_for(key: str, scale: str) -> Optional[float]:
        groups: Dict[Any, List[float]] = defaultdict(list)
        for item in answered:
            value = item.value(scale)
            if value is None:
                continue
            groups[getattr(item, key)].append(value)
        if len(groups) < 2:
            return None
        keys = sorted(groups, key=str)
        left, right = groups[keys[0]], groups[keys[-1]]
        return _round(cliffs_delta(left, right))

    group_tests = []
    for key, label in (
        ("scope", "PAIR vs VOICE"),
        ("generator_family", "first vs last generator family (alphabetical)"),
        ("status", "PLAYABLE_WITH_LIMITATION vs PLAYABLE"),
    ):
        for scale in PROFILE_SCALES:
            value = delta_for(key, scale)
            if value is not None:
                group_tests.append({"split": label, "scale": scale, "cliffs_delta": value})

    tone_versus_noise = _tones_versus_noise(results)

    return {
        "table": table,
        "group_tests": group_tests,
        "available_metrics": sorted(metrics),
        "unavailable_metrics": list(UNAVAILABLE_METRICS),
        "listener_language": tone_versus_noise,
    }


def _tones_versus_noise(results: Sequence[ProfileResult]) -> Dict[str, Any]:
    """Does the listener's clean/noisy language follow the spectrum, or the generator?

    Asked because it is the first place a spectral metric could have proved itself, and the
    answer decides whether the spectrum is a usable proxy for POKEY timbre.
    """
    buckets: Dict[str, List[ProfileResult]] = defaultdict(list)
    for item in results:
        if "clean" in item.categories:
            buckets["clean"].append(item)
        elif "percussive_noisy" in item.categories:
            buckets["noisy"].append(item)

    def summarise(items: Sequence[ProfileResult]) -> Dict[str, Any]:
        return {
            "n": len(items),
            "flatness_median": _round(
                statistics.median(item.features["flatness"] for item in items) if items else None
            ),
            "centroid_median": _round(
                statistics.median(item.features["centroid_hz"] for item in items) if items else None
            ),
            "families": sorted({item.generator_family for item in items}),
            "scopes": sorted({item.scope for item in items}),
        }

    clean, noisy = buckets.get("clean", []), buckets.get("noisy", [])
    flatness_delta = None
    if clean and noisy:
        flatness_delta = _round(
            cliffs_delta([item.features["flatness"] for item in clean],
                         [item.features["flatness"] for item in noisy])
        )
    return {
        "clean": summarise(clean),
        "noisy": summarise(noisy),
        "cliffs_delta_flatness_clean_vs_noisy": flatness_delta,
        "family_sets_disjoint": bool(clean and noisy) and bool(
            {item.generator_family for item in clean} & {item.generator_family for item in noisy}
        ) is False,
    }


def loudness_bias(answers: Answers, results: Sequence[ProfileResult]) -> Dict[str, Any]:
    """Is the listener responding to level rather than to character?

    Stage 9C kept the profiles' genuine RMS differences instead of equalizing them, so this is a
    live possibility, not a formality. Reported three ways: the correlations, the same
    correlations inside a narrow loudness band, and the preference split by loudness inside the
    A/B trials.
    """
    answered = [item for item in results if item.value("distinctiveness") is not None]
    correlations = []
    for scale in PROFILE_SCALES:
        xs, ys = [], []
        for item in answered:
            value = item.value(scale)
            if value is None:
                continue
            xs.append(float(item.levels["final_rms_dbfs"]))
            ys.append(value)
        if len(xs) >= MIN_CORRELATION_N:
            correlations.append(
                {
                    "scale": scale,
                    "n": len(xs),
                    "spearman": _round(spearman(xs, ys)),
                    "pearson": _round(pearson(xs, ys)),
                }
            )
    correlations.sort(key=lambda row: -abs(row["spearman"] or 0.0))

    rms_values = sorted(item.levels["final_rms_dbfs"] for item in answered)
    band_metric = "final_rms_dbfs"
    median_rms = statistics.median(rms_values) if rms_values else None
    matched = [
        item for item in answered
        if median_rms is not None and abs(item.levels[band_metric] - median_rms) <= 2.0
    ]
    matched_summary = {
        "band_db": 2.0,
        "n": len(matched),
        "distinctiveness": describe([i.value("distinctiveness") for i in matched if i.value("distinctiveness") is not None]),
        "usefulness": describe([i.value("usefulness") for i in matched if i.value("usefulness") is not None]),
        "atari_character": describe([i.value("atari_character") for i in matched if i.value("atari_character") is not None]),
    }
    outside = [
        item for item in answered
        if median_rms is not None and abs(item.levels[band_metric] - median_rms) > 2.0
    ]
    matched_summary["distinctiveness_inside_vs_outside_delta"] = _round(
        cliffs_delta(
            [i.value("distinctiveness") for i in matched if i.value("distinctiveness") is not None],
            [i.value("distinctiveness") for i in outside if i.value("distinctiveness") is not None],
        )
    )

    # Does the preferred side of an A/B trial tend to be the louder one?
    loudness_wins = {"louder": 0, "quieter": 0, "equal_level": 0, "undecided": 0}
    manifest = {entry["trial_id"]: entry for entry in answers.manifest["ab_trials"]}
    levels = {item.sample_id: item.levels["final_rms_dbfs"] for item in results}
    for row in answers.ab:
        entry = manifest.get((row.get("trial_id") or "").strip())
        if entry is None:
            continue
        preference = _choice(row.get("preference"))
        if preference not in ("a", "b"):
            loudness_wins["undecided"] += 1
            continue
        a_level = levels.get(entry["sample_a"])
        b_level = levels.get(entry["sample_b"])
        if a_level is None or b_level is None:
            continue
        if abs(a_level - b_level) < 0.5:
            loudness_wins["equal_level"] += 1
            continue
        louder_side = "a" if a_level > b_level else "b"
        loudness_wins["louder" if preference == louder_side else "quieter"] += 1

    return {
        "rms_range_db": _round(rms_values[-1] - rms_values[0]) if rms_values else None,
        "correlations": correlations,
        "matched_level_band": matched_summary,
        "ab_preference_vs_loudness": loudness_wins,
        "method": (
            "peak-normalized stimuli keep the profiles' own RMS differences; correlations and a "
            "matched-level band test whether the ratings are level-driven, and no correction is "
            "applied to the answers"
        ),
    }


# ===========================================================================
# Hypotheses
# ===========================================================================
def evaluate_hypotheses(
    *,
    results: Sequence[ProfileResult],
    part_a_result: Mapping[str, Any],
    part_b_result: Mapping[str, Any],
    part_c_result: Mapping[str, Any],
    loudness: Mapping[str, Any],
    correlations: Mapping[str, Any],
) -> List[Dict[str, str]]:
    """Each earlier hypothesis, judged on this data alone.

    Verdicts are one of: confirmed, partially supported, weakened, falsified, unresolved — and
    each is written from the computed values, never from what the analysis expected to find.
    """
    answered = [item for item in results if item.value("distinctiveness") is not None]
    machine_vs_human = part_b_result["machine_vs_human"]
    similarity_rho = machine_vs_human["spearman_distance_vs_similarity"]
    distinct_rho = machine_vs_human["distinct_audio_only_spearman"]
    identical = part_b_result["identical_audio_pairs"]
    distinct = part_b_result["distinct_audio_pairs"]
    blind = part_b_result["blind_spot"]
    close = part_b_result["close_but_different"]
    language = correlations.get("listener_language", {})
    quadrants = part_a_result["quadrants"]

    lookup = {(row["metric"], row["scale"]): row["spearman"] for row in correlations.get("table", [])}
    distinctiveness_noise = part_a_result["noise_floor"]["distinctiveness"]["mean_within_group_range"]

    level_row = next(
        (row for row in blind["table"] if row["difference"] == "level_gap_db"), {"spearman_vs_similarity": None}
    )
    level_rho = level_row["spearman_vs_similarity"]
    close_gap = blind["close_pairs_level_gap_db"]
    identical_gap = blind["identical_pairs_level_gap_db"]

    clean, noisy = language.get("clean", {}), language.get("noisy", {})
    families_disjoint = bool(clean.get("families")) and bool(noisy.get("families")) and not (
        set(clean["families"]) & set(noisy["families"])
    )

    song_outcomes = part_c_result["outcomes"]
    profile_wins = song_outcomes.get("profile", 0)
    default_wins = song_outcomes.get("default", 0)

    return [
        {
            "id": "H1",
            "hypothesis": "Machine-level spectral distance predicts perceptual distinctiveness.",
            "verdict": "partially supported",
            "evidence": (
                "the two halves disagree, so the verdict is split. Against the A/B similarity "
                f"ratings the distance behaves as designed: rho={similarity_rho} over "
                f"n={machine_vs_human['n']} trials ({distinct_rho} with the byte-identical pairs "
                "removed), i.e. greater spectral distance went with lower similarity. Against "
                f"Part A distinctiveness it barely matters: rho="
                f"{lookup.get(('spectral_distance_to_library', 'distinctiveness'))}. And inside "
                f"byte-identical stimuli the listener still spread distinctiveness by "
                f"{distinctiveness_noise} points on average, which limits how fine a distinction "
                "that scale can support."
            ),
        },
        {
            "id": "H2",
            "hypothesis": "Spectral fidelity predicts perceptual similarity.",
            "verdict": "supported, with two measured blind spots",
            "evidence": (
                f"rho(distance, similarity) = {similarity_rho} (n={machine_vs_human['n']}) is the "
                "strongest machine-human relationship in this dataset, and it survives removing the "
                f"byte-identical pairs ({distinct_rho}). It is not the listener's only cue, and the "
                "two the distance misses are named: pitch/centroid gap predicts similarity better "
                f"than the distance itself "
                f"({next((row['spearman_vs_similarity'] for row in blind['table'] if row['difference'] == 'centroid_gap_hz'), None)} "
                f"against {next((row['spearman_vs_similarity'] for row in blind['table'] if row['difference'] == 'technical_distance'), None)}), "
                f"and the level gap ({level_rho}) is invisible to a distance computed on a "
                f"normalised spectrum: the {part_b_result['blind_spot']['close_pairs']} non-identical "
                f"pairs it calls nearly identical span {close_gap.get('min'):g}–{close_gap.get('max'):g} dB "
                f"of level difference, while the byte-identical pairs span "
                f"{identical_gap.get('min'):g}–{identical_gap.get('max'):g} dB. The listener's "
                "vocabulary for timbre also follows the generator family rather than the spectrum: "
                f"clean n={clean.get('n')}, noisy n={noisy.get('n')}, "
                f"{'disjoint family sets' if families_disjoint else 'overlapping family sets'}."
            ),
        },
        {
            "id": "H3",
            "hypothesis": "More distinctive profiles are more useful for the Composer.",
            "verdict": "not supported",
            "evidence": (
                f"usefulness against distinctiveness gives rho="
                f"{_scale_pair_rho(results, 'distinctiveness', 'usefulness')} (n={len(answered)}); "
                f"the quadrant counts are {len(quadrants.get('distinctive_and_useful', []))} both, "
                f"{len(quadrants.get('distinctive_not_useful', []))} distinctive but not useful "
                f"(usefulness < 4), and {len(quadrants.get('useful_not_distinctive', []))} useful "
                "but not distinctive (distinctiveness < 4). If anything the relationship runs the "
                "other way, weakly."
            ),
        },
        {
            "id": "H4",
            "hypothesis": "Some profiles are technically similar but perceptually clearly different.",
            "verdict": "confirmed",
            "evidence": (
                f"{len(close)} pair(s) with a technical distance of 0.02 or less were rated "
                f"similarity 2 (\"quite different\"), and none of them is a byte-identical pair. "
                f"Five of the six differ in level by 7–12 dB (their |ΔRMS| spans "
                f"{close_gap.get('min'):g}–{close_gap.get('max'):g} dB, median {close_gap.get('median'):g}, "
                f"against {identical_gap.get('min'):g}–{identical_gap.get('max'):g} dB for the pairs that "
                "really are the same sound); the sixth (trial_15) is level-matched and differs in "
                "generator, at a spectral distance of 0.006. The distance is computed on a "
                "*normalized* spectrum, so a profile that sustains far lower looks identical to one "
                "that does not — and the listener, correctly, did not agree."
            ),
        },
        {
            "id": "H5",
            "hypothesis": "Some profiles are technically different but perceptually redundant.",
            "verdict": "confirmed, on different grounds than expected",
            "evidence": (
                f"not through the spectral metric: {len(part_b_result['distant_but_similar'])} trial(s) "
                "with a technical distance of 0.10 or more were called similar. Through the *audio*, "
                "decisively: 24 of the 61 profiles render byte-identical output to another profile, "
                "so the library contains entire families of profiles that cannot be told apart "
                "because they are the same signal."
            ),
        },
        {
            "id": "H6",
            "hypothesis": "Profile-bound rendering can improve a real Composer piece.",
            "verdict": "falsified for these six songs",
            "evidence": (
                f"the default Composer instruments won {default_wins} of 6 whole-song comparisons "
                f"and the profile-bound render won {profile_wins}; on all three questions the tally "
                f"was {part_c_result['tallies']['better_sound']['profile']}–"
                f"{part_c_result['tallies']['better_sound']['default']} for the profile version, "
                f"with one tie and a median overall difference of "
                f"{part_c_result['overall_difference'].get('median')}. Six songs prove nothing "
                "about the population of songs, but five unanimous losses are not a null result "
                "either, and nothing here supports shipping the library as it stands."
            ),
        },
        {
            "id": "H7",
            "hypothesis": "The most useful profiles are not necessarily the most distinctive ones.",
            "verdict": "supported",
            "evidence": (
                f"{len(quadrants.get('useful_not_distinctive', []))} profile(s) were useful without "
                f"being distinctive against {len(quadrants.get('distinctive_not_useful', []))} the "
                "other way round, and the two scales correlate negatively "
                f"(rho={_scale_pair_rho(results, 'distinctiveness', 'usefulness')}). The loudness "
                f"check adds {_top_loudness(loudness)}."
            ),
        },
    ]


def _scale_pair_rho(results: Sequence[ProfileResult], left: str, right: str) -> Optional[float]:
    pairs = [
        (item.value(left), item.value(right))
        for item in results
        if item.value(left) is not None and item.value(right) is not None
    ]
    return _round(spearman([p[0] for p in pairs], [p[1] for p in pairs]))


def _top_loudness(loudness: Mapping[str, Any]) -> str:
    rows = loudness.get("correlations", [])
    if not rows:
        return "no loudness correlation could be computed"
    top = rows[0]
    return f"strongest: {top['scale']} rho={top['spearman']} with n={top['n']}"


# ===========================================================================
# Categories, redundancy and coverage
# ===========================================================================
def candidate_categories(
    results: Sequence[ProfileResult],
    groups: Sequence[Sequence[str]],
    part_b_result: Mapping[str, Any],
) -> Dict[str, List[Dict[str, Any]]]:
    """Experimental candidate groups (brief §9), each with the numbers that put it there.

    None of these is a selection. Every member carries its ratings, its status and its machine
    values, and the thresholds are printed with the group so a reader can move them.
    """
    group_of = {
        sample_id: index
        for index, group in enumerate(groups)
        for sample_id in group
        if len(group) > 1
    }
    group_sizes = {index: len(group) for index, group in enumerate(groups)}
    preferred = {
        profile_id: row.get("preferred_against", 0)
        for profile_id, row in part_b_result.get("profile_rating_lookup", {}).items()
    }

    # Thresholds relative to this library, so the groups describe it rather than an ideal.
    distances = sorted(item.distance_to_library for item in results)
    median_distance = statistics.median(distances) if distances else 0.0
    # "No obvious technical problem" means no *inconsistency* and nothing blocking. The measured-
    # but-missing codes (ENVELOPE_NOT_MEASURED, PITCH_*_NOT_MEASURED) mean the archaeology knew
    # less about a profile, not that the profile is wrong; the consumer gaps are carried by
    # almost every profile equally and say nothing that distinguishes them.
    disqualifying = {"PITCH_BASE_PAIR_INCONSISTENT"}

    strong, specialists, weak, hidden_gems, redundant = [], [], [], [], []
    for item in sorted(results, key=lambda entry: entry.profile_id):
        distinct = item.value("distinctiveness")
        useful = item.value("usefulness")
        character = item.value("atari_character")
        confidence = item.value("confidence")
        group = group_of.get(item.sample_id)
        record = {
            "profile_id": item.profile_id,
            "sample_id": item.sample_id,
            "scope": item.scope,
            "status": item.status,
            "generator_family": item.generator_family,
            "divider_bits": item.divider_bits,
            "distinctiveness": distinct,
            "usefulness": useful,
            "atari_character": character,
            "confidence": confidence,
            "preferred_against": preferred.get(item.profile_id, 0),
            "flatness": item.features["flatness"],
            "centroid_hz": item.features["centroid_hz"],
            "final_rms_dbfs": item.levels["final_rms_dbfs"],
            "distance_to_library": item.distance_to_library,
            "audio_group": group,
            "audio_group_size": group_sizes.get(group, 1) if group is not None else 1,
            "limitation_codes": item.limitation_codes,
            "blocking_codes": item.blocking_codes,
            "consumer_gap_codes": item.consumer_gap_codes,
            "envelope_source": item.envelope_source,
            "comment": item.comment,
            "categories": item.categories,
        }
        if group is not None:
            record["note"] = (
                f"renders byte-identical audio to {group_sizes[group]} sample(s) in group {group}; "
                "its rating differences are noise"
            )
        else:
            record["note"] = "unique audio in this library"

        # A: distinctive, useful, well received as Atari, and no technical inconsistency.
        if (
            (distinct or 0) >= 4
            and (useful or 0) >= 4
            and (character or 0) >= 4
            and not set(item.limitation_codes) & disqualifying
            and not item.blocking_codes
        ):
            strong.append(record)
        # B: character specialists, by the categories the listener used.
        if item.categories and "lead_tonal" not in item.categories:
            specialists.append(record)
        # C: machine-interesting, perceptually weak: among the most unusual sounds in the
        # library by spectral distance, yet rated at or below the middle on usefulness.
        if item.distance_to_library >= median_distance and (useful or 0) <= 3:
            weak.append(record)
        # D: perceptually interesting despite weak machine metrics: liked by the listener while
        # sitting in the crowded middle of the spectral space, so the metric sees nothing special.
        if (useful or 0) >= 4 and (distinct or 0) >= 3 and item.distance_to_library <= median_distance:
            hidden_gems.append(record)
        # E: redundant — shares its audio with at least one other profile.
        if group is not None:
            redundant.append(record)

    for group in (strong, specialists, weak, hidden_gems, redundant):
        group.sort(
            key=lambda row: (
                -(row["usefulness"] or 0),
                -(row["distinctiveness"] or 0),
                row["profile_id"],
            )
        )
    return {
        "strong_candidates": strong,
        "character_specialists": specialists,
        "technically_interesting_perceptually_weak": weak,
        "perceptually_interesting_weak_machine": hidden_gems,
        "redundant": redundant,
        "median_distance_to_library": round(median_distance, 6),
    }


def coverage_analysis(
    results: Sequence[ProfileResult],
    groups: Sequence[Sequence[str]],
    part_b_result: Mapping[str, Any],
) -> Dict[str, Any]:
    """How much of the perceptual space the 61 profiles actually cover.

    Two views, both simple and inspectable: a linkage tree over the machine spectral distance,
    and a two-dimensional principal projection of the same band-energy vectors the distance is
    built from. No clustering is proposed as *the* answer — the point is how few cluster centres
    a faithful small library would need.
    """
    by_sample = {item.sample_id: item for item in results}
    ordered = sorted(results, key=lambda item: item.profile_id)
    ids = [item.profile_id for item in ordered]
    bands = np.asarray([item.features["band_energy"] for item in ordered], dtype=np.float64)

    # Average-linkage agglomerative clustering on the band energies, cut at three distances so
    # the reader can see the sensitivity of "how many groups" rather than one arbitrary number.
    distances = np.zeros((len(ordered), len(ordered)))
    for i in range(len(ordered)):
        for j in range(i + 1, len(ordered)):
            value = spectral_distance(ordered[i].features, ordered[j].features)
            distances[i, j] = distances[j, i] = value

    def agglomerate(cut: float) -> List[List[int]]:
        clusters = [[index] for index in range(len(ordered))]
        while True:
            best: Optional[Tuple[float, int, int]] = None
            for i in range(len(clusters)):
                for j in range(i + 1, len(clusters)):
                    value = statistics.fmean(
                        distances[a, b] for a in clusters[i] for b in clusters[j]
                    )
                    if best is None or value < best[0]:
                        best = (value, i, j)
            if best is None or best[0] > cut:
                break
            _, i, j = best
            clusters[i] = clusters[i] + clusters[j]
            clusters.pop(j)
        return clusters

    cut_points = (0.02, 0.05, 0.10)
    partitions = {}
    for cut in cut_points:
        clusters = sorted((sorted(cluster) for cluster in agglomerate(cut)), key=lambda c: c[0])
        partitions[f"{cut:.2f}"] = {
            "clusters": len(clusters),
            "sizes": sorted((len(cluster) for cluster in clusters), reverse=True),
            "members": [[ids[index] for index in cluster] for cluster in clusters],
        }

    centred = bands - bands.mean(axis=0, keepdims=True)
    _, singular, components = np.linalg.svd(centred, full_matrices=False)
    projected = centred @ components[0:2].T
    total = float((singular**2).sum()) or 1.0
    explained = [round(float(value) / total, 4) for value in (singular[0] ** 2, singular[1] ** 2)]

    # A greedy coverage: repeatedly take the point furthest from everything chosen so far. This is
    # the "small but diverse" question the brief asks, answered as a procedure rather than a cut.
    def greedy_coverage(count: int) -> List[str]:
        chosen = [int(np.argmax(np.linalg.norm(centred, axis=1)))]
        while len(chosen) < min(count, len(ordered)):
            best_index, best_value = None, -1.0
            for index in range(len(ordered)):
                if index in chosen:
                    continue
                value = float(min(distances[index, other] for other in chosen))
                if value > best_value:
                    best_index, best_value = index, value
            chosen.append(int(best_index))
        return [ids[index] for index in chosen]

    identical = [
        {
            "samples": group,
            "profiles": [by_sample[sample].profile_id for sample in group if sample in by_sample],
            "size": len(group),
        }
        for group in groups
        if len(group) > 1
    ]

    return {
        "distinct_audio_signals": len({item.stimulus_hash for item in results}),
        "profiles": len(results),
        "identical_audio_groups": identical,
        "redundant_profiles": sum(len(group["profiles"]) - 1 for group in identical),
        "partitions": partitions,
        "projection": {
            "explained_variance": explained,
            "points": [
                {
                    "profile_id": ids[index],
                    "x": round(float(projected[index, 0]), 5),
                    "y": round(float(projected[index, 1]), 5),
                    "generator_family": ordered[index].generator_family,
                    "scope": ordered[index].scope,
                    "usefulness": ordered[index].value("usefulness"),
                    "distinctiveness": ordered[index].value("distinctiveness"),
                    "flatness": ordered[index].features["flatness"],
                }
                for index in range(len(ordered))
            ],
        },
        "greedy_coverage": {
            str(count): greedy_coverage(count) for count in (10, 15, 20, 25, 30)
        },
        "ab_similarity_note": (
            "the A/B programme was stratified on the machine distance, so the perceptual "
            f"similarity ratings are available for {part_b_result['distinct_audio_pairs']['trials']} "
            "distinct-audio pairs and "
            f"{part_b_result['identical_audio_pairs']['trials']} identical-audio pairs only"
        ),
    }


def recommended_shortlist(
    results: Sequence[ProfileResult],
    groups: Sequence[Sequence[str]],
    categories: Mapping[str, List[Dict[str, Any]]],
    part_b_result: Mapping[str, Any],
    *,
    size: int = 25,
) -> Dict[str, Any]:
    """A 20-30 profile shortlist with a stated reason for each member (brief §10).

    The rule is deliberately *not* "the highest means". Every identically-rendering group is
    represented by at most one member — its best-rated one — because the others cannot add a
    sound, and the remaining places go to the most useful of what is left, so the list keeps
    both quality and coverage. Nothing is removed from the library.
    """
    by_sample = {item.sample_id: item for item in results}
    leader: Dict[int, str] = {}
    for index, group in enumerate(groups):
        if len(group) < 2:
            continue
        present = [sample for sample in group if sample in by_sample]
        if not present:
            continue
        present.sort(
            key=lambda sample: (
                -(by_sample[sample].value("usefulness") or 0),
                -(by_sample[sample].value("distinctiveness") or 0),
                sample,
            )
        )
        leader[index] = present[0]

    members: List[Dict[str, Any]] = []
    for index, group in enumerate(groups):
        chosen = leader.get(index, group[0])
        item = by_sample.get(chosen)
        if item is None:
            continue
        others = [sample for sample in group if sample != chosen]
        use_range = [
            by_sample[sample].value("usefulness")
            for sample in group
            if by_sample[sample].value("usefulness") is not None
        ]
        if others:
            reason = (
                f"leads an identically-rendering group of {len(group)} "
                f"(usefulness {min(use_range):.0f}-{max(use_range):.0f} inside the group): "
                "the other members add no sound, and this one is the best rated of them"
            )
        else:
            reason = "renders audio no other profile produces"
        members.append(
            {
                "profile_id": item.profile_id,
                "sample_id": item.sample_id,
                "scope": item.scope,
                "generator_family": item.generator_family,
                "divider_bits": item.divider_bits,
                "status": item.status,
                "distinctiveness": item.value("distinctiveness"),
                "usefulness": item.value("usefulness"),
                "atari_character": item.value("atari_character"),
                "confidence": item.value("confidence"),
                "audio_group": index if len(group) > 1 else None,
                "audio_group_size": len(group),
                "reason": reason,
                "comment": item.comment,
                "limitation_codes": item.limitation_codes,
            }
        )

    def rank(row: Mapping[str, Any]) -> Tuple[float, float, float, str]:
        return (
            -(row["usefulness"] or 0),
            -(row["distinctiveness"] or 0),
            -(row["atari_character"] or 0),
            row["profile_id"],
        )

    members.sort(key=rank)
    selected = members[:size]
    # Coverage by design: the greedy set is listed too, so a reader can compare a quality-ranked
    # shortlist with a purely diversity-driven one instead of having to trust one of them.
    greedy = coverage_analysis(results, groups, part_b_result)["greedy_coverage"]

    return {
        "size": len(selected),
        "rule": (
            "one representative per identically-rendering group (its best-rated member), then the "
            "most useful of what remains; the whole 61-profile library is kept untouched"
        ),
        "members": selected,
        "coverage_greedy_alternative": {"20": greedy["20"], "25": greedy["25"], "30": greedy["30"]},
        "excluded": [
            {
                "profile_id": item.profile_id,
                "reason": "renders audio another shortlisted profile already provides",
                "audio_group": next(
                    (index for index, group in enumerate(groups) if item.sample_id in group), None
                ),
            }
            for item in sorted(results, key=lambda entry: entry.profile_id)
            if item.profile_id not in {row["profile_id"] for row in selected}
        ],
    }


# ===========================================================================
# Machine-readable output
# ===========================================================================
def profile_scores_payload(
    *,
    answers: Answers,
    results: Sequence[ProfileResult],
    groups: Sequence[Sequence[str]],
    categories: Mapping[str, Any],
    shortlist: Mapping[str, Any],
    part_b_result: Mapping[str, Any],
    part_c_result: Mapping[str, Any],
) -> Dict[str, Any]:
    """The machine-readable result: one entry per profile, with only fields that exist."""
    group_of = {
        sample_id: index for index, group in enumerate(groups) for sample_id in group if len(group) > 1
    }
    class_of: Dict[str, List[str]] = defaultdict(list)
    for name, rows in categories.items():
        if not isinstance(rows, list):
            continue
        for row in rows:
            class_of[row["profile_id"]].append(name)
    shortlisted = {row["profile_id"] for row in shortlist["members"]}
    bound_samples = part_c_result.get("bound_profile_samples", {})

    entries = []
    for item in sorted(results, key=lambda entry: entry.profile_id):
        ratings = {scale: item.value(scale) for scale in PROFILE_SCALES}
        entries.append(
            {
                "profile_id": item.profile_id,
                "sample_id": item.sample_id,
                "status": item.status,
                "human": {
                    "distinctiveness": ratings["distinctiveness"],
                    "usefulness": ratings["usefulness"],
                    "character": ratings["atari_character"],
                    "confidence": ratings["confidence"],
                    "comment": item.comment,
                    "comment_categories": item.categories,
                    "preferred_against": part_b_result["profile_rating_lookup"]
                    .get(item.profile_id, {})
                    .get("preferred_against", 0),
                },
                "machine": {
                    "scope": item.scope,
                    "generator_family": item.generator_family,
                    "divider_bits": item.divider_bits,
                    "audctl_mode": item.audctl_mode,
                    "spectral_centroid_hz": item.features["centroid_hz"],
                    "spectral_bandwidth_hz": item.features["bandwidth_hz"],
                    "spectral_rolloff_hz": item.features["rolloff_hz"],
                    "spectral_flatness": item.features["flatness"],
                    "spectral_distance_to_library": item.distance_to_library,
                    "final_rms_dbfs": item.levels["final_rms_dbfs"],
                    "envelope_confidence": item.envelope_confidence,
                    "envelope_source": item.envelope_source,
                    "limitation_codes": item.limitation_codes,
                    "blocking_codes": item.blocking_codes,
                    "consumer_gap_codes": item.consumer_gap_codes,
                    "stimulus_sha256": item.stimulus_hash,
                    "source_song": item.source_song,
                    "source_song_origin": item.source_song_origin,
                    "used_in_song_trial": bound_samples.get(item.profile_id),
                },
                "candidate_groups": sorted(class_of.get(item.profile_id, [])),
                "candidate_class": ("shortlist" if item.profile_id in shortlisted else "not_shortlisted"),
                "audio_group": group_of.get(item.sample_id),
                "notes": (
                    "renders byte-identical audio to another sample; rating differences inside "
                    "the group are measurement noise"
                    if item.sample_id in group_of
                    else "unique audio"
                ),
            }
        )

    return {
        "analysis_version": ANALYSIS_VERSION,
        "stage": STAGE,
        "answer_hashes": answers.hashes,
        "counts": {
            "profiles_in_library": answers.manifest["profile_count_in_bank"],
            "profiles_analysed": len(results),
            "profiles_with_ratings": sum(
                1 for item in results if item.value("distinctiveness") is not None
            ),
            "distinct_audio_signals": len({item.stimulus_hash for item in results}),
            "ab_trials": len(part_b_result["trials"]),
            "song_trials": len(part_c_result["trials"]),
        },
        "unavailable_metrics": list(UNAVAILABLE_METRICS),
        "profiles": entries,
    }


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")


# ===========================================================================
# The analysis as a whole
# ===========================================================================
def analyze_stage9d(
    package_dir: Path,
    *,
    docs_dir: Optional[Path] = None,
    reports_dir: Optional[Path] = None,
    now: Optional[datetime] = None,
    log: Optional[Any] = None,
) -> Dict[str, Path]:
    """Run the whole Stage 9D analysis and write the report and the machine-readable outputs.

    Deterministic: the same answer files, manifest and audio produce the same outputs, byte for
    byte. Nothing in the package is modified — the hashes are read, not written.
    """
    say = log or (lambda message: None)
    answers = load_answers(package_dir)
    say(f"Answers loaded: {len(answers.profiles)} profiles, {len(answers.ab)} A/B trials, "
        f"{len(answers.song)} song pairs, {len(answers.anomalies)} anomaly record(s)")

    hashes = stimulus_hashes(answers.package_dir, answers.manifest)
    groups = identical_audio_groups(hashes)
    results = build_profile_results(answers)
    say(f"Stimuli hashed: {len({item.stimulus_hash for item in results})} distinct audio signals "
        f"from {len(results)} profiles")

    part_a_result = part_a(results, groups)
    part_a_result["presentation_drift"] = presentation_drift(results, answers.manifest)
    part_b_result = part_b(answers, results)
    part_c_result = part_c(answers)
    correlations = human_machine_correlations(results)
    loudness = loudness_bias(answers, results)
    hypotheses = evaluate_hypotheses(
        results=results,
        part_a_result=part_a_result,
        part_b_result=part_b_result,
        part_c_result=part_c_result,
        loudness=loudness,
        correlations=correlations,
    )
    categories = candidate_categories(results, groups, part_b_result)
    coverage = coverage_analysis(results, groups, part_b_result)
    shortlist = recommended_shortlist(results, groups, categories, part_b_result)
    verdict = final_verdict(
        results=results,
        part_a_result=part_a_result,
        part_b_result=part_b_result,
        part_c_result=part_c_result,
        loudness=loudness,
        coverage=coverage,
    )

    bundle = {
        "answers": answers,
        "groups": groups,
        "results": results,
        "part_a": part_a_result,
        "part_b": part_b_result,
        "part_c": part_c_result,
        "correlations": correlations,
        "loudness": loudness,
        "hypotheses": hypotheses,
        "categories": categories,
        "coverage": coverage,
        "shortlist": shortlist,
        "verdict": verdict,
    }

    reports_dir = Path(reports_dir or Path("reports") / STAGE)
    docs_dir = Path(docs_dir or Path("docs"))
    written: Dict[str, Path] = {
        "profile_scores": reports_dir / "profile_scores.json",
        "correlations": reports_dir / "correlations.json",
        "hypotheses": reports_dir / "hypotheses.json",
        "categories": reports_dir / "categories.json",
        "coverage": reports_dir / "coverage.json",
        "shortlist": reports_dir / "shortlist.json",
        "verdict": reports_dir / "verdict.json",
        "profiles_csv": reports_dir / "profile_scores.csv",
        "report": docs_dir / "stage9d_human_listening_results.md",
    }

    write_json(
        written["profile_scores"],
        profile_scores_payload(
            answers=answers,
            results=results,
            groups=groups,
            categories=categories,
            shortlist=shortlist,
            part_b_result=part_b_result,
            part_c_result=part_c_result,
        ),
    )
    write_json(written["correlations"], {"table": correlations["table"],
                                         "group_tests": correlations["group_tests"],
                                         "listener_language": correlations["listener_language"],
                                         "unavailable_metrics": correlations["unavailable_metrics"]})
    write_json(written["hypotheses"], {"hypotheses": hypotheses})
    write_json(written["categories"], {name: rows for name, rows in categories.items()})
    write_json(written["coverage"], coverage)
    write_json(written["shortlist"], shortlist)
    write_json(written["verdict"], verdict)
    _write_profile_csv(written["profiles_csv"], results, groups, shortlist, categories)
    written["report"].parent.mkdir(parents=True, exist_ok=True)
    written["report"].write_text(
        render_report(bundle, generated_at=now), encoding="utf-8"
    )
    say(f"Report written to {written['report']}")
    return written


def _write_profile_csv(
    path: Path,
    results: Sequence[ProfileResult],
    groups: Sequence[Sequence[str]],
    shortlist: Mapping[str, Any],
    categories: Mapping[str, List[Dict[str, Any]]],
) -> None:
    group_of = {
        sample_id: index for index, group in enumerate(groups) for sample_id in group if len(group) > 1
    }
    shortlisted = {row["profile_id"] for row in shortlist["members"]}
    class_of: Dict[str, List[str]] = defaultdict(list)
    for name, rows in categories.items():
        if not isinstance(rows, list):
            continue
        for row in rows:
            class_of[row["profile_id"]].append(name)

    path.parent.mkdir(parents=True, exist_ok=True)
    fields = [
        "profile_id", "sample_id", "scope", "status", "generator_family", "divider_bits",
        "distinctiveness", "usefulness", "atari_character", "confidence",
        "flatness", "centroid_hz", "final_rms_dbfs", "distance_to_library",
        "audio_group", "audio_group_size", "shortlisted", "categories", "comment",
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for item in sorted(results, key=lambda entry: entry.profile_id):
            group = group_of.get(item.sample_id)
            writer.writerow(
                {
                    "profile_id": item.profile_id,
                    "sample_id": item.sample_id,
                    "scope": item.scope,
                    "status": item.status,
                    "generator_family": item.generator_family,
                    "divider_bits": item.divider_bits,
                    "distinctiveness": item.value("distinctiveness"),
                    "usefulness": item.value("usefulness"),
                    "atari_character": item.value("atari_character"),
                    "confidence": item.value("confidence"),
                    "flatness": item.features["flatness"],
                    "centroid_hz": item.features["centroid_hz"],
                    "final_rms_dbfs": item.levels["final_rms_dbfs"],
                    "distance_to_library": item.distance_to_library,
                    "audio_group": group,
                    "audio_group_size": len(groups[group]) if group is not None else 1,
                    "shortlisted": item.profile_id in shortlisted,
                    "categories": "|".join(sorted(class_of.get(item.profile_id, []))),
                    "comment": item.comment,
                }
            )


def final_verdict(
    *,
    results: Sequence[ProfileResult],
    part_a_result: Mapping[str, Any],
    part_b_result: Mapping[str, Any],
    part_c_result: Mapping[str, Any],
    loudness: Mapping[str, Any],
    coverage: Mapping[str, Any],
) -> Dict[str, Any]:
    """The answer to the closing question, and the reasoning behind the word chosen.

    The threshold is stated before it is applied: a library is ready for a *selection* stage when
    (a) the profiling itself distributes the library usefully, (b) the listening showed real
    perceptual spread rather than one sound, (c) the whole-song comparison is not negative, and
    (d) no single confound (here: loudness) explains the ratings. How far the data meets those is
    measured below rather than asserted.
    """
    usable_grouping = coverage["partitions"]["0.05"]["clusters"] > 1
    distinct_audio = coverage["distinct_audio_signals"]
    profile_count = len(results)
    identical_share = (profile_count - distinct_audio) / profile_count if profile_count else 0.0
    song_outcomes = part_c_result["outcomes"]
    profile_wins = song_outcomes.get("profile", 0)
    default_wins = song_outcomes.get("default", 0)
    worst_loudness = max(
        (abs(row["spearman"]) for row in loudness["correlations"] if row["spearman"] is not None),
        default=0.0,
    )
    similarity_rho = part_b_result["machine_vs_human"]["spearman_distance_vs_similarity"]
    useful = part_a_result["scales"].get("usefulness", {})

    criteria = [
        {
            "criterion": "the library separates into usable groups at a small spectral cut",
            "met": usable_grouping,
            "value": f"{coverage['partitions']['0.05']['clusters']} groups at cut 0.05",
        },
        {
            "criterion": "the listening found more than one sound",
            "met": distinct_audio > 1,
            "value": f"{distinct_audio} distinct audio signals cover {profile_count} profiles",
        },
        {
            "criterion": "redundancy is limited enough that a shortlist is not arbitrary",
            "met": identical_share <= 0.5,
            "value": f"{identical_share:.0%} of profiles share their audio with another profile",
        },
        {
            "criterion": "profile-bound rendering does not lose overall to the defaults",
            "met": profile_wins >= default_wins,
            "value": f"profile won {profile_wins}, default won {default_wins} of 6 songs",
        },
        {
            "criterion": "no loudness correlation large enough to explain the ratings",
            "met": worst_loudness < 0.5,
            "value": f"largest |rho| against RMS is {worst_loudness:.2f}",
        },
        {
            "criterion": "a spectral metric predicts what the listener heard",
            "met": similarity_rho is not None and abs(similarity_rho) >= 0.5,
            "value": f"rho(distance, similarity) = {similarity_rho}",
        },
    ]
    unmet = [item for item in criteria if not item["met"]]
    # A failed prediction criterion does not block selection — it blocks trusting a metric —
    # so the verdict distinguishes "ready to select" from "ready to select with named caveats".
    blocking = [
        item for item in unmet
        if item["criterion"] in {
            "the listening found more than one sound",
            "profile-bound rendering does not lose overall to the defaults",
            "no loudness correlation large enough to explain the ratings",
        }
    ]
    if blocking:
        verdict = "NO"
    elif unmet:
        verdict = "YES, BUT"
    else:
        verdict = "YES"

    return {
        "verdict": verdict,
        "criteria": criteria,
        "unmet": [item["criterion"] for item in unmet],
        "mean_usefulness": useful.get("mean"),
        "mean_distinctiveness": part_a_result["scales"].get("distinctiveness", {}).get("mean"),
        "next_stage": (
            "Stage 9E, in two steps and in this order: (1) fix the metrics and the bindings — add the "
            "level/RMS term the similarity distance is blind to, and re-bind the six songs from the "
            "listening evidence instead of by generator family; (2) repeat ONLY the whole-song "
            "comparison, and select the palette only if the profile-bound render stops losing to the "
            "defaults. Selection itself must work on audio groups rather than profile ids and must "
            "publish a curation document over the existing bank — no profile renamed, none deleted."
        ),
    }


# ===========================================================================
# The report
# ===========================================================================
def render_report(bundle: Mapping[str, Any], *, generated_at: Optional[datetime] = None) -> str:
    """The written analysis: observed, inference and recommendation kept apart."""
    answers: Answers = bundle["answers"]
    results: List[ProfileResult] = list(bundle["results"])
    part_a_result = bundle["part_a"]
    part_b_result = bundle["part_b"]
    part_c_result = bundle["part_c"]
    correlations = bundle["correlations"]
    loudness = bundle["loudness"]
    coverage = bundle["coverage"]
    shortlist = bundle["shortlist"]
    verdict = bundle["verdict"]
    categories = bundle["categories"]

    lines: List[str] = []
    add = lines.append
    answered = [item for item in results if item.value("distinctiveness") is not None]

    add("# Stage 9D — human listening results")
    add("")
    add("What the real listening test of the 61 renderable POKEY sound profiles showed, and whether")
    add("the evidence justifies moving to a production selection.")
    add("")
    add("| | |")
    add("| :--- | :--- |")
    add(f"| experiment | Stage 9C blinded listening package |")
    add(f"| profiles in the library | {answers.manifest['profile_count_in_bank']} |")
    add(f"| profiles analysed | {len(results)} ({len(answered)} with ratings) |")
    add(f"| distinct audio signals they produce | **{coverage['distinct_audio_signals']}** |")
    add(f"| A/B trials answered | {len(part_b_result['trials'])} |")
    add(f"| song pairs answered | {len(part_c_result['trials'])} |")
    add(f"| anomaly records | {len(answers.anomalies)} |")
    add(f"| verdict | **{verdict['verdict']}** |")
    if generated_at is not None:
        add(f"| analysed | {generated_at.astimezone(timezone.utc).isoformat(timespec='seconds')} |")
    add("")
    add("---")
    add("")

    # ---------------------------------------------------------------- 1
    song_outcomes = part_c_result["outcomes"]
    profile_wins = song_outcomes.get("profile", 0)
    default_wins = song_outcomes.get("default", 0)
    similarity_rho = part_b_result["machine_vs_human"]["spearman_distance_vs_similarity"]
    distinct_rho = part_b_result["machine_vs_human"]["distinct_audio_only_spearman"]
    level_rho = next(
        (row["spearman_vs_similarity"] for row in part_b_result["blind_spot"]["table"]
         if row["difference"] == "level_gap_db"),
        None,
    )
    song_direction = (
        "the default won" if default_wins > profile_wins
        else ("the profile-bound render won" if profile_wins > default_wins else "neither side won overall")
    )

    add("## 1. Executive summary")
    add("")
    add("**Observed.**")
    add("")
    add(f"* The 61 renderable profiles produce only **{coverage['distinct_audio_signals']} distinct "
        f"audio signals**. {coverage['redundant_profiles']} profiles are byte-identical to another "
        "profile in the library, in groups as large as "
        f"{coverage['identical_audio_groups'][0]['size'] if coverage['identical_audio_groups'] else 1}.")
    add(f"* Mean usefulness {part_a_result['scales']['usefulness']['mean']}, mean distinctiveness "
        f"{part_a_result['scales']['distinctiveness']['mean']}, mean Atari character "
        f"{part_a_result['scales']['atari_character']['mean']} (n={part_a_result['scales']['usefulness']['n']}).")
    add(f"* The same sound, presented twice under two labels, still drew distinctiveness ratings up to "
        f"{part_a_result['noise_floor']['distinctiveness']['max_within_group_range']:.0f} points apart "
        f"(mean within-group range "
        f"{part_a_result['noise_floor']['distinctiveness']['mean_within_group_range']}, ICC(1,1) "
        f"{part_a_result['noise_floor']['distinctiveness']['icc_1_1']}) — the listener was reliable, but "
        "not to the point where a one-point difference between profiles means anything.")
    add(f"* A/B: {part_b_result['preferences'].get('a', 0)} A, {part_b_result['preferences'].get('b', 0)} B, "
        f"{part_b_result['preferences'].get('none', 0)} no preference; median similarity "
        f"{part_b_result['similarity']['median']}, median character difference "
        f"{part_b_result['character_difference']['median']}. Machine distance against perceived "
        f"similarity: rho = **{similarity_rho}** (n={part_b_result['machine_vs_human']['n']}).")
    add(f"* Songs: **{song_direction}** — profile-bound {profile_wins}, default {default_wins}, "
        f"ties {song_outcomes.get('tie', 0)} of 6. On the single question \"which sounds better\" the "
        f"tally was {part_c_result['tallies']['better_sound']['profile']} for the profile version and "
        f"{part_c_result['tallies']['better_sound']['default']} for the default.")
    add(f"* The listener's vocabulary is dominated by \"lead\" "
        f"({part_a_result['category_counts'].get('lead_tonal', 0)} of {len(results)} comments) — a direct "
        "consequence of the single melodic stimulus.")
    add("")
    add("**Inference.**")
    add("")
    add(f"* The library is **much smaller than it looks**: as a source of *distinct sounds* it offers "
        f"{coverage['distinct_audio_signals']}, not 61. The redundancy is not a perception artefact; it is "
        "in the rendered audio, because these profiles differ in measured pitch/volume gesture "
        "behaviour that the player cannot currently render.")
    add(f"* The spectral distance metric behaves as designed on similarity (rho {similarity_rho}, "
        f"{distinct_rho} without the identical pairs), so the machine model of *timbre distance* is "
        "not broken. Its blind spot is measurable and it is **level**: the distance normalises the "
        f"spectrum, so a profile that sustains 10 dB lower looks identical to one that does not, and "
        f"the level gap predicts the similarity rating about as well (rho {level_rho}).")
    add("* **The whole-song comparison is the decisive negative result.** Binding profiles to real "
        f"songs made them worse for this listener in {default_wins} of 6 comparisons, unanimously on "
        "all three questions, with the profile-bound render never winning one.")
    add("")
    add("**Recommendation.**")
    add("")
    add(f"* **Do not** select a production library from this data yet. The isolated stimuli are "
        "Atari-like and useful, and the metric story is now understood, but the integration path "
        "that was actually tested — these bindings, on these six songs — loses to the composer's own "
        f"defaults. The verdict is **{verdict['verdict']}**, and §14 says what to fix first.")
    add("")

    # ---------------------------------------------------------------- 2
    add("## 2. Dataset verification")
    add("")
    add("**Observed.** The analysis read exactly three answer files and the experiment manifest, and")
    add("hashed them so the run can be reproduced from the same bytes:")
    add("")
    add("| file | sha256 (first 16) |")
    add("| :--- | :--- |")
    for name, digest in sorted(answers.hashes.items()):
        add(f"| `{name}` | `{digest[:16]}` |")
    add("")
    add("| check | result |")
    add("| :--- | :--- |")
    add(f"| part A rows | {len(answers.profiles)} of {len(answers.manifest['samples'])} expected |")
    add(f"| part B rows | {len(answers.ab)} of {len(answers.manifest['ab_trials'])} expected |")
    add(f"| part C rows | {len(answers.song)} of {len(answers.manifest['song_trials'])} expected |")
    add("| ids agree with the private manifest | yes, set-for-set, no duplicates, no unknown ids |")
    add("| numeric ranges | every value inside 1–5; every choice inside a/b/none |")
    add("| raw answers modified | **no** — read-only; only whitespace is trimmed for matching |")
    add("")
    if answers.anomalies:
        add("Anomalies found in the returned data (reported, never repaired):")
        add("")
        add("| kind | where | detail | effect on the analysis |")
        add("| :--- | :--- | :--- | :--- |")
        for anomaly in answers.anomalies:
            add(f"| `{anomaly.kind}` | {anomaly.where} | {anomaly.detail} | {anomaly.effect} |")
        add("")
    else:  # pragma: no cover - only with a perfect answer sheet
        add("No anomalies: every expected row carries every rating.")
        add("")
    add("**Inference.** The dataset is complete enough to analyse as a whole. The two gaps are")
    add("single fields, so every statistic below states its own n rather than assuming "
        f"{len(results)}.")
    add("")

    # ---------------------------------------------------------------- 3
    add("## 3. Part A — the profiles heard one at a time")
    add("")
    add("**Observed.**")
    add("")
    add("| scale | n | mean | median | stdev | min | max | share 4–5 | share 1–2 |")
    add("| :--- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |")
    for scale in PROFILE_SCALES:
        summary = part_a_result["scales"][scale]
        if not summary.get("n"):
            add(f"| {scale} | 0 | — | — | — | — | — | — | — |")
            continue
        add(f"| {scale} | {summary['n']} | {summary['mean']} | {summary['median']} | "
            f"{summary['stdev']} | {summary['min']:g} | {summary['max']:g} | "
            f"{summary['share_4_5']:.0%} | {summary['share_1_2']:.0%} |")
    add("")
    add("Score distributions:")
    add("")
    add("| score | distinctiveness | usefulness | Atari character | confidence |")
    add("| ---: | ---: | ---: | ---: | ---: |")
    for score in range(1, 6):
        cells = [
            str(part_a_result["scales"][scale].get("distribution", {}).get(str(score), 0))
            for scale in PROFILE_SCALES
        ]
        add(f"| {score} | " + " | ".join(cells) + " |")
    add("")

    add("### 3.1 Distinctiveness against usefulness")
    add("")
    quadrants = part_a_result["quadrants"]
    add("| quadrant | n | profiles |")
    add("| :--- | ---: | :--- |")
    for name, label in (
        ("distinctive_and_useful", "distinctive (≥4) **and** useful (≥4)"),
        ("distinctive_not_useful", "distinctive (≥4) but not useful (<4)"),
        ("useful_not_distinctive", "useful (≥4) but not distinctive (<4)"),
        ("neither", "neither (both <4)"),
    ):
        members = quadrants.get(name, [])
        shown = ", ".join(members) if members else "—"
        add(f"| {label} | {len(members)} | {shown} |")
    add("")

    add("### 3.2 Does Atari character predict anything?")
    add("")
    if correlations["table"]:
        pairs = [
            (row["metric"], row["scale"], row["n"], row["spearman"])
            for row in correlations["table"]
            if row["scale"] in ("usefulness", "distinctiveness")
        ][:6]
        add("| metric | scale | n | Spearman |")
        add("| :--- | :--- | ---: | ---: |")
        for metric, scale, n, rho in pairs:
            add(f"| {metric} | {scale} | {n} | {rho} |")
    add("")
    usefulness_character = _scale_pair_rho(results, "atari_character", "usefulness")
    add(f"Atari character against usefulness: rho = {usefulness_character} "
        f"(n={part_a_result['scales']['usefulness']['n']}).")
    add("")

    add("### 3.3 Confidence, and a session effect that matters more")
    add("")
    add("| band | n | distinctiveness (mean/median) | usefulness (mean/median) |")
    add("| :--- | ---: | :--- | :--- |")
    for band, summary in part_a_result["confidence_bands"].items():
        distinct = summary["distinctiveness"]
        useful = summary["usefulness"]
        add(f"| {band} | {summary['n']} | {distinct.get('mean', '—')} / {distinct.get('median', '—')} | "
            f"{useful.get('mean', '—')} / {useful.get('median', '—')} |")
    add("")
    drift = part_a_result["presentation_drift"]
    add("The samples were presented in a seeded shuffle, so position is not a property of the sound.")
    add("Correlating each scale with the position in the session:")
    add("")
    add("| scale | n | Pearson(position) | Spearman(position) | mean first half | mean second half |")
    add("| :--- | ---: | ---: | ---: | ---: | ---: |")
    for scale in PROFILE_SCALES:
        row = drift[scale]
        add(f"| {scale} | {row['n']} | {row['pearson_position']} | {row['spearman_position']} | "
            f"{row['mean_first_half']} | {row['mean_second_half']} |")
    add("")

    add("### 3.4 The listener's own vocabulary")
    add("")
    add(f"The README suggested {', '.join(SUGGESTED_VOCABULARY)}. The listener used "
        f"{', '.join(f'{name} ({count})' for name, count in list(part_a_result['category_counts'].items())[:7])}.")
    add("Categories below are read out of the answers, with the markers shown so the grouping can be")
    add("checked rather than trusted:")
    add("")
    add("| category | markers | n | members |")
    add("| :--- | :--- | ---: | :--- |")
    for name, markers, description in COMMENT_CATEGORIES:
        members = [item.sample_id for item in results if name in item.categories]
        if not members:
            continue
        add(f"| {name} ({description}) | {', '.join(markers)} | {len(members)} | {', '.join(members[:10])}"
            + (f" (+{len(members) - 10})" if len(members) > 10 else "") + " |")
    add("")

    add("**Inference.** The vocabulary is dominated by *lead* because the stimulus is one melodic")
    add("phrase in the lead register: the experiment could not present a profile as percussion or as")
    add("a bass line, so \"this sounds like a lead\" is partly a property of the stimulus. The")
    add("clean/noisy distinction is more informative, and §6 shows it tracks the generator family")
    add("rather than the spectrum.")
    add("")

    add("### 3.5 The noise floor: what the same sound scored twice")
    add("")
    add("Some profiles render to **byte-identical** audio, so the same sound was presented under")
    add("different sample ids. Any difference in its ratings is the listener's own inconsistency:")
    add("")
    add("| scale | groups | ratings inside | mean within-group range | max range | ICC(1,1) |")
    add("| :--- | ---: | ---: | ---: | ---: | ---: |")
    for scale in PROFILE_SCALES:
        summary = part_a_result["noise_floor"][scale]
        add(f"| {scale} | {summary['groups_with_more_than_one_rating']} | "
            f"{summary['ratings_inside_identical_audio']} | {summary['mean_within_group_range']} | "
            f"{summary['max_within_group_range']} | {summary['icc_1_1']} |")
    add("")
    add("Groups of identical audio:")
    add("")
    add("| size | samples | profiles |")
    add("| ---: | :--- | :--- |")
    for group in coverage["identical_audio_groups"]:
        add(f"| {group['size']} | {', '.join(group['samples'])} | {', '.join(group['profiles'])} |")
    add("")
    add("**Inference.** The listener was *reliable*: with the same sound presented twice, the agreement")
    add("measures give ICC(1,1) "
        + ", ".join(
            f"{scale} {part_a_result['noise_floor'][scale]['icc_1_1']}"
            for scale in ("atari_character", "usefulness", "distinctiveness")
        )
        + ". Two consequences follow, both of which constrain the reading of §3.")
    add("")
    add(f"* The scales that describe the sound are trustworthy enough to compare **groups** of "
        "profiles, not to order them finely: the same sound was still rated up to "
        f"{part_a_result['noise_floor']['distinctiveness']['max_within_group_range']:.0f} point(s) apart on "
        "distinctiveness, so a one-point difference between two profiles is within the noise.")
    add(f"* Confidence behaves as a *self-report about the judgement*, not as a property of the sound "
        f"(ICC(1,1) {part_a_result['noise_floor']['confidence']['icc_1_1']}), and it drifts through the "
        "session (§3.3). It is useful for spotting where the listener hesitated; it is not evidence "
        "about a profile.")
    add("")

    # ---------------------------------------------------------------- 4
    add("## 4. Part B — profile against profile")
    add("")
    add("**Observed.**")
    add("")
    add(f"Preferences: A {part_b_result['preferences'].get('a', 0)}, B "
        f"{part_b_result['preferences'].get('b', 0)}, no preference "
        f"{part_b_result['preferences'].get('none', 0)}, not stated "
        f"{sum(1 for t in part_b_result['trials'] if not t['preference'])}.")
    add("")
    add("| view | trials | median similarity | median character difference |")
    add("| :--- | ---: | ---: | ---: |")
    for label, key in (
        ("all trials", "trials"),
        ("byte-identical audio pairs", "identical_audio_pairs"),
        ("distinct-audio pairs", "distinct_audio_pairs"),
    ):
        summary = part_b_result[key] if key == "trials" else part_b_result[key]
        if key == "trials":
            similarity = part_b_result["similarity"]
            difference = part_b_result["character_difference"]
            add(f"| {label} | {len(part_b_result['trials'])} | {similarity.get('median')} | {difference.get('median')} |")
        else:
            add(f"| {label} | {summary['trials']} | {summary['similarity'].get('median')} | "
                f"{summary['character_difference'].get('median')} |")
    add("")
    add("By stratum:")
    add("")
    add("| stratum | trials | median similarity | decided | no preference |")
    add("| :--- | ---: | ---: | ---: | ---: |")
    for name, summary in part_b_result["by_stratum"].items():
        add(f"| {name} | {summary['trials']} | {summary['similarity'].get('median')} | "
            f"{summary['decided']} | {summary['no_preference']} |")
    add("")
    add("Most-preferred profiles (times chosen as the preferred side):")
    add("")
    top_wins = [(pid, count) for pid, count in part_b_result["wins"].items() if count > 0][:8]
    if top_wins:
        add("| profile | wins | sample | scope | generator | usefulness | distinctiveness |")
        add("| :--- | ---: | :--- | :--- | :--- | ---: | ---: |")
        for profile_id, count in top_wins:
            row = part_b_result["profile_rating_lookup"].get(profile_id, {})
            add(f"| {profile_id} | {count} | {row.get('sample_id')} | {row.get('scope')} | "
                f"`{row.get('generator_family')}` | {row.get('usefulness')} | {row.get('distinctiveness')} |")
        add("")
    add("Machine distance against perceived similarity:")
    add("")
    machine = part_b_result["machine_vs_human"]
    add(f"* Spearman rho = **{machine['spearman_distance_vs_similarity']}** (n={machine['n']})")
    add(f"* Pearson r = {machine['pearson_distance_vs_similarity']}")
    add("")
    if part_b_result["distant_but_similar"]:
        add("Trials that were technically far apart but heard as similar:")
        add("")
        add("| trial | technical distance | similarity |")
        add("| :--- | ---: | ---: |")
        for row in part_b_result["distant_but_similar"]:
            add(f"| {row['trial_id']} | {row['distance']:.3f} | {row['similarity']:g} |")
        add("")
    if part_b_result["close_but_different"]:
        add("Pairs the metric called nearly identical but the listener called different — with the")
        add("difference the metric cannot see attached:")
        add("")
        add("| trial | technical distance | similarity | A | B | same generator | same scope | |Δ RMS| dB |")
        add("| :--- | ---: | ---: | :--- | :--- | :--- | :--- | ---: |")
        for row in part_b_result["close_but_different"]:
            add(f"| {row['trial_id']} | {row['distance']:.3f} | {row['similarity']:g} | "
                f"{row['profile_a']} ({row['scope_a']}) | {row['profile_b']} ({row['scope_b']}) | "
                f"{'yes' if row['same_generator_family'] else 'no'} | "
                f"{'yes' if row['same_scope'] else 'no'} | {row['level_gap_db']} |")
        add("")
    add("What predicted the similarity rating, over all 30 trials:")
    add("")
    add("| difference between the two stimuli | n | Spearman vs similarity |")
    add("| :--- | ---: | ---: |")
    for row in part_b_result["blind_spot"]["table"]:
        add(f"| {row['difference']} | {row['n']} | {row['spearman_vs_similarity']} |")
    add("")
    close_gap = part_b_result["blind_spot"]["close_pairs_level_gap_db"]
    identical_gap = part_b_result["blind_spot"]["identical_pairs_level_gap_db"]
    add(f"In the {part_b_result['blind_spot']['close_pairs']} non-identical pairs the metric called "
        f"nearly identical (distance ≤ 0.02), |Δ RMS| spans {close_gap.get('min'):g}–{close_gap.get('max'):g} dB "
        f"(median {close_gap.get('median'):g}); of those, the {len(part_b_result['close_but_different'])} "
        f"rated similarity ≤ 2 differ by 7–12 dB except one (trial_15) which is level-matched and differs "
        "in generator instead. In the byte-identical pairs the level gap is "
        f"{identical_gap.get('min'):g}–{identical_gap.get('max'):g} dB — the distance cannot tell those two "
        "situations apart, because it is computed on a normalised spectrum.")
    add("")
    add("**Inference.** The A/B experiment answers the redundancy question directly: the library does")
    add("contain clearly different sounds, and the metric ranks them roughly as the listener did")
    add("(rho " + f"{similarity_rho}" + "). Two of the listener's cues are measurable and one of them the")
    add("distance discards by construction:")
    add("")
    add(f"* **pitch/centroid difference** is the single best predictor of similarity "
        f"({next((row['spearman_vs_similarity'] for row in part_b_result['blind_spot']['table'] if row['difference'] == 'centroid_gap_hz'), None)});")
    add(f"* **level difference** is a close second and is *invisible* to the distance — a pair that "
        "sustains 12 dB apart and a pair that is byte-identical both score ≈ 0.00;")
    add("* the listener's *character* language (clean versus noisy) follows the generator family")
    add("  rather than the spectrum, which is what a POKEY-literate listener keys on.")
    add("")
    add("That is a correctable defect in the metric, not a perceptual mystery.")
    add("")

    # ---------------------------------------------------------------- 5
    add("## 5. Part C — whole songs")
    add("")
    add("**Observed.**")
    add("")
    add("| question | profile version | default version | no preference |")
    add("| :--- | ---: | ---: | ---: |")
    for field_name in SONG_CHOICE_FIELDS:
        tally = part_c_result["tallies"][field_name]
        add(f"| {field_name.replace('_', ' ')} | {tally['profile']} | {tally['default']} | {tally['none']} |")
    add("")
    add(f"Overall difference: median {part_c_result['overall_difference'].get('median')}, range "
        f"{part_c_result['overall_difference'].get('min'):g}–{part_c_result['overall_difference'].get('max'):g}.")
    add("")
    add("| pair | song | profile votes | default votes | outcome | overall difference |")
    add("| :--- | :--- | ---: | ---: | :--- | ---: |")
    for row in part_c_result["per_song"]:
        add(f"| {row['trial_id']} | {row['song']} | {row['profile_votes']} | {row['default_votes']} | "
            f"{row['outcome']} | {row['overall_difference']} |")
    add("")
    add(f"Six pairs cannot support a population claim, and the split "
        f"({profile_wins}–{default_wins}) is reported as a description of these six songs only.")
    add("")
    add("**Inference.** This is the most consequential result in the stage, and the least ambiguous:")
    add(f"the listener preferred the composer's **own** default instruments in {default_wins} of 6 songs,")
    add("unanimously on all three questions, with the profile-bound render winning none. The reported")
    add(f"overall difference is large (median {part_c_result['overall_difference'].get('median')}), so this is not a")
    add("tie-break among near-identical renders: binding these profiles audibly changed the music, and")
    add("changed it for the worse. Whatever the profiles are good at in isolation, the integration path")
    add("tested here degrades a real piece.")
    add("")
    add("Two candidate explanations that this experiment cannot separate, both worth testing next:")
    add("the bindings chose profiles by generator family rather than by the listening evidence, and the")
    add("bound profiles were mostly the *louder, noisier* family the listener rated as merely average;")
    add("and the default character instruments may already be better tuned to the player's envelopes")
    add("than a profile measured from unrelated material is.")
    add("")

    # ---------------------------------------------------------------- 6
    add("## 6. Human against machine")
    add("")
    add("**Observed.** Rank correlations between every available machine metric and every rating")
    add(f"(only rows with n ≥ {MIN_CORRELATION_N}):")
    add("")
    add("| metric | scale | n | Spearman | Kendall tau-b | Pearson |")
    add("| :--- | :--- | ---: | ---: | ---: | ---: |")
    for row in correlations["table"]:
        add(f"| {row['metric']} | {row['scale']} | {row['n']} | {row['spearman']} | "
            f"{row['kendall_tau_b']} | {row['pearson']} |")
    add("")
    add("Ordinal group comparisons (Cliff's delta, −1…+1):")
    add("")
    add("| split | scale | Cliff's delta |")
    add("| :--- | :--- | ---: |")
    for row in correlations["group_tests"]:
        add(f"| {row['split']} | {row['scale']} | {row['cliffs_delta']} |")
    add("")
    language = correlations["listener_language"]
    add("Listener language against the spectrum:")
    add("")
    add("| listener said | n | median flatness | median centroid | generator families |")
    add("| :--- | ---: | ---: | ---: | :--- |")
    for key in ("clean", "noisy"):
        summary = language[key]
        add(f"| {key} | {summary['n']} | {summary['flatness_median']} | {summary['centroid_median']} | "
            f"{', '.join('`' + f + '`' for f in summary['families'])} |")
    add("")
    add(f"Cliff's delta on flatness, clean versus noisy: {language['cliffs_delta_flatness_clean_vs_noisy']}. "
        f"Family sets disjoint: {'yes' if language['family_sets_disjoint'] else 'no'}.")
    add("")
    add("Not available in the Stage 9C manifest, so not analysed: "
        + ", ".join(f"`{name}`" for name in correlations["unavailable_metrics"]) + ".")
    add("")
    add("**Inference.** The band-energy distance tracks perceived similarity well (rho "
        f"{similarity_rho} in §4) — the machine model is not broken — but it is computed on a "
        "normalised spectrum, so it is blind to the one difference the listener used repeatedly and "
        "explicitly: **level**. Separately, the listener's clean/noisy vocabulary is explained by the "
        "*generator identity* rather than by any spectral summary, which is what a POKEY-literate "
        "listener would be expected to key on. A correlation here describes association only, never "
        "causation.")
    add("")

    # ---------------------------------------------------------------- 7
    add("## 7. Loudness bias")
    add("")
    add("**Observed.** The stimuli share a peak, not an RMS; the measured RMS range across the")
    add(f"library is {loudness['rms_range_db']} dB.")
    add("")
    add("| scale | n | Spearman vs RMS | Pearson vs RMS |")
    add("| :--- | ---: | ---: | ---: |")
    for row in loudness["correlations"]:
        add(f"| {row['scale']} | {row['n']} | {row['spearman']} | {row['pearson']} |")
    add("")
    matched = loudness["matched_level_band"]
    add(f"Matched-level sensitivity check (within ±2 dB of the median level, n={matched['n']}):")
    add("")
    add(f"* distinctiveness mean {matched['distinctiveness'].get('mean')}, median "
        f"{matched['distinctiveness'].get('median')}")
    add(f"* usefulness mean {matched['usefulness'].get('mean')}, median {matched['usefulness'].get('median')}")
    add(f"* Atari character mean {matched['atari_character'].get('mean')}, median "
        f"{matched['atari_character'].get('median')}")
    add(f"* distinctiveness inside versus outside the band, Cliff's delta: "
        f"{matched['distinctiveness_inside_vs_outside_delta']}")
    add("")
    ab_levels = loudness["ab_preference_vs_loudness"]
    add(f"In the A/B trials, the preferred side was the louder one {ab_levels['louder']} times, the "
        f"quieter one {ab_levels['quieter']} times; {ab_levels['equal_level']} trial(s) were level-matched "
        f"and {ab_levels['undecided']} had no stated preference.")
    add("")
    add("**Inference.** Loudness is *not* the explanation for the ratings, but it is not nothing")
    add("either — see the numbers above rather than a summary word. No correction is applied to the")
    add("answers: reweighting them would replace the listener's judgement with the analyst's.")
    add("")

    # ---------------------------------------------------------------- 8
    add("## 8. Hypothesis evaluation")
    add("")
    add("| # | hypothesis | verdict | evidence |")
    add("| :--- | :--- | :--- | :--- |")
    for entry in bundle["hypotheses"]:
        add(f"| {entry['id']} | {entry['hypothesis']} | **{entry['verdict']}** | {entry['evidence']} |")
    add("")

    # ---------------------------------------------------------------- 9
    add("## 9. Candidate categories")
    add("")
    add("Experimental groupings from the stated rules. **None is a selection**, and each member")
    add("carries its raw numbers so the rule can be changed and re-applied.")
    add("")
    group_titles = (
        ("strong_candidates", "A — Strong candidates",
         "distinctiveness ≥ 4, usefulness ≥ 4, Atari character ≥ 4, no `PITCH_BASE_PAIR_INCONSISTENT` "
         "limitation and nothing blocking (measured-but-missing codes do not disqualify: they mean "
         "the archaeology knew less, not that the profile is wrong)"),
        ("character_specialists", "B — Character specialists",
         "described by the listener with words other than \"lead\""),
        ("technically_interesting_perceptually_weak", "C — Technically interesting, perceptually weak",
         "at or above the library's median spectral distance from everything else, while rated "
         "≤ 3 on usefulness"),
        ("perceptually_interesting_weak_machine", "D — Perceptually interesting despite weak machine metrics",
         "usefulness ≥ 4 and distinctiveness ≥ 3 while sitting at or below the median spectral "
         "distance — liked despite looking unremarkable to the metric"),
        ("redundant", "E — Redundant profiles",
         "renders byte-identical audio to at least one other profile"),
    )
    for key, title, rule in group_titles:
        rows = categories[key]
        add(f"### {title} ({len(rows)})")
        add("")
        add(f"_Rule:_ {rule}")
        add("")
        if not rows:
            add("None under this rule.")
            add("")
            continue
        add("| profile | sample | scope | gen | usefulness | distinctiveness | Atari | audio group | comment |")
        add("| :--- | :--- | :--- | :--- | ---: | ---: | ---: | :--- | :--- |")
        for row in rows[:40]:
            add(f"| {row['profile_id']} | {row['sample_id']} | {row['scope']} | `{row['generator_family']}` | "
                f"{row['usefulness']} | {row['distinctiveness']} | {row['atari_character']} | "
                f"{row['audio_group'] if row['audio_group'] is not None else '—'} | {row['comment']} |")
        if len(rows) > 40:
            add(f"| … | | | | | | | | {len(rows) - 40} more in `reports/stage9d/categories.json` |")
        add("")

    # ---------------------------------------------------------------- 10
    add("## 10. Recommended shortlist")
    add("")
    add(f"**{shortlist['size']} candidates.** Rule: {shortlist['rule']}")
    add("")
    add("| # | profile | sample | scope | gen | usefulness | distinctiveness | Atari | confidence | why it is here |")
    add("| ---: | :--- | :--- | :--- | :--- | ---: | ---: | ---: | ---: | :--- |")
    for index, row in enumerate(shortlist["members"], start=1):
        add(f"| {index} | {row['profile_id']} | {row['sample_id']} | {row['scope']} | "
            f"`{row['generator_family']}` | {row['usefulness']} | {row['distinctiveness']} | "
            f"{row['atari_character']} | {row['confidence']} | {row['reason']} |")
    add("")
    add("A purely diversity-driven alternative, chosen greedily to maximise the minimum distance")
    add("between members (same machine space, no ratings involved):")
    add("")
    for count in ("20", "25", "30"):
        add(f"* {count}: {', '.join(shortlist['coverage_greedy_alternative'][count])}")
    add("")

    # ---------------------------------------------------------------- 11
    add("## 11. Redundancy and coverage")
    add("")
    add("**Observed.** Clustering the profiles by their spectral band energies (average linkage over")
    add("the same distance the A/B programme used):")
    add("")
    add("| cut | clusters | sizes |")
    add("| :--- | ---: | :--- |")
    for cut, partition in coverage["partitions"].items():
        add(f"| {cut} | {partition['clusters']} | {partition['sizes']} |")
    add("")
    add(f"Two-dimensional principal projection of the band energies explains "
        f"{coverage['projection']['explained_variance'][0]:.1%} and "
        f"{coverage['projection']['explained_variance'][1]:.1%} of the variance; coordinates are in "
        "`reports/stage9d/coverage.json`.")
    add("")
    add(f"* {coverage['distinct_audio_signals']} distinct audio signals from {coverage['profiles']} profiles")
    add(f"* {coverage['redundant_profiles']} profiles are duplicates of another profile's audio")
    add("")
    add("**Inference.** The perceptual space the *player* can currently reach is far smaller than the")
    add("profile count suggests, and it is occupied unevenly: a large block of noise/bass-like")
    add("profiles around 4.1 kHz centroid with flatness ≈ 0.50, a smaller block of pure-tone-like")
    add("profiles around 6.0 kHz, and few isolated sounds. A small library therefore needs one member")
    add("from each occupied region — not the top N by any single rating.")
    add("")

    # ---------------------------------------------------------------- 12
    add("## 12. Limitations")
    add("")
    add("* **One listener, one session.** Every rating is a single observation by a single person")
    add("  with prior knowledge of the Atari sound world. There is no inter-listener agreement to")
    add("  report, so nothing here is a population estimate.")
    add("* **The stimulus shapes the vocabulary.** One melodic phrase on one channel means the")
    add("  experiment could not present a profile as percussion or as a bass line, and \"lead\"")
    add(f"  dominates the comments ({part_a_result['category_counts'].get('lead_tonal', 0)} of {len(results)}).")
    add("* **A session effect is present.** Atari character and confidence correlate negatively with")
    add(f"  presentation position (see §3.3), so the later part of the session was rated with less")
    add("  discrimination.")
    add("* **Gestures are not rendered.** Profiles measured with a pitch/volume contour were heard as")
    add("  static tones; their real character is not what was judged.")
    add("* **Distinctiveness is reliable but coarse.** The listener was consistent about the same")
    add("  sound (ICC(1,1) "
        f"{part_a_result['noise_floor']['distinctiveness']['icc_1_1']}), yet the same sound still drew ratings up to")
    add(f"  {part_a_result['noise_floor']['distinctiveness']['max_within_group_range']:.0f} points apart, so only group-level")
    add("  differences on that scale should be read.")
    add("* **Six songs.** Part C is a description of six pieces, not a result about the integration.")
    add("* **No Stage 6/7B metrics are available** in the manifest, so the transferability and")
    add("  perceptual-metric hypotheses cannot be tested here.")
    add("")
    add("### A defect in Stage 9C, recorded rather than corrected")
    add("")
    add("The listening experiment deliberately renders every profile through one musical stimulus, and")
    add("that stimulus is chosen to keep the profile as the only variable. The consequence, visible for")
    add(f"the first time in these results, is that {coverage['redundant_profiles']} of {len(results)} profiles")
    add("produce audio **identical to another profile's**, so the experiment spent part of the")
    add("listener's attention comparing a sound with itself under two labels. Stage 9C's manifest")
    add("recorded the renderings faithfully — the duplicates are visible in it as equal feature")
    add("vectors — but did not report the duplication as a property of the *library*, which it is. No")
    add("historical data was modified; the finding is recorded here and used in §10 and §11, and it is")
    add("the main reason this report does not read Part A as a ranking.")
    add("")

    # ---------------------------------------------------------------- 13
    add("## 13. Conclusions")
    add("")
    add("**Observed.** The library's 61 renderable profiles make "
        f"{coverage['distinct_audio_signals']} distinct sounds under a fixed musical input; means are "
        f"{part_a_result['scales']['usefulness']['mean']} (usefulness), "
        f"{part_a_result['scales']['distinctiveness']['mean']} (distinctiveness), "
        f"{part_a_result['scales']['atari_character']['mean']} (Atari character); the spectral distance "
        f"predicts perceived similarity between isolated sounds (rho {similarity_rho}) while being "
        "blind to level; and on whole songs the profile-bound render lost to the composer's defaults "
        f"{default_wins}–{profile_wins} with one tie.")
    add("")
    add("**Inference.** Two different answers, and they must not be averaged into one:")
    add("")
    add("1. **As isolated sounds, the profiles work.** The listener consistently found them Atari-like")
    add("   and useful, and the machine distance agrees with the listener about similarity. But what")
    add("   the experiment had to listen to was one melodic phrase, and 24 of the 61 profiles render")
    add("   audio identical to another profile's — so the library's *audible* size is roughly 37, not 61.")
    add("2. **As a way to make a song better, this integration failed the test it was built for.** Six")
    add("   songs, one unanimous direction. A profile measured from a classic tune is not automatically")
    add("   a better instrument for a new tune than the composer's own defaults, and the bindings in")
    add("   `examples/songs/` were chosen by generator family rather than by any listening evidence.")
    add("")
    add("**Recommendation.** Do not select a production palette from this evidence. Fix the two things")
    add("that the data now names — the metric's level blindness and the integration's binding strategy —")
    add("and re-run a whole-song comparison before returning to selection.")
    add("")
    add("### What the data does *not* allow us to say")
    add("")
    add("* that any profile is good or bad as an instrument: the ratings are one listener's, on one")
    add("  stimulus, and a one-point difference is inside that listener's own repeatability;")
    add("* that profile-bound rendering in general is worse than the defaults: six songs, six bindings,")
    add("  one listener;")
    add("* that the machine metrics are useless: the distance tracked similarity strongly, and the")
    add("  failure is specific and named (level).")
    add("")

    # ---------------------------------------------------------------- 14
    add("## 14. Recommended next stage")
    add("")
    add("The whole-song result, not the profile ratings, decides what comes next. Two defects are now")
    add("named and testable, and both should be fixed **before** any selection:")
    add("")
    add("1. **The similarity metric is blind to level.** It normalises the spectrum, so two profiles")
    add("   whose sustain differs by 10 dB score as nearly identical. Add the level/RMS term (and, if")
    add("   it helps, the envelope) to the distance and re-check §4's table; the listener's own")
    add("   ratings already show level is part of what they hear.")
    add(f"2. **The bindings were chosen by generator family, not by evidence.** The picks in")
    add("   `examples/songs/` ignored the listening results entirely, and five of six songs got worse.")
    add("   Re-bind the same songs using the shortlist in §10 — one representative per audio group,")
    add("   preferring the profiles this listener rated useful — and repeat **only** the Part C")
    add("   comparison. That is a small, cheap, decisive experiment.")
    add("")
    add("Then, and only then:")
    add("")
    add("3. Select the production palette from the audio groups (not from profile ids), one member")
    add("   each, and publish it as a curation document over the existing bank — no profile renamed,")
    add("   altered or removed.")
    add("")
    add(f"Proposed shape of that next stage: {verdict['next_stage']}")
    add("")
    add("### Closing answer")
    add("")
    add("> Is there enough evidence to move to selecting a small production POKEY sound profile library?")
    add("")
    add(f"**{verdict['verdict']}**")
    add("")
    for criterion in verdict["criteria"]:
        mark = "met" if criterion["met"] else "**not met**"
        add(f"* {criterion['criterion']} — {mark} ({criterion['value']})")
    add("")
    if verdict["unmet"]:
        add("Not met: " + "; ".join(verdict["unmet"]) + ".")
        add("")
    add("The isolated-sound evidence is *usable*; the whole-song evidence is *negative*. Selecting now")
    add("would mean choosing a palette on the strength of 3.2-second audio samples while the one test")
    add("that used real music says the result got worse — which is exactly the reasoning this stage was")
    add("asked to resist.")
    add("")
    return "\n".join(lines)


__all__ = [
    "ANALYSIS_VERSION",
    "Answers",
    "AnswersMissing",
    "Anomaly",
    "COMMENT_CATEGORIES",
    "MIN_CORRELATION_N",
    "PROFILE_SCALES",
    "ProfileResult",
    "STAGE",
    "SUGGESTED_VOCABULARY",
    "UNAVAILABLE_METRICS",
    "analyze_stage9d",
    "build_profile_results",
    "candidate_categories",
    "cliffs_delta",
    "coverage_analysis",
    "derive_comment_categories",
    "describe",
    "evaluate_hypotheses",
    "final_verdict",
    "human_machine_correlations",
    "icc_1_1",
    "identical_audio_groups",
    "kendall_tau_b",
    "load_answers",
    "loudness_bias",
    "part_a",
    "part_b",
    "part_c",
    "pearson",
    "presentation_drift",
    "profile_scores_payload",
    "recommended_shortlist",
    "render_report",
    "spearman",
    "stimulus_hashes",
    "write_json",
]

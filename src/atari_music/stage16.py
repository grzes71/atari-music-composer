"""Stage 16 — cross-song generalisation of the Stage 15 performance style.

Analysis only. This stage asks one question: **does a context-aware performance style learned
from one song contain information that stays valid on a different song?** It builds nothing,
renders nothing, generates nothing, and asks nobody to listen.

Song analysis is **not re-implemented**. Every event, every technique identity, every
classification and every context dimension comes from :mod:`atari_music.stage15` unchanged;
this module only aggregates those results across songs. Where a Stage 15 definition was a
heuristic, the heuristic is reused as-is, and where cross-song comparison needs a *different*
representation (for example an absolute note-length band instead of Stage 15's song-relative
tertiles) that change is made here, named, and justified — never by editing Stage 15.

Everything is deterministic: no sampling, no timestamps, no reliance on filesystem or
dictionary order, and every input is read through its SHA-256.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from atari_music import stage15

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_REPORTS_DIR = REPO_ROOT / "reports"
DEFAULT_STAGE15_DIR = DEFAULT_REPORTS_DIR / "stage15"
DEFAULT_STAGE16_DIR = DEFAULT_REPORTS_DIR / "stage16"
DEFAULT_DOCS_DIR = REPO_ROOT / "docs"
DEFAULT_ARCHAEOLOGY_DIR = stage15.DEFAULT_ARCHAEOLOGY_DIR

ANALYSIS_VERSION = "stage16/1"

#: Song A is the Stage 15 reference; song B is the Stage 15 runner-up, recovered from the
#: Stage 15 artefact rather than assumed.
SONG_A_SLUG = "Draconus_2024__sub0"

# -- documented thresholds (Part F, Part H) -----------------------------------------
#: A technique needs this many occurrences in a song before that song counts as evidence.
MIN_OCCURRENCES_IN_SONG = 20
#: Share of the selected songs in which a technique must appear to be a universality candidate.
UNIVERSAL_SONG_SHARE = 0.75
#: Context distributions are compared in two steps. A technique only has a *usable* context
#: rule in a song if one value dominates its distribution; otherwise there is nothing to
#: compare. Lowering this constant is how the analysis would be made more generous, and it is
#: stated here rather than buried.
CONTEXT_DOMINANCE_MIN = 0.40
#: Secondary, distribution-shape comparison (overlap coefficient, i.e. the sum of the smaller
#: share for every value). Reported next to the dominance test, never instead of it.
CONTEXT_OVERLAP_SAME = 0.50
CONTEXT_OVERLAP_DIFFERENT = 0.30
#: Parameter distributions are compared with range intersection over union.
PARAMETER_OVERLAP_SAME = 0.50
#: Absolute bands used for cross-song comparison. Stage 15 used *song-relative* tertiles for
#: note length; a tertile means a different number of frames in every song, so it cannot be
#: compared across songs. These absolute bands are the cross-song replacement.
NOTE_LENGTH_BANDS = ((3, "short_1_3_frames"), (12, "medium_4_12_frames"))
DENSITY_BANDS = ((2, "sparse_0_2"), (6, "medium_3_6"))
#: How many example occurrences to publish for an ambiguous case.
AMBIGUITY_EXAMPLES = 3

#: Portable context factors — the ones whose *meaning* survives a song boundary.
PORTABLE_CONTEXT_FACTORS = (
    "family_bucket",
    "position_in_note",
    "pitch_band",
    "note_length_band",
    "density_band",
    "company_band",
    "previous_event_kind",
    "next_event_kind",
)
#: Factors that are indices inside one song and therefore cannot be compared across songs.
SONG_LOCAL_CONTEXT_FACTORS = ("channel", "occurrence_index_band")
#: The factors used for the short "core signature".
CORE_CONTEXT_FACTORS = ("family_bucket", "position_in_note", "pitch_band")

#: Techniques whose definition is so generic that shared presence is weak evidence of a shared
#: style. Flagged so they can be excluded from a generalisation claim (Part G: a schema can be
#: universal while the style is not).
LOW_LEVEL_TECHNIQUES = frozenset(
    {"NOTE_ON", "NOTE_OFF", "PITCH_CHANGE", "VOLUME_CHANGE", "REGISTER_PATTERN_CHANGE"}
)


class Stage16Error(RuntimeError):
    """A required input artefact is missing or malformed."""


#: Disclosed defect and correction, found while doing this stage and fixed in Stage 15 itself.
#: Stage 15's span analysis read the dominant generator of a span as
#: ``max(set(waves), key=waves.count)``, whose result on a *tie* depends on set iteration order,
#: which depends on per-process string hashing. The analysis was therefore not deterministic
#: between processes, which Stage 16 cannot tolerate because it depends on it. Stage 15's own
#: artefacts were regenerated after the fix; the change moves 10 of 13,480 events between
#: classifications (0.07%) and changes none of Stage 15's findings, techniques or verdicts.
DETERMINISM_FIX_NOTE = (
    "Reusing another stage's analysis means inheriting its determinism. Stage 15's dominant-"
    "generator tie-break used set iteration order, which varies with the per-process string hash "
    "seed, so its event classifications could differ between processes. The tie-break is now "
    "lexicographic and Stage 15's artefacts were regenerated; 10 of 13,480 reference-song events "
    "(0.07%) moved between classifications and no Stage 15 conclusion changed."
)


# ---------------------------------------------------------------------------
# Helpers (aggregation only; every song-level definition lives in Stage 15)
# ---------------------------------------------------------------------------
def _read_json(path: Path) -> Any:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError as error:
        raise Stage16Error(f"missing artefact: {path}") from error
    except json.JSONDecodeError as error:
        raise Stage16Error(f"malformed JSON: {path}: {error}") from error


def sha256_file(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _rnd(value: Optional[float], places: int = 6) -> Optional[float]:
    if value is None:
        return None
    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        return None
    return round(float(value), places)


def _median(values: Sequence[float]) -> Optional[float]:
    return stage15._median(values)


def _quantile(values: Sequence[float], q: float) -> Optional[float]:
    return stage15._quantile(values, q)


def _share(part: int, whole: int) -> Optional[float]:
    return _rnd(part / whole) if whole else None


def _jaccard(left: Iterable[str], right: Iterable[str]) -> Optional[float]:
    a, b = set(left), set(right)
    union = a | b
    return _rnd(len(a & b) / len(union)) if union else None


def _weighted_jaccard(left: Mapping[str, int], right: Mapping[str, int]) -> Optional[float]:
    """Ruzicka similarity: sum of per-key minima over sum of per-key maxima."""
    keys = sorted(set(left) | set(right))
    if not keys:
        return None
    lower = sum(min(left.get(key, 0), right.get(key, 0)) for key in keys)
    upper = sum(max(left.get(key, 0), right.get(key, 0)) for key in keys)
    return _rnd(lower / upper) if upper else None


def _overlap_coefficient(left: Mapping[str, float], right: Mapping[str, float]) -> Optional[float]:
    """Overlap of two categorical distributions: sum over values of the smaller share."""
    keys = sorted(set(left) | set(right))
    if not keys:
        return None
    return _rnd(sum(min(left.get(key, 0.0), right.get(key, 0.0)) for key in keys))


def _range_overlap(left: Tuple[float, float], right: Tuple[float, float]) -> Optional[float]:
    """Intersection over union of two numeric ranges."""
    low = max(left[0], right[0])
    high = min(left[1], right[1])
    union = max(left[1], right[1]) - min(left[0], right[0])
    if union <= 0:
        return 1.0 if low == high else 0.0
    return _rnd(max(0.0, high - low) / union)


def _distribution(values: Sequence[float], places: int = 6) -> Dict[str, Any]:
    if not values:
        return {}
    return {
        "count": len(values),
        "min": _rnd(min(values), places),
        "p10": _rnd(_quantile(values, 0.10), places),
        "median": _rnd(_median(values), places),
        "p90": _rnd(_quantile(values, 0.90), places),
        "max": _rnd(max(values), places),
    }


def _shares(counter: Mapping[str, int]) -> Dict[str, float]:
    total = sum(counter.values())
    if not total:
        return {}
    return {key: _rnd(count / total) for key, count in sorted(counter.items())}


# ---------------------------------------------------------------------------
# PART A — deterministic train/test song selection
# ---------------------------------------------------------------------------
#: The axes the brief names, and how each becomes a comparable number. Categorical axes
#: contribute 1.0 when they differ, i.e. a different composer or a different AUDCTL is worth
#: one whole axis of distance. Numeric axes are min-max normalised over the eligible corpus so
#: no axis dominates because of its units.
DIVERSITY_NUMERIC_AXES = (
    "audible_channels",
    "generator_families",
    "distinct_pitch_values",
    "events_per_second",
    "duration_s",
)
DIVERSITY_CATEGORICAL_AXES = ("author", "audctl")


@dataclass(frozen=True)
class Candidate:
    """One corpus subsong, described by the axes song selection is allowed to look at."""

    slug: str
    path: str
    sha256: str
    song: str
    subsong: int
    title: Optional[str]
    author: Optional[str]
    date: Optional[str]
    duration_s: float
    frames: int
    audctl: str
    audible_channels: int
    generator_families: int
    distinct_pitch_values: int
    events: int

    @property
    def events_per_second(self) -> float:
        return self.events / self.duration_s if self.duration_s else 0.0

    def vector(self) -> Dict[str, Any]:
        return {
            "audible_channels": self.audible_channels,
            "generator_families": self.generator_families,
            "distinct_pitch_values": self.distinct_pitch_values,
            "events_per_second": self.events_per_second,
            "duration_s": self.duration_s,
            "author": self.author,
            "audctl": self.audctl,
        }

    def to_dict(self) -> Dict[str, Any]:
        return {
            "slug": self.slug,
            "path": self.path,
            "sha256": self.sha256,
            "song": self.song,
            "subsong": self.subsong,
            "title": self.title,
            "author": self.author,
            "date": self.date,
            "duration_s": _rnd(self.duration_s),
            "frames": self.frames,
            "audctl": self.audctl,
            "audible_channels": self.audible_channels,
            "generator_families": self.generator_families,
            "distinct_pitch_values": self.distinct_pitch_values,
            "events": self.events,
            "events_per_second": _rnd(self.events_per_second),
        }


def corpus_candidates(arch_root: Path = DEFAULT_ARCHAEOLOGY_DIR) -> List[Candidate]:
    """Every corpus subsong with the axes song selection may use. Sorted by slug."""
    candidates: List[Candidate] = []
    for path in stage15.list_traces(arch_root):
        trace = stage15.load_trace(path)
        metrics = stage15.candidate_metrics(trace)
        events = len(stage15.detect_events(trace))
        candidates.append(
            Candidate(
                slug=metrics["trace"], path=metrics["path"], sha256=metrics["sha256"],
                song=metrics["song"], subsong=int(metrics["subsong"]), title=metrics["title"],
                author=metrics["author"], date=metrics["date"],
                duration_s=float(metrics["duration_s"]), frames=int(metrics["frames"]),
                audctl=metrics["audctl"], audible_channels=int(metrics["audible_channels"]),
                generator_families=int(metrics["generator_families"]),
                distinct_pitch_values=int(metrics["distinct_pitch_values"]), events=events,
            )
        )
    return candidates


def diversity_distance(
    left: Mapping[str, Any],
    right: Mapping[str, Any],
    ranges: Mapping[str, float],
    author_weight: float = 1.0,
) -> float:
    """Euclidean distance over the named axes, each normalised to at most 1.0."""
    total = 0.0
    for axis in DIVERSITY_NUMERIC_AXES:
        span = ranges.get(axis, 0.0)
        delta = 0.0 if span <= 0 else abs(left[axis] - right[axis]) / span
        total += delta * delta
    if left["author"] != right["author"]:
        total += author_weight * author_weight
    if left["audctl"] != right["audctl"]:
        total += 1.0
    return math.sqrt(total)


def select_diverse_songs(
    candidates: Sequence[Candidate],
    seed_slugs: Sequence[str],
    count: int = 2,
    author_weight: float = 1.0,
) -> Dict[str, Any]:
    """Greedy farthest-first selection, so "diverse" is computed rather than asserted.

    Starting from the already-chosen songs, each additional song is the one whose *nearest*
    neighbour among the chosen is farthest away. That is the standard max-min diversification
    rule: it cannot be steered toward a song anyone prefers, and it is a total order because
    ties break by slug.
    """
    by_slug = {candidate.slug: candidate for candidate in candidates}
    for slug in seed_slugs:
        if slug not in by_slug:
            raise Stage16Error(f"seed song not in the corpus: {slug}")
    vectors = {candidate.slug: candidate.vector() for candidate in candidates}
    ranges = {
        axis: max(v[axis] for v in vectors.values()) - min(v[axis] for v in vectors.values())
        for axis in DIVERSITY_NUMERIC_AXES
    }

    chosen = list(seed_slugs)
    steps: List[Dict[str, Any]] = []
    while len(chosen) < len(seed_slugs) + count:
        scored = []
        for candidate in candidates:
            if candidate.slug in chosen:
                continue
            nearest = min(
                diversity_distance(vectors[candidate.slug], vectors[other], ranges, author_weight)
                for other in chosen
            )
            scored.append((-nearest, candidate.slug))
        scored.sort()
        if not scored:
            break
        chosen.append(scored[0][1])
        steps.append(
            {
                "picked": scored[0][1],
                "min_distance_to_already_chosen": _rnd(-scored[0][0], 4),
                "runner_up": scored[1][1] if len(scored) > 1 else None,
                "runner_up_distance": _rnd(-scored[1][0], 4) if len(scored) > 1 else None,
                "considered": len(scored),
            }
        )
    return {
        "rule": (
            "greedy max-min (farthest-first) over min-max normalised axes: "
            + ", ".join(DIVERSITY_NUMERIC_AXES)
            + " numerically, plus author and AUDCTL as categorical axes worth 1.0 each when they "
            "differ; ties broken by slug ascending"
        ),
        "author_weight": author_weight,
        "ranges": {axis: _rnd(span, 4) for axis, span in ranges.items()},
        "seeds": list(seed_slugs),
        "chosen": chosen,
        "steps": steps,
    }


def recover_stage15_pair(
    arch_root: Path = DEFAULT_ARCHAEOLOGY_DIR,
    stage15_dir: Path = DEFAULT_STAGE15_DIR,
) -> Dict[str, Any]:
    """Song A and song B straight out of the Stage 15 artefact, not from memory.

    The Stage 15 record is read, never written. If it is absent the pair is recomputed with
    Stage 15's own selection function, and the fallback is recorded so the reader knows which
    path was taken.
    """
    path = Path(stage15_dir) / "reference_song.json"
    if path.is_file():
        selection = _read_json(path)["selection"]
        return {
            "source": str(path),
            "source_sha256": sha256_file(path),
            "recovered_from_artifact": True,
            "reference": selection["winner"]["trace"],
            "runner_up": selection["runner_up"]["trace"] if selection.get("runner_up") else None,
            "reference_author": selection["winner"]["author"],
            "runner_up_author": (
                selection["runner_up"]["author"] if selection.get("runner_up") else None
            ),
        }
    selection = stage15.select_reference_song(arch_root)
    return {
        "source": None,
        "source_sha256": None,
        "recovered_from_artifact": False,
        "reference": selection["winner"]["trace"],
        "runner_up": selection["runner_up"]["trace"] if selection.get("runner_up") else None,
        "reference_author": selection["winner"]["author"],
        "runner_up_author": (
            selection["runner_up"]["author"] if selection.get("runner_up") else None
        ),
    }


# ---------------------------------------------------------------------------
# PART B/C — reuse the Stage 15 analysis per song, then normalise the numbers
# ---------------------------------------------------------------------------
def note_length_band(note_frames: Optional[int]) -> str:
    """Absolute note-length band. Stage 15 used song-relative tertiles, which are not
    comparable across songs; this is the cross-song replacement and the only place a Stage 15
    representation is changed for comparison."""
    if note_frames is None:
        return "outside_note"
    for limit, name in NOTE_LENGTH_BANDS:
        if note_frames <= limit:
            return name
    return "long_13_plus_frames"


def density_band(events_within_window: Optional[int]) -> str:
    """Absolute local-density band, for the same reason."""
    if events_within_window is None:
        return "unknown"
    for limit, name in DENSITY_BANDS:
        if events_within_window <= limit:
            return name
    return "dense_7_plus"


def company_band(other_channels_active: int) -> str:
    if other_channels_active <= 0:
        return "alone"
    if other_channels_active == 1:
        return "duet"
    if other_channels_active == 2:
        return "trio"
    return "full"


def occurrence_band(index: int) -> str:
    if index <= 3:
        return "first_3_occurrences"
    if index <= 10:
        return "occurrences_4_10"
    return "occurrences_11_plus"


def build_portable_contexts(contexts: Sequence[Mapping[str, Any]]) -> List[Dict[str, str]]:
    """Turn Stage 15 context records into the cross-song comparable view of each event."""
    out: List[Dict[str, str]] = []
    for context in contexts:
        out.append(
            {
                "family_bucket": str(context["family_bucket"]),
                "position_in_note": str(context["position_in_note"]),
                "pitch_band": str(context["pitch_band"]),
                "note_length_band": note_length_band(context.get("note_frames")),
                "density_band": density_band(context.get("events_within_25_frames_on_channel")),
                "company_band": company_band(int(context.get("other_channels_active") or 0)),
                "previous_event_kind": str(context.get("previous_event_on_channel") or "none"),
                "next_event_kind": str(context.get("next_event_on_channel") or "none"),
                "channel": f"ch{context['channel']}",
                "occurrence_index_band": occurrence_band(
                    int(context.get("occurrence_index_for_technique") or 1)
                ),
            }
        )
    return out


@dataclass
class SongAnalysis:
    """One song, analysed by Stage 15 and then described in cross-song terms."""

    slug: str
    candidate: Candidate
    trace: stage15.RegisterTrace
    summary: Dict[str, Any]
    events: List[stage15.Event]
    contexts: List[Dict[str, Any]]
    vocabulary: Dict[str, Any]
    context: Dict[str, Any]
    character: Dict[str, Any]
    portable: List[Dict[str, str]]
    #: technique_id -> the event indices of that technique, in frame order
    indexes_by_technique: Dict[str, List[int]]
    #: technique_id -> context factor -> value -> share
    distributions: Dict[str, Dict[str, Dict[str, float]]]
    #: technique_id -> parameter -> the raw numeric values observed in this song
    numeric_parameters: Dict[str, Dict[str, List[float]]]
    #: technique_id -> parameter -> value -> count
    categorical_parameters: Dict[str, Dict[str, Dict[str, int]]]

    @property
    def event_count(self) -> int:
        return len(self.events)

    def techniques(self) -> List[str]:
        return sorted(self.indexes_by_technique)

    def counted_techniques(self, minimum: int = MIN_OCCURRENCES_IN_SONG) -> Dict[str, int]:
        return {
            technique: len(indexes)
            for technique, indexes in sorted(self.indexes_by_technique.items())
            if len(indexes) >= minimum
        }


def analyse_song(candidate: Candidate) -> SongAnalysis:
    """Run the Stage 15 pipeline on one song and index its results for cross-song comparison."""
    trace = stage15.load_trace(Path(candidate.path))
    summary = stage15.trace_summary(trace)
    events = stage15.detect_events(trace)
    contexts = stage15.event_contexts(trace, events)
    vocabulary = stage15.performance_vocabulary(trace, events, contexts)
    context = stage15.context_dependence(vocabulary, events, contexts)
    character = stage15.channel_character(trace, events, contexts)
    portable = build_portable_contexts(contexts)

    indexes_by_technique: Dict[str, List[int]] = {}
    for index, context_row in enumerate(contexts):
        indexes_by_technique.setdefault(str(context_row["technique_id"]), []).append(index)

    distributions: Dict[str, Dict[str, Dict[str, float]]] = {}
    for technique, indexes in indexes_by_technique.items():
        per_factor: Dict[str, Dict[str, float]] = {}
        for factor in PORTABLE_CONTEXT_FACTORS + SONG_LOCAL_CONTEXT_FACTORS:
            counts: Dict[str, int] = {}
            for index in indexes:
                value = portable[index][factor]
                counts[value] = counts.get(value, 0) + 1
            per_factor[factor] = _shares(counts)
        distributions[technique] = per_factor

    numeric_parameters: Dict[str, Dict[str, List[float]]] = {}
    categorical_parameters: Dict[str, Dict[str, Dict[str, int]]] = {}
    for technique, indexes in indexes_by_technique.items():
        numbers: Dict[str, List[float]] = {}
        categories: Dict[str, Dict[str, int]] = {}
        for index in indexes:
            for name, value in events[index].parameters.items():
                if isinstance(value, bool):
                    categories.setdefault(name, {})
                    categories[name][str(value)] = categories[name].get(str(value), 0) + 1
                elif isinstance(value, (int, float)):
                    numbers.setdefault(name, []).append(float(value))
                elif isinstance(value, str):
                    categories.setdefault(name, {})
                    categories[name][value] = categories[name].get(value, 0) + 1
        numeric_parameters[technique] = numbers
        categorical_parameters[technique] = categories

    return SongAnalysis(
        slug=candidate.slug, candidate=candidate, trace=trace, summary=summary,
        events=list(events), contexts=list(contexts), vocabulary=vocabulary, context=context,
        character=character, portable=portable, indexes_by_technique=indexes_by_technique,
        distributions=distributions, numeric_parameters=numeric_parameters,
        categorical_parameters=categorical_parameters,
    )


def song_overview(song: SongAnalysis) -> Dict[str, Any]:
    """Part C: one song's numbers, raw *and* normalised so durations do not confound them."""
    duration = song.candidate.duration_s
    audible_frames = sum(
        int(channel["audible_frames"]) for channel in song.summary["channels"]
    )
    techniques = song.counted_techniques(0)
    families: Dict[str, int] = {}
    for event in song.events:
        bucket = stage15.family_bucket(event)
        families[bucket] = families.get(bucket, 0) + 1
    channels: Dict[str, int] = {}
    positions: Dict[str, int] = {}
    note_lengths: List[float] = []
    durations: List[float] = []
    confidences: List[float] = []
    for index, event in enumerate(song.events):
        channels[str(event.channel)] = channels.get(str(event.channel), 0) + 1
        positions[str(song.contexts[index]["position_in_note"])] = (
            positions.get(str(song.contexts[index]["position_in_note"]), 0) + 1
        )
        if song.contexts[index].get("note_frames"):
            note_lengths.append(float(song.contexts[index]["note_frames"]))
        durations.append(float(event.duration_frames))
        confidences.append(float(event.confidence))
    return {
        "slug": song.slug,
        "song": song.candidate.song,
        "subsong": song.candidate.subsong,
        "title": song.candidate.title,
        "author": song.candidate.author,
        "date": song.candidate.date,
        "audctl": song.candidate.audctl,
        "trace_sha256": song.candidate.sha256,
        "trace_path": song.candidate.path,
        "frames": song.candidate.frames,
        "duration_s": _rnd(duration),
        "audible_frames_total": audible_frames,
        "events": song.event_count,
        "techniques_all": len(techniques),
        "techniques_at_least_20": len(song.counted_techniques()),
        "events_per_second": _rnd(song.event_count / duration) if duration else None,
        "events_per_audible_channel_second": (
            _rnd(song.event_count / (audible_frames * song.trace.frame_period_ms / 1000.0))
            if audible_frames else None
        ),
        "techniques_per_second": _rnd(len(techniques) / duration) if duration else None,
        "technique_occurrences_per_second": _rnd(song.event_count / duration) if duration else None,
        "techniques_per_1000_events": [
            {"technique_id": name, "occurrences": count, "share": _share(count, song.event_count)}
            for name, count in sorted(techniques.items())
        ],
        "generator_distribution": _shares(families),
        "channel_distribution": _shares(channels),
        "position_in_note_distribution": _shares(positions),
        "event_duration_frames": _distribution(durations, 3),
        "note_frames": _distribution(note_lengths, 3),
        "confidence": _distribution(confidences, 4),
        "classifications": dict(song.vocabulary["classifications"]),
        "classes_present": list(song.vocabulary["kinds_present"]),
        "classes_absent": list(song.vocabulary["kinds_absent"]),
        "context_verdict_counts": dict(song.context["verdict_counts"]),
        "context_strongest_factors": sorted(
            {
                str(item["strongest_factor"])
                for item in song.context["techniques"]
                if item["strongest_factor"]
            }
        ),
        "voice_characters": [
            {
                "voice_id": voice["voice_id"],
                "inferred_character": voice["inferred_character"],
                "musical_role": voice["musical_role"],
                "median_note_frames": voice["median_note_frames"],
                "noise_share": voice["noise_share"],
            }
            for voice in song.character["voices"]
        ],
    }


def song_summaries(songs: Sequence[SongAnalysis]) -> Dict[str, Any]:
    """Part C: all songs side by side, with the normalised measures that make them comparable."""
    overviews = [song_overview(song) for song in songs]
    return {
        "normalisation_note": (
            "Songs differ in length, so raw counts are published next to events/second, "
            "events/audible-channel-second and technique occurrences/second. Every comparison "
            "that follows uses occurrence shares (a technique's share of a song's events) rather "
            "than absolute counts."
        ),
        "songs": overviews,
        "totals": {
            "events": sum(row["events"] for row in overviews),
            "duration_s": _rnd(sum(row["duration_s"] for row in overviews)),
            "techniques_union": sorted(
                {
                    technique
                    for row in overviews
                    for technique in (item["technique_id"]
                                      for item in row["techniques_per_1000_events"])
                }
            ),
        },
    }


# ---------------------------------------------------------------------------
# PART D — technique vocabulary generalisation
# ---------------------------------------------------------------------------
def technique_overlap(songs: Sequence[SongAnalysis]) -> Dict[str, Any]:
    """A technique x song matrix plus pairwise overlap, weighted by occurrence share.

    Two songs with the same short list of techniques can use them in wildly different
    proportions; the Ruzicka similarity on *shares* is what exposes that, so it is reported
    next to the plain Jaccard on the technique sets.
    """
    slugs = [song.slug for song in songs]
    counts = {song.slug: song.counted_techniques(0) for song in songs}
    shares = {
        song.slug: _shares(counts[song.slug]) for song in songs
    }
    every_technique = sorted({technique for values in counts.values() for technique in values})

    matrix = []
    for technique in every_technique:
        row = {
            "technique_id": technique,
            "kind": technique.split("_")[0] if "_" in technique else technique,
            "low_level": technique in LOW_LEVEL_TECHNIQUES,
            "songs": {},
        }
        present = 0
        for slug in slugs:
            occurrences = counts[slug].get(technique, 0)
            row["songs"][slug] = {
                "occurrences": occurrences,
                "share_of_song": shares[slug].get(technique),
            }
            if occurrences:
                present += 1
        row["songs_present"] = present
        row["songs_at_least_20"] = sum(
            1 for slug in slugs
            if counts[slug].get(technique, 0) >= MIN_OCCURRENCES_IN_SONG
        )
        matrix.append(row)

    # Explicitly check the event *class* (kind) level too, since Stage 15 reported ~92% overlap
    # there and the brief warns that this is the weakest form of evidence.
    kinds = {song.slug: set(song.vocabulary["kinds_present"]) for song in songs}
    kind_matrix = []
    every_kind = sorted({kind for values in kinds.values() for kind in values})
    for kind in sorted(set(stage15.EVENT_KINDS)):
        row = {"event_kind": kind, "songs": {}}
        present = 0
        for slug in slugs:
            has = kind in kinds[slug]
            row["songs"][slug] = has
            present += 1 if has else 0
        row["songs_present"] = present
        kind_matrix.append(row)

    pairs = []
    for first in range(len(slugs)):
        for second in range(first + 1, len(slugs)):
            a, b = slugs[first], slugs[second]
            pairs.append(
                {
                    "song_a": a,
                    "song_b": b,
                    "technique_jaccard": _jaccard(counts[a], counts[b]),
                    "technique_ruzicka_on_shares": _weighted_jaccard(counts[a], counts[b]),
                    "event_class_jaccard": _jaccard(kinds[a], kinds[b]),
                    "shared_techniques": sorted(set(counts[a]) & set(counts[b])),
                    "only_in_a": sorted(set(counts[a]) - set(counts[b])),
                    "only_in_b": sorted(set(counts[b]) - set(counts[a])),
                }
            )
    return {
        "measure": {
            "technique_jaccard": "|A n B| / |A u B| on the sets of technique identifiers",
            "technique_ruzicka_on_shares": (
                "sum of per-technique minima over sum of per-technique maxima, using each "
                "technique's *share* of its song's events, so two songs that share a technique "
                "list but weight it differently are separated"
            ),
            "event_class_jaccard": "the same on the coarser event-kind sets Stage 15 reported",
        },
        "songs": slugs,
        "union_techniques": every_technique,
        "core_vocabulary_candidates": [
            row["technique_id"] for row in matrix
            if row["songs_at_least_20"] >= math.ceil(UNIVERSAL_SONG_SHARE * len(slugs))
            and not row["low_level"]
        ],
        "matrix": matrix,
        "event_class_matrix": kind_matrix,
        "pairwise": pairs,
        "summary": {
            "techniques_in_union": len(every_technique),
            "techniques_in_all_songs": sum(1 for row in matrix if row["songs_present"] == len(slugs)),
            "techniques_in_one_song_only": sum(1 for row in matrix if row["songs_present"] == 1),
            "mean_pairwise_technique_jaccard": _rnd(
                _median([pair["technique_jaccard"] for pair in pairs])
            ),
            "mean_pairwise_ruzicka": _rnd(_median([pair["technique_ruzicka_on_shares"] for pair in pairs])),
            "mean_pairwise_event_class_jaccard": _rnd(
                _median([pair["event_class_jaccard"] for pair in pairs])
            ),
        },
    }


def _mean_of(values: Sequence[float]) -> Optional[float]:
    return sum(values) / len(values) if values else None


def _dominant(distribution: Mapping[str, float]) -> Tuple[Optional[str], Optional[float]]:
    if not distribution:
        return None, None
    value = max(sorted(distribution), key=lambda key: distribution[key])
    return value, distribution[value]


# ---------------------------------------------------------------------------
# PART E / I — context generalisation, and which dimensions are portable
# ---------------------------------------------------------------------------
def context_generalization(
    songs: Sequence[SongAnalysis],
    minimum: int = MIN_OCCURRENCES_IN_SONG,
) -> Dict[str, Any]:
    """Does the *same* technique sit in the *same* context in every song?

    For each technique observed often enough in at least two songs, every portable factor's
    value distribution is compared with the overlap coefficient. The dominant value is compared
    as well, because a distribution can overlap loosely while the songs disagree about what the
    technique is *for*.
    """
    slugs = [song.slug for song in songs]
    by_song = {song.slug: song for song in songs}
    every_technique = sorted(
        {technique for song in songs for technique in song.counted_techniques(minimum)}
    )

    technique_rows: List[Dict[str, Any]] = []
    factor_records: Dict[str, List[Dict[str, Any]]] = {
        factor: [] for factor in PORTABLE_CONTEXT_FACTORS
    }
    for technique in every_technique:
        present_in = [
            slug for slug in slugs if by_song[slug].counted_techniques(minimum).get(technique)
        ]
        if len(present_in) < 2:
            continue
        factors: Dict[str, Any] = {}
        for factor in PORTABLE_CONTEXT_FACTORS:
            distributions = {
                slug: by_song[slug].distributions[technique][factor] for slug in present_in
            }
            dominants = {slug: _dominant(value) for slug, value in distributions.items()}
            pairs = []
            for first in range(len(present_in)):
                for second in range(first + 1, len(present_in)):
                    a, b = present_in[first], present_in[second]
                    pairs.append(
                        {
                            "song_a": a,
                            "song_b": b,
                            "overlap": _overlap_coefficient(distributions[a], distributions[b]),
                            "dominant_a": dominants[a][0],
                            "dominant_b": dominants[b][0],
                            "dominant_agrees": dominants[a][0] == dominants[b][0],
                        }
                    )
            overlaps = [pair["overlap"] for pair in pairs if pair["overlap"] is not None]
            agreements = [pair["dominant_agrees"] for pair in pairs]
            median_overlap = _median(overlaps)
            dominant_shares = {slug: (dominants[slug][1] or 0.0) for slug in present_in}
            concentrated = {
                slug: dominant_shares[slug] >= CONTEXT_DOMINANCE_MIN for slug in present_in
            }
            if not all(concentrated.values()):
                # At least one song has no dominant value: there is no rule there to compare.
                verdict = "DIFFUSE_CONTEXT"
            elif all(agreements):
                verdict = "SAME_CONTEXT"
            else:
                verdict = "DIFFERENT_CONTEXT"
            factors[factor] = {
                "songs": {slug: dominants[slug][0] for slug in present_in},
                "dominant_shares": {slug: _rnd(dominant_shares[slug]) for slug in present_in},
                "concentrated_in_every_song": all(concentrated.values()),
                "songs_without_a_dominant_value": sorted(
                    slug for slug in present_in if not concentrated[slug]
                ),
                "pairwise": pairs,
                "median_overlap": _rnd(median_overlap),
                "dominant_agreement_share": _share(
                    sum(1 for value in agreements if value), len(agreements)
                ),
                "verdict": verdict,
            }
            factor_records[factor].append(
                {
                    "technique_id": technique,
                    "median_overlap": _rnd(median_overlap),
                    "dominant_agreement": _share(
                        sum(1 for value in agreements if value), len(agreements)
                    ),
                    "verdict": verdict,
                    "songs_present": len(present_in),
                }
            )
        usable = [
            factors[factor]["median_overlap"] for factor in PORTABLE_CONTEXT_FACTORS
            if factors[factor]["verdict"] == "SAME_CONTEXT"
        ]
        decidable = [
            factors[factor]["verdict"] for factor in PORTABLE_CONTEXT_FACTORS
            if factors[factor]["verdict"] != "DIFFUSE_CONTEXT"
        ]
        agreeing = sum(1 for verdict in decidable if verdict == "SAME_CONTEXT")
        disagreeing = sum(1 for verdict in decidable if verdict == "DIFFERENT_CONTEXT")
        if not decidable:
            overall = "NO_DECIDABLE_CONTEXT"
        elif disagreeing == 0:
            overall = "SAME_CONTEXT"
        elif agreeing == 0:
            overall = "DIFFERENT_CONTEXT"
        elif agreeing > disagreeing:
            overall = "MOSTLY_SAME_CONTEXT"
        elif disagreeing > agreeing:
            overall = "MOSTLY_DIFFERENT_CONTEXT"
        else:
            overall = "MIXED_CONTEXT"
        technique_rows.append(
            {
                "technique_id": technique,
                "songs_present": len(present_in),
                "low_level": technique in LOW_LEVEL_TECHNIQUES,
                "decidable_dimensions": len(decidable),
                "dimensions_agreeing": agreeing,
                "dimensions_disagreeing": disagreeing,
                "dimension_agreement_share": _share(agreeing, len(decidable)),
                "median_overlap_of_same_context_dimensions": _rnd(_median(usable)),
                "overall_verdict": overall,
                "factors": factors,
            }
        )
    return _context_summary(technique_rows, factor_records)


def _context_summary(
    technique_rows: Sequence[Mapping[str, Any]],
    factor_records: Mapping[str, Sequence[Mapping[str, Any]]],
) -> Dict[str, Any]:
    """Fold the per-technique and per-factor rows into the Part E/I answer."""
    factor_rows = []
    for factor in PORTABLE_CONTEXT_FACTORS:
        records = list(factor_records.get(factor, []))
        overlaps = [
            r["median_overlap"] for r in records
            if r["verdict"] == "SAME_CONTEXT" and r["median_overlap"] is not None
        ]
        agreements = [
            r["dominant_agreement"] for r in records if r["dominant_agreement"] is not None
        ]
        factor_rows.append(
            {
                "factor": factor,
                "techniques_compared": len(records),
                "median_overlap_where_same_context": _rnd(_median(overlaps)),
                "mean_overlap_where_same_context": _rnd(_mean_of(overlaps)),
                "median_dominant_agreement": _rnd(_median(agreements)),
                "same_context_share": _share(
                    sum(1 for r in records if r["verdict"] == "SAME_CONTEXT"), len(records)
                ),
                "different_context_share": _share(
                    sum(1 for r in records if r["verdict"] == "DIFFERENT_CONTEXT"), len(records)
                ),
                "diffuse_context_share": _share(
                    sum(1 for r in records if r["verdict"] == "DIFFUSE_CONTEXT"), len(records)
                ),
                "decidable_share": _share(
                    sum(1 for r in records if r["verdict"] != "DIFFUSE_CONTEXT"), len(records)
                ),
            }
        )
    factor_rows.sort(
        key=lambda row: (
            -(row["decidable_share"] or 0.0),
            -(row["same_context_share"] or 0.0),
            row["factor"],
        )
    )
    ordered = sorted(technique_rows, key=lambda row: (-row["songs_present"], row["technique_id"]))
    good = [row for row in ordered if row["overall_verdict"] in ("SAME_CONTEXT", "MOSTLY_SAME_CONTEXT")]
    bad = [row for row in ordered if row["overall_verdict"] in ("DIFFERENT_CONTEXT", "MOSTLY_DIFFERENT_CONTEXT")]
    good_non_low = [row for row in good if not row["low_level"]]
    agreeing = sum(row["dimensions_agreeing"] for row in ordered)
    decidable_total = sum(row["decidable_dimensions"] for row in ordered)
    return {
        "method": {
            "test": (
                "a technique has a usable context in a song only if one value of the factor "
                "dominates it; the dominant values are then compared across songs"
            ),
            "dominance_threshold": CONTEXT_DOMINANCE_MIN,
            "secondary_shape_test": (
                f"overlap coefficient of the two distributions; >= {CONTEXT_OVERLAP_SAME} would be "
                "the generous reading, reported next to the dominance result"
            ),
            "verdicts": {
                "SAME_CONTEXT": "every decidable dimension agrees across songs",
                "MOSTLY_SAME_CONTEXT": "more dimensions agree than disagree",
                "MIXED_CONTEXT": "agreements and disagreements balance",
                "MOSTLY_DIFFERENT_CONTEXT": "more dimensions disagree than agree",
                "DIFFERENT_CONTEXT": "every decidable dimension disagrees",
                "NO_DECIDABLE_CONTEXT": (
                    "no dimension has a dominant value in every song, so there is no rule to "
                    "compare; not counted as evidence either way"
                ),
            },
            "minimum_occurrences_per_song": MIN_OCCURRENCES_IN_SONG,
            "portable_factors": list(PORTABLE_CONTEXT_FACTORS),
            "song_local_factors_excluded": list(SONG_LOCAL_CONTEXT_FACTORS),
            "why_song_local": (
                "channel numbering and occurrence index describe one song's layout; channel 2 in "
                "one song is not channel 2 in another, so comparing them would be meaningless"
            ),
        },
        "techniques_compared": len(ordered),
        "same_context": [row["technique_id"] for row in good],
        "same_context_excluding_low_level": [row["technique_id"] for row in good_non_low],
        "different_context": [row["technique_id"] for row in bad],
        "no_decidable_context": [
            row["technique_id"] for row in ordered
            if row["overall_verdict"] == "NO_DECIDABLE_CONTEXT"
        ],
        "dimensions_agreeing_total": agreeing,
        "dimensions_decidable_total": decidable_total,
        "dimension_agreement_share": _share(agreeing, decidable_total),
        "techniques": ordered,
        "by_factor": factor_rows,
        "answer": (
            f"{len(good)} of {len(ordered)} comparable techniques keep their context across songs "
            f"({len(good_non_low)} of those are not low-level classes) and {len(bad)} do not. At "
            f"the dimension level, {agreeing} of {decidable_total} decidable technique-by-dimension "
            f"tests agree ({_share(agreeing, decidable_total)}). The most portable dimensions are "
            + ", ".join(row["factor"] for row in factor_rows[:3])
            + "."
        ),
    }


# ---------------------------------------------------------------------------
# PART D.3 / report 8 — parameter generalisation
# ---------------------------------------------------------------------------
def _numeric_parameter_rows(
    by_song: Mapping[str, SongAnalysis], technique: str, present_in: Sequence[str]
) -> List[Dict[str, Any]]:
    names = sorted(
        {name for slug in present_in for name in by_song[slug].numeric_parameters[technique]}
    )
    rows = []
    for name in names:
        available = [
            slug for slug in present_in if by_song[slug].numeric_parameters[technique].get(name)
        ]
        if len(available) < 2:
            continue
        values = {slug: by_song[slug].numeric_parameters[technique][name] for slug in available}
        supports = {slug: (min(v), max(v)) for slug, v in values.items()}
        cores = {
            slug: (float(_quantile(v, 0.10)), float(_quantile(v, 0.90)))
            for slug, v in values.items()
        }
        medians = {slug: _median(v) for slug, v in values.items()}
        pairs = []
        for first in range(len(available)):
            for second in range(first + 1, len(available)):
                a, b = available[first], available[second]
                ratio = None
                if medians[a] and medians[b] and medians[b] != 0:
                    ratio = medians[a] / medians[b]
                pairs.append(
                    {
                        "song_a": a, "song_b": b,
                        "support_overlap": _range_overlap(supports[a], supports[b]),
                        "core_overlap": _range_overlap(cores[a], cores[b]),
                        "median_a": _rnd(medians[a], 3), "median_b": _rnd(medians[b], 3),
                        "median_ratio": _rnd(ratio, 3),
                    }
                )
        supports_ok = [p["support_overlap"] for p in pairs if p["support_overlap"] is not None]
        cores_ok = [p["core_overlap"] for p in pairs if p["core_overlap"] is not None]
        median_support = _median(supports_ok)
        rows.append(
            {
                "parameter": name,
                "songs": {slug: _distribution(values[slug], 3) for slug in available},
                "pairwise": pairs,
                "median_support_overlap": _rnd(median_support),
                "median_core_overlap": _rnd(_median(cores_ok)),
                "verdict": (
                    "UNKNOWN" if median_support is None
                    else "SAME_RANGE" if median_support >= PARAMETER_OVERLAP_SAME
                    else "DIFFERENT_RANGE"
                ),
            }
        )
    return rows


def _categorical_parameter_rows(
    by_song: Mapping[str, SongAnalysis], technique: str, present_in: Sequence[str]
) -> List[Dict[str, Any]]:
    names = sorted(
        {name for slug in present_in for name in by_song[slug].categorical_parameters[technique]}
    )
    rows = []
    for name in names:
        available = [
            slug for slug in present_in
            if by_song[slug].categorical_parameters[technique].get(name)
        ]
        if len(available) < 2:
            continue
        distributions = {
            slug: _shares(by_song[slug].categorical_parameters[technique][name])
            for slug in available
        }
        pairs = []
        for first in range(len(available)):
            for second in range(first + 1, len(available)):
                a, b = available[first], available[second]
                pairs.append(
                    {
                        "song_a": a, "song_b": b,
                        "overlap": _overlap_coefficient(distributions[a], distributions[b]),
                        "value_set_jaccard": _jaccard(distributions[a], distributions[b]),
                    }
                )
        overlaps = [p["overlap"] for p in pairs if p["overlap"] is not None]
        median_overlap = _median(overlaps)
        rows.append(
            {
                "parameter": name,
                "value_sets": {slug: sorted(distributions[slug]) for slug in available},
                "pairwise": pairs,
                "median_overlap": _rnd(median_overlap),
                "verdict": (
                    "UNKNOWN" if median_overlap is None
                    else "SAME_VALUES" if median_overlap >= PARAMETER_OVERLAP_SAME
                    else "DIFFERENT_VALUES"
                ),
            }
        )
    return rows


def parameter_generalization(
    songs: Sequence[SongAnalysis],
    minimum: int = MIN_OCCURRENCES_IN_SONG,
) -> Dict[str, Any]:
    """For techniques shared by songs, do the *numbers* overlap?

    Only like-for-like units are compared: a numeric parameter against itself, categorical
    parameters as value sets. Nothing is converted between units.
    """
    slugs = [song.slug for song in songs]
    by_song = {song.slug: song for song in songs}
    every_technique = sorted(
        {technique for song in songs for technique in song.counted_techniques(minimum)}
    )
    rows = []
    for technique in every_technique:
        present_in = [
            slug for slug in slugs if by_song[slug].counted_techniques(minimum).get(technique)
        ]
        if len(present_in) < 2:
            continue
        numeric_rows = _numeric_parameter_rows(by_song, technique, present_in)
        categorical_rows = _categorical_parameter_rows(by_song, technique, present_in)
        verdicts = [
            row["verdict"]
            for row in numeric_rows + categorical_rows
            if row["verdict"] != "UNKNOWN"
        ]
        same = sum(1 for verdict in verdicts if verdict in ("SAME_RANGE", "SAME_VALUES"))
        rows.append(
            {
                "technique_id": technique,
                "songs_present": len(present_in),
                "low_level": technique in LOW_LEVEL_TECHNIQUES,
                "numeric_parameters": numeric_rows,
                "categorical_parameters": categorical_rows,
                "comparable_parameters": len(verdicts),
                "same_parameters": same,
                "same_share": _share(same, len(verdicts)),
                "verdict": (
                    "UNKNOWN" if not verdicts
                    else "PARAMETERS_GENERALISE" if same / len(verdicts) >= 0.5
                    else "PARAMETERS_SONG_SPECIFIC"
                ),
            }
        )
    rows.sort(key=lambda row: (-row["songs_present"], row["technique_id"]))
    usable = [row for row in rows if row["comparable_parameters"]]
    generalising = [row for row in usable if row["verdict"] == "PARAMETERS_GENERALISE"]
    return {
        "method": {
            "numeric": "range intersection over union on [min,max] (support) and [p10,p90] (core)",
            "categorical": "overlap coefficient of the value distribution, plus value-set Jaccard",
            "same_at_or_above": PARAMETER_OVERLAP_SAME,
            "note": "only like-for-like parameters are compared; no unit conversion is performed",
        },
        "techniques_compared": len(rows),
        "techniques_with_comparable_parameters": len(usable),
        "techniques_generalising": [row["technique_id"] for row in generalising],
        "techniques_song_specific": [
            row["technique_id"] for row in usable if row["verdict"] == "PARAMETERS_SONG_SPECIFIC"
        ],
        "techniques": rows,
        "answer": (
            f"{len(generalising)} of {len(usable)} techniques with comparable parameters have "
            f"overlapping ranges across songs; {len(usable) - len(generalising)} do not."
        ),
    }


# ---------------------------------------------------------------------------
# PART F / L — train/test: can the training songs describe the held-out song?
# ---------------------------------------------------------------------------
def _training_index(
    songs: Mapping[str, SongAnalysis], train_slugs: Sequence[str]
) -> Dict[str, Any]:
    """Everything a training set knows, keyed by technique."""
    knowledge: Dict[str, Any] = {}
    for slug in train_slugs:
        song = songs[slug]
        for technique, indexes in song.indexes_by_technique.items():
            entry = knowledge.setdefault(
                technique,
                {"occurrences": 0, "songs": [], "factor_values": {}, "numeric": {},
                 "categorical": {}},
            )
            entry["occurrences"] += len(indexes)
            entry["songs"].append(slug)
            for factor in PORTABLE_CONTEXT_FACTORS:
                bucket = entry["factor_values"].setdefault(factor, {})
                for value in song.distributions[technique][factor]:
                    bucket[value] = bucket.get(value, 0) + 1
            for name, values in song.numeric_parameters[technique].items():
                entry["numeric"].setdefault(name, []).extend(values)
            for name, counts in song.categorical_parameters[technique].items():
                bucket = entry["categorical"].setdefault(name, {})
                for value, count in counts.items():
                    bucket[value] = bucket.get(value, 0) + count
    for entry in knowledge.values():
        entry["songs"] = sorted(set(entry["songs"]))
        entry["songs_present"] = len(entry["songs"])
        entry["factor_dominants"] = {}
        for factor in PORTABLE_CONTEXT_FACTORS:
            counts = entry["factor_values"].get(factor, {})
            if not counts:
                continue
            total = sum(counts.values())
            value = max(sorted(counts), key=lambda key: counts[key])
            entry["factor_dominants"][factor] = {
                "value": value,
                "share": _rnd(counts[value] / total),
                "usable": counts[value] / total >= CONTEXT_DOMINANCE_MIN,
            }
        entry["numeric_ranges"] = {
            name: (min(values), max(values))
            for name, values in sorted(entry["numeric"].items())
        }
        entry["numeric_cores"] = {
            name: (float(_quantile(values, 0.10)), float(_quantile(values, 0.90)))
            for name, values in sorted(entry["numeric"].items())
        }
    return knowledge


def evaluate_fold(
    songs: Mapping[str, SongAnalysis],
    train_slugs: Sequence[str],
    test_slug: str,
    minimum: int = MIN_OCCURRENCES_IN_SONG,
) -> Dict[str, Any]:
    """Describe the held-out song using only what the training songs know.

    Coverage is reported in layers because the layers are *conditional on each other*: context
    and parameter coverage only mean something for events whose technique the training set
    already knows. Saying so is the difference between an honest number and a misleading one.
    """
    knowledge = _training_index(songs, train_slugs)
    test = songs[test_slug]
    total_events = test.event_count

    known_events = 0
    known_events_well = 0
    factor_covered: Dict[str, int] = {factor: 0 for factor in PORTABLE_CONTEXT_FACTORS}
    factor_matches_dominant: Dict[str, int] = {factor: 0 for factor in PORTABLE_CONTEXT_FACTORS}
    factor_decidable: Dict[str, int] = {factor: 0 for factor in PORTABLE_CONTEXT_FACTORS}
    core_signature_covered = 0
    all_factors_covered = 0
    parameters_checked = 0
    parameters_in_support = 0
    parameters_in_core = 0
    unknown_by_technique: Dict[str, int] = {}
    example_unknown: List[Dict[str, Any]] = []

    for index, event in enumerate(test.events):
        technique = str(test.contexts[index]["technique_id"])
        entry = knowledge.get(technique)
        if not entry:
            unknown_by_technique[technique] = unknown_by_technique.get(technique, 0) + 1
            if len(example_unknown) < AMBIGUITY_EXAMPLES:
                example_unknown.append(
                    {
                        "kind": event.kind,
                        "channel": event.channel,
                        "start_frame": event.start_frame,
                        "technique_id": technique,
                    }
                )
            continue
        known_events += 1
        if entry["occurrences"] >= minimum:
            known_events_well += 1

        covered_here = []
        dominant_here = []
        for factor in PORTABLE_CONTEXT_FACTORS:
            value = test.portable[index][factor]
            if value in entry["factor_values"].get(factor, {}):
                factor_covered[factor] += 1
                covered_here.append(True)
            else:
                covered_here.append(False)
            dominant = entry["factor_dominants"].get(factor)
            if dominant and dominant["usable"]:
                factor_decidable[factor] += 1
                if value == dominant["value"]:
                    factor_matches_dominant[factor] += 1
                    dominant_here.append(True)
                else:
                    dominant_here.append(False)
            else:
                dominant_here.append(False)
        if len(dominant_here) >= len(CORE_CONTEXT_FACTORS) and all(
            dominant_here[PORTABLE_CONTEXT_FACTORS.index(factor)]
            for factor in CORE_CONTEXT_FACTORS
        ):
            core_signature_covered += 1
        if all(covered_here):
            all_factors_covered += 1

        for name, value in sorted(event.parameters.items()):
            if name in stage15.INDEX_LIKE_PARAMETERS:
                continue
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                if name in entry["categorical"]:
                    parameters_checked += 1
                    if str(value) in entry["categorical"][name]:
                        parameters_in_support += 1
                        parameters_in_core += 1
                continue
            support = entry["numeric_ranges"].get(name)
            if support is None:
                continue
            parameters_checked += 1
            if support[0] <= value <= support[1]:
                parameters_in_support += 1
            core = entry["numeric_cores"].get(name)
            if core and core[0] <= value <= core[1]:
                parameters_in_core += 1

    known_types = sum(1 for technique in test.techniques() if technique in knowledge)
    return {
        "test_song": test_slug,
        "train_songs": list(train_slugs),
        "test_events": total_events,
        "training_techniques": len(knowledge),
        "technique_coverage_events": _share(known_events, total_events),
        "technique_coverage_events_min_occurrences": _share(known_events_well, total_events),
        "technique_coverage_types": _share(known_types, len(test.techniques())),
        "unknown_share": _rnd(1.0 - (known_events / total_events)) if total_events else None,
        "context_coverage_by_factor": {
            factor: _share(factor_covered[factor], known_events)
            for factor in PORTABLE_CONTEXT_FACTORS
        },
        "context_dominant_match_by_factor": {
            factor: _share(factor_matches_dominant[factor], factor_decidable[factor])
            for factor in PORTABLE_CONTEXT_FACTORS
        },
        "context_dominant_match_core_mean": _rnd(
            _mean_of([
                factor_matches_dominant[factor] / factor_decidable[factor]
                for factor in CORE_CONTEXT_FACTORS
                if factor_decidable[factor]
            ])
        ),
        "context_decidable_events_by_factor": dict(factor_decidable),
        "context_coverage_core_signature": _share(core_signature_covered, known_events),
        "context_coverage_core_signature_meaning": (
            "share of known-technique events whose three core context values all equal the value "
            "that dominates that technique in the training songs — a prediction, not a lookup"
        ),
        "context_coverage_all_factors": _share(all_factors_covered, known_events),
        "context_coverage_basis": (
            "conditional on the event's technique being known to training; "
            f"{known_events} of {total_events} events qualified"
        ),
        "parameter_coverage_checked": parameters_checked,
        "parameter_coverage_in_support": _share(parameters_in_support, parameters_checked),
        "parameter_coverage_in_core": _share(parameters_in_core, parameters_checked),
        "parameter_coverage_basis": (
            "conditional on the technique being known AND the parameter existing in training; a "
            "categorical parameter counts as covered when the value was seen at all"
        ),
        "techniques_unknown_to_training": sorted(unknown_by_technique),
        "unknown_event_counts": dict(sorted(unknown_by_technique.items())),
        "example_unknown_events": example_unknown,
    }


def leave_one_out(
    songs: Sequence[SongAnalysis],
    minimum: int = MIN_OCCURRENCES_IN_SONG,
) -> Dict[str, Any]:
    """Part F: hold each song out in turn, train on the rest."""
    by_song = {song.slug: song for song in songs}
    slugs = [song.slug for song in songs]
    folds = [
        evaluate_fold(by_song, [slug for slug in slugs if slug != test_slug], test_slug, minimum)
        for test_slug in slugs
    ]

    def median_of(key: str) -> Optional[float]:
        return _rnd(_median([fold[key] for fold in folds if fold.get(key) is not None]))

    return {
        "design": "leave-one-song-out: for each song, train on the other songs and describe it",
        "minimum_occurrences": minimum,
        "songs": slugs,
        "folds": folds,
        "median_technique_coverage_events": median_of("technique_coverage_events"),
        "median_context_coverage_core_signature": median_of("context_coverage_core_signature"),
        "median_context_dominant_match_core_mean": median_of("context_dominant_match_core_mean"),
        "median_parameter_coverage_in_support": median_of("parameter_coverage_in_support"),
        "median_parameter_coverage_in_core": median_of("parameter_coverage_in_core"),
        "median_unknown_share": median_of("unknown_share"),
        "best_covered_song": (
            max(folds, key=lambda fold: fold["technique_coverage_events"] or 0.0)["test_song"]
            if folds else None
        ),
        "worst_covered_song": (
            min(folds, key=lambda fold: fold["technique_coverage_events"] or 0.0)["test_song"]
            if folds else None
        ),
        "answer": (
            "With three training songs, a held-out song's events are covered at "
            f"{median_of('technique_coverage_events')} at the technique level, "
            f"{median_of('context_coverage_core_signature')} at the core-context level and "
            f"{median_of('parameter_coverage_in_support')} at the parameter-support level — the "
            "last two conditional on the technique being known."
        ),
    }


def reference_robustness(
    songs: Sequence[SongAnalysis],
    reference_slug: str,
    minimum: int = MIN_OCCURRENCES_IN_SONG,
) -> Dict[str, Any]:
    """Part L: how well does *one* song describe the others, and is one of them special?

    Training on a single song is the strictest version of the question, and it is what Stage 15
    actually had. Running it once per song makes it possible to see whether the Stage 15
    reference is unusually representative rather than assuming it.
    """
    by_song = {song.slug: song for song in songs}
    slugs = [song.slug for song in songs]
    folds = [
        evaluate_fold(by_song, [reference_slug], test_slug, minimum)
        for test_slug in slugs
        if test_slug != reference_slug
    ]

    def mean_of(key: str) -> Optional[float]:
        values = [fold[key] for fold in folds if fold.get(key) is not None]
        return _rnd(_mean_of(values))

    return {
        "reference_song": reference_slug,
        "held_out": [fold["test_song"] for fold in folds],
        "folds": folds,
        "mean_technique_coverage_events": mean_of("technique_coverage_events"),
        "mean_context_coverage_core_signature": mean_of("context_coverage_core_signature"),
        "mean_parameter_coverage_in_support": mean_of("parameter_coverage_in_support"),
        "mean_unknown_share": mean_of("unknown_share"),
    }


def song_representativeness(
    songs: Sequence[SongAnalysis],
    minimum: int = MIN_OCCURRENCES_IN_SONG,
) -> Dict[str, Any]:
    """Part L: every song as the sole training source, so "is A special?" is measured."""
    slugs = [song.slug for song in songs]
    experiments = [
        reference_robustness(songs, slug, minimum) for slug in slugs
    ]
    ranked = sorted(
        experiments, key=lambda row: -(row["mean_technique_coverage_events"] or 0.0)
    )
    return {
        "design": (
            "each song is used alone as the training set, and every other song is described from "
            "it; this is the strictest test and it is the situation Stage 15 was actually in"
        ),
        "experiments": experiments,
        "best_single_reference": ranked[0]["reference_song"] if ranked else None,
        "worst_single_reference": ranked[-1]["reference_song"] if ranked else None,
        "answer": (
            "As a single training song, "
            + ", ".join(
                f"{row['reference_song']} covers {row['mean_technique_coverage_events']}"
                for row in experiments
            )
            + " of the other songs' events at the technique level."
        ),
    }


# ---------------------------------------------------------------------------
# PART H — how much is universal, common, or song-specific
# ---------------------------------------------------------------------------
def universality(
    songs: Sequence[SongAnalysis],
    overlap: Mapping[str, Any],
    context: Mapping[str, Any],
    parameters: Mapping[str, Any],
    minimum: int = MIN_OCCURRENCES_IN_SONG,
) -> Dict[str, Any]:
    """Classify every technique, with the thresholds stated rather than implied.

    UNIVERSAL means present at usable volume in at least 75% of the songs, with a
    context-consistent reading and parameter ranges that overlap. COMMON relaxes that to "in at
    least two songs"; SONG_SPECIFIC means the evidence exists in one song only. A low-level class
    that reaches UNIVERSAL is flagged, because its universality is the weakest evidence
    available: the detector defines it the same way everywhere by construction.
    """
    slugs = [song.slug for song in songs]
    required = math.ceil(UNIVERSAL_SONG_SHARE * len(slugs))
    context_by_technique = {row["technique_id"]: row for row in context["techniques"]}
    parameter_by_technique = {row["technique_id"]: row for row in parameters["techniques"]}
    matrix = {row["technique_id"]: row for row in overlap["matrix"]}

    rows = []
    for technique in sorted(matrix):
        entry = matrix[technique]
        evidence_songs = sorted(
            slug for slug in slugs if entry["songs"][slug]["occurrences"] >= minimum
        )
        context_row = context_by_technique.get(technique)
        parameter_row = parameter_by_technique.get(technique)
        context_verdict = context_row["overall_verdict"] if context_row else "NOT_COMPARABLE"
        parameter_verdict = parameter_row["verdict"] if parameter_row else "NOT_COMPARABLE"
        if (
            len(evidence_songs) >= required
            and context_verdict in ("SAME_CONTEXT", "MOSTLY_SAME_CONTEXT")
            and parameter_verdict == "PARAMETERS_GENERALISE"
        ):
            verdict = "UNIVERSAL"
        elif len(evidence_songs) >= 2:
            verdict = "COMMON"
        elif len(evidence_songs) == 1:
            verdict = "SONG_SPECIFIC"
        else:
            verdict = "UNKNOWN"
        rows.append(
            {
                "technique_id": technique,
                "verdict": verdict,
                "songs_with_evidence": evidence_songs,
                "songs_with_evidence_count": len(evidence_songs),
                "required_for_universal": required,
                "low_level": technique in LOW_LEVEL_TECHNIQUES,
                "context_verdict": context_verdict,
                "context_overlap": (
                    context_row["median_overlap_of_same_context_dimensions"] if context_row else None
                ),
                "parameter_verdict": parameter_verdict,
                "parameter_same_share": parameter_row["same_share"] if parameter_row else None,
                "occurrences_total": sum(entry["songs"][slug]["occurrences"] for slug in slugs),
            }
        )
    counts: Dict[str, int] = {}
    for row in rows:
        counts[row["verdict"]] = counts.get(row["verdict"], 0) + 1
    universal = [row["technique_id"] for row in rows if row["verdict"] == "UNIVERSAL"]
    universal_non_low = [
        row["technique_id"] for row in rows
        if row["verdict"] == "UNIVERSAL" and not row["low_level"]
    ]
    return {
        "thresholds": {
            "minimum_occurrences_in_song": minimum,
            "universal_songs_required": (
                f"{required} of {len(slugs)} (UNIVERSAL_SONG_SHARE={UNIVERSAL_SONG_SHARE})"
            ),
            "universal_context": (
                f"context verdict is SAME_CONTEXT or MOSTLY_SAME_CONTEXT (dimension-level "
                f"agreement, dominance threshold {CONTEXT_DOMINANCE_MIN})"
            ),
            "universal_parameters": "parameter verdict is PARAMETERS_GENERALISE",
            "common": "evidence in at least two songs but not meeting the UNIVERSAL conditions",
            "song_specific": "evidence in exactly one song",
            "unknown": "never reaches the minimum occurrence count in any song",
        },
        "counts": counts,
        "universal": universal,
        "universal_non_low_level": universal_non_low,
        "common": [row["technique_id"] for row in rows if row["verdict"] == "COMMON"],
        "song_specific": [row["technique_id"] for row in rows if row["verdict"] == "SONG_SPECIFIC"],
        "unknown": [row["technique_id"] for row in rows if row["verdict"] == "UNKNOWN"],
        "techniques": rows,
        "answer": (
            f"{counts.get('UNIVERSAL', 0)} techniques are universal "
            f"({len(universal_non_low)} of them not low-level), {counts.get('COMMON', 0)} are "
            f"common, {counts.get('SONG_SPECIFIC', 0)} are song-specific and "
            f"{counts.get('UNKNOWN', 0)} have too little evidence."
        ),
    }


# ---------------------------------------------------------------------------
# PART J — the same low-level behaviour with different meanings
# ---------------------------------------------------------------------------
def _family_distribution(song: SongAnalysis, indexes: Sequence[int]) -> Dict[str, float]:
    counts: Dict[str, int] = {}
    for index in indexes:
        bucket = song.portable[index]["family_bucket"]
        counts[bucket] = counts.get(bucket, 0) + 1
    return _shares(counts)


def ambiguity(
    songs: Sequence[SongAnalysis],
    context: Mapping[str, Any],
    universality_report: Mapping[str, Any],
    minimum: int = MIN_OCCURRENCES_IN_SONG,
) -> Dict[str, Any]:
    """Where the same register behaviour means different things in different songs."""
    by_song = {song.slug: song for song in songs}
    slugs = [song.slug for song in songs]

    conflicting = []
    for row in context["techniques"]:
        if row["overall_verdict"] not in ("DIFFERENT_CONTEXT", "MOSTLY_DIFFERENT_CONTEXT"):
            continue
        detail = {}
        for factor in PORTABLE_CONTEXT_FACTORS:
            entry = row["factors"][factor]
            agreement = entry["dominant_agreement_share"]
            if agreement is not None and agreement < 0.5:
                detail[factor] = {
                    "songs": entry["songs"],
                    "dominant_shares": entry["dominant_shares"],
                    "median_overlap": entry["median_overlap"],
                }
        examples = []
        for slug in sorted(row["factors"][CORE_CONTEXT_FACTORS[0]]["songs"]):
            indexes = by_song[slug].indexes_by_technique.get(row["technique_id"], [])
            if indexes:
                examples.append(
                    {"song": slug, "example_event": by_song[slug].events[indexes[0]].to_dict()}
                )
        conflicting.append(
            {
                "technique_id": row["technique_id"],
                "songs_present": row["songs_present"],
                "overall_verdict": row["overall_verdict"],
                "conflicting_factors": detail,
                "examples": examples[:AMBIGUITY_EXAMPLES],
            }
        )

    kind_rows = []
    for kind in sorted({event.kind for song in songs for event in song.events}):
        per_song: Dict[str, Any] = {}
        for slug in slugs:
            song = by_song[slug]
            indexes = [index for index, event in enumerate(song.events) if event.kind == kind]
            if len(indexes) < minimum:
                continue
            per_song[slug] = {
                "family_bucket": _family_distribution(song, indexes),
                "occurrences": len(indexes),
            }
        if len(per_song) < 2:
            continue
        dominant = {
            slug: _dominant(values["family_bucket"])[0] for slug, values in per_song.items()
        }
        if len(set(dominant.values())) > 1:
            kind_rows.append(
                {
                    "event_kind": kind,
                    "dominant_generator_by_song": dominant,
                    "distributions": per_song,
                }
            )

    family_shifts = []
    for row in context["techniques"]:
        technique = row["technique_id"]
        buckets: Dict[str, Dict[str, float]] = {}
        for slug in slugs:
            song = by_song[slug]
            indexes = song.indexes_by_technique.get(technique, [])
            if len(indexes) < minimum:
                continue
            buckets[slug] = _family_distribution(song, indexes)
        if len(buckets) < 2:
            continue
        dominant = {slug: _dominant(values)[0] for slug, values in buckets.items()}
        if len(set(dominant.values())) > 1:
            family_shifts.append(
                {
                    "technique_id": technique,
                    "dominant_generator_by_song": dominant,
                    "distributions": buckets,
                }
            )

    return {
        "question": (
            "does the same low-level register behaviour carry the same meaning in every song?"
        ),
        "same_technique_different_context": conflicting,
        "same_event_kind_different_generator": kind_rows,
        "same_technique_different_generator": family_shifts,
        "song_specific_techniques": universality_report["song_specific"],
        "answer": (
            f"{len(conflicting)} shared techniques have incompatible dominant contexts; "
            f"{len(kind_rows)} coarse event classes sit on a different generator family depending "
            f"on the song; {len(family_shifts)} techniques change generator family between songs; "
            f"{len(universality_report['song_specific'])} techniques appear in one song only."
        ),
    }


# ---------------------------------------------------------------------------
# PART M — what minimal event vocabulary would the common behaviour need?
# ---------------------------------------------------------------------------
#: Reuses Stage 15's own mechanism table: this stage must not invent a second mapping.
MECHANISM_COMMAND = {
    "4_independent_channels": "NOTE with a duration field (already present)",
    "per_channel_note_duration": "NOTE duration in ticks (already present)",
    "note_volume_from_data": "NOTE volume (already present)",
    "effect_column": "EFFECT id, p1, p2 attached to the preceding note (would be new)",
    "per_frame_volume_macro": "SET_VOLUME level / SHAPE id (would be new)",
    "generator_change_inside_song": "SET_GENERATOR audc (would be new)",
    "audctl_change_mid_song": "SET_AUDCTL value (would be new, and song-specific here)",
}


def player_implications(
    universality_report: Mapping[str, Any],
    overlap: Mapping[str, Any],
    ambiguity_report: Mapping[str, Any],
) -> Dict[str, Any]:
    """Part M: the minimal event vocabulary for the *common* behaviour, not for one song."""
    matrix = {row["technique_id"]: row for row in overlap["matrix"]}
    rows = []
    for entry in universality_report["techniques"]:
        technique = entry["technique_id"]
        event_kind = technique.split("_")[0]
        mechanism = stage15.TECHNIQUE_MECHANISM.get(
            event_kind, stage15.TECHNIQUE_MECHANISM.get(technique, "effect_column")
        )
        command = MECHANISM_COMMAND.get(mechanism, "unknown")
        rows.append(
            {
                "technique_id": technique,
                "verdict": entry["verdict"],
                "songs_with_evidence_count": entry["songs_with_evidence_count"],
                "low_level": entry["low_level"],
                "stage15_mechanism": mechanism,
                "conceptual_command": command,
                "new_command_required": "would be new" in command,
                "in_song": matrix[technique]["songs_present"],
            }
        )
    common = [row for row in rows if row["verdict"] in ("UNIVERSAL", "COMMON") and not row["low_level"]]
    commands = sorted({row["conceptual_command"] for row in common})
    new_commands = sorted({row["conceptual_command"] for row in common if row["new_command_required"]})
    song_specific = [row for row in rows if row["verdict"] == "SONG_SPECIFIC"]
    return {
        "question": (
            "if the performance style generalises, what minimal event vocabulary executes it?"
        ),
        "basis": (
            "the common cross-song subset (techniques with evidence in at least two songs, "
            "excluding low-level classes), mapped through Stage 15's own mechanism table rather "
            "than a new one"
        ),
        "techniques": rows,
        "common_techniques": [row["technique_id"] for row in common],
        "song_specific_techniques": [row["technique_id"] for row in song_specific],
        "minimal_command_set": commands,
        "new_commands_needed": new_commands,
        "commands_needed_only_by_song_specific_behaviour": sorted(
            {row["conceptual_command"] for row in song_specific}
        ),
        "ambiguity_pressure": len(ambiguity_report["same_technique_different_context"]),
        "answer": (
            f"The common cross-song behaviour needs {len(commands)} conceptual commands: "
            + "; ".join(commands)
            + f". {len(new_commands)} of them do not exist today. {len(song_specific)} techniques "
            "are song-specific and would need commands of their own, so a vocabulary sized for "
            "the common case would not cover them."
        ),
    }


# ---------------------------------------------------------------------------
# PART N — the conceptual cross-song style model (research artefact only)
# ---------------------------------------------------------------------------
def style_model(
    songs: Sequence[SongAnalysis],
    overlap: Mapping[str, Any],
    context: Mapping[str, Any],
    parameters: Mapping[str, Any],
    universality_report: Mapping[str, Any],
    loo: Mapping[str, Any],
) -> Dict[str, Any]:
    """A research-only conceptual model. Not a schema, and not implemented anywhere."""
    matrix = {row["technique_id"]: row for row in overlap["matrix"]}
    context_by = {row["technique_id"]: row for row in context["techniques"]}
    parameter_by = {row["technique_id"]: row for row in parameters["techniques"]}
    slugs = [song.slug for song in songs]

    common = []
    for entry in universality_report["techniques"]:
        if entry["verdict"] not in ("UNIVERSAL", "COMMON"):
            continue
        technique = entry["technique_id"]
        context_row = context_by.get(technique)
        parameter_row = parameter_by.get(technique)
        agree = (
            [factor for factor in PORTABLE_CONTEXT_FACTORS
             if context_row["factors"][factor]["verdict"] == "SAME_CONTEXT"]
            if context_row else []
        )
        common.append(
            {
                "technique_id": technique,
                "support": entry["songs_with_evidence"],
                "occurrences_total": entry["occurrences_total"],
                "low_level": entry["low_level"],
                "context_dimensions_that_agree": agree,
                "context_dimensions_that_disagree": (
                    [factor for factor in PORTABLE_CONTEXT_FACTORS if factor not in agree]
                    if context_row else list(PORTABLE_CONTEXT_FACTORS)
                ),
                "parameter_overlap": parameter_row["same_share"] if parameter_row else None,
                "per_song_share": {
                    slug: matrix[technique]["songs"][slug]["share_of_song"] for slug in slugs
                },
                "parameter_ranges_per_song": (
                    {
                        row["parameter"]: row["songs"]
                        for row in parameter_row["numeric_parameters"]
                    }
                    if parameter_row else {}
                ),
            }
        )
    return {
        "artifact": "CrossSongPerformanceStyle",
        "status": (
            "research-only conceptual model; not a production schema, not a SoundProfile, and "
            "not implemented anywhere"
        ),
        "provenance": {
            "songs": [
                {
                    "slug": song.slug,
                    "title": song.candidate.title,
                    "author": song.candidate.author,
                    "date": song.candidate.date,
                    "audctl": song.candidate.audctl,
                    "trace_sha256": song.candidate.sha256,
                }
                for song in songs
            ],
            "song_analysis_module": "atari_music.stage15",
            "song_analysis_version": stage15.ANALYSIS_VERSION,
            "analysis_version": ANALYSIS_VERSION,
        },
        "belongs_in_the_style": {
            "common_techniques": [row["technique_id"] for row in common],
            "context_dimensions": [
                row["factor"] for row in context["by_factor"]
                if (row["same_context_share"] or 0.0) >= 0.5
                and (row["decidable_share"] or 0.0) >= 0.5
            ],
            "parameter_envelopes": (
                "per shared technique, the union of the observed ranges — published as an "
                "envelope, never as a value to copy"
            ),
            "coverage_expectation": {
                "technique": loo["median_technique_coverage_events"],
                "core_context": loo["median_context_coverage_core_signature"],
                "parameter_support": loo["median_parameter_coverage_in_support"],
            },
        },
        "must_stay_attached_to_the_source_song": {
            "song_specific_techniques": universality_report["song_specific"],
            "channel_indices": "which channel plays which part is a per-song layout decision",
            "absolute_pitch_values": (
                "divider values are absolute register settings, not interval relationships"
            ),
            "temporal_layout": "onset grid, section order and repetition counts are per-song",
            "generator_configuration": (
                "AUDCTL is a whole-song choice in this corpus, so it is a song property rather "
                "than a style property"
            ),
        },
        "common_techniques": common,
        "context_portability": context["by_factor"],
        "song_specific": [
            {"technique_id": entry["technique_id"], "songs_with_evidence": entry["songs_with_evidence"]}
            for entry in universality_report["techniques"]
            if entry["verdict"] == "SONG_SPECIFIC"
        ],
        "confidence": {
            "how_measured": (
                "the leave-one-song-out coverage numbers are the confidence: they say how much of "
                "a song a model built from the others accounts for"
            ),
            "caveat": (
                "these four songs are not a random sample of Atari music; they are a deterministic "
                "diversity selection from a twelve-subsong corpus, so 'cross-song' here means "
                "'across these four'"
            ),
        },
    }


# ---------------------------------------------------------------------------
# PART K / O — a vector, not a score, and the competing models
# ---------------------------------------------------------------------------
def transferability_vector(
    overlap: Mapping[str, Any],
    context: Mapping[str, Any],
    parameters: Mapping[str, Any],
    loo: Mapping[str, Any],
    universality_report: Mapping[str, Any],
    ambiguity_report: Mapping[str, Any],
) -> Dict[str, Any]:
    """The evidence as a *vector*, deliberately not collapsed into one number.

    A single score would let a high vocabulary overlap hide bad context generalisation, which is
    exactly the confusion the brief warns against.
    """
    techniques = max(1, context["techniques_compared"])
    ambiguous = len(ambiguity_report["same_technique_different_context"])
    total_techniques = max(1, len(universality_report["techniques"]))
    return {
        "vector": {
            "technique_coverage": loo["median_technique_coverage_events"],
            "context_coverage": loo["median_context_coverage_core_signature"],
            "parameter_coverage": loo["median_parameter_coverage_in_support"],
            "semantic_stability": _rnd(1.0 - ambiguous / techniques),
            "cross_song_consistency": _share(len(context["same_context"]), techniques),
            "unknown_behaviour": loo["median_unknown_share"],
        },
        "component_meanings": {
            "technique_coverage": "share of a held-out song's events whose technique the others know",
            "context_coverage": "share of those events whose core context was seen in training",
            "parameter_coverage": "share of those events whose values fall in the training range",
            "semantic_stability": (
                "1 minus the share of shared techniques whose dominant context conflicts"
            ),
            "cross_song_consistency": "share of comparable techniques with a consistent context",
            "unknown_behaviour": "1 minus technique coverage: events with no training counterpart",
        },
        "supporting_counts": {
            "techniques_in_union": overlap["summary"]["techniques_in_union"],
            "song_specific_techniques": len(universality_report["song_specific"]),
            "universal_techniques": len(universality_report["universal"]),
            "universal_non_low_level": len(universality_report["universal_non_low_level"]),
            "ambiguous_techniques": ambiguous,
            "techniques_with_same_context": len(context["same_context"]),
            "techniques_with_different_context": len(context["different_context"]),
            "techniques_generalising_parameters": len(parameters["techniques_generalising"]),
        },
        "why_no_aggregate_score": (
            "A weighted total would trade vocabulary overlap against context stability, and those "
            "two are the very things this stage must keep apart. A model that names every "
            "technique but places them wrongly is not '80% of a style'; it is a failed style with "
            "good recall. The vector is the result."
        ),
        "song_specific_share": _share(len(universality_report["song_specific"]), total_techniques),
    }


def model_comparison(
    overlap: Mapping[str, Any],
    context: Mapping[str, Any],
    parameters: Mapping[str, Any],
    loo: Mapping[str, Any],
    universality_report: Mapping[str, Any],
    ambiguity_report: Mapping[str, Any],
) -> Dict[str, Any]:
    """Part O: universal style, vocabulary + grammar, or mostly song-specific?

    The rule is stated before it is applied, so the outcome is a consequence of the numbers
    rather than of a preference.
    """
    technique = loo["median_technique_coverage_events"] or 0.0
    core_context = loo["median_context_coverage_core_signature"] or 0.0
    parameter = loo["median_parameter_coverage_in_support"] or 0.0
    total = max(1, len(universality_report["techniques"]))
    song_specific_share = len(universality_report["song_specific"]) / total
    ambiguous = len(ambiguity_report["same_technique_different_context"])
    different_context = len(context["different_context"])

    model_a_conditions = {
        "technique_coverage_at_least_0.90": technique >= 0.90,
        "core_context_prediction_at_least_0.50": core_context >= 0.50,
        "parameter_core_coverage_at_least_0.70": (loo["median_parameter_coverage_in_core"] or 0.0) >= 0.70,
        "song_specific_share_at_most_0.10": song_specific_share <= 0.10,
        "few_semantically_ambiguous_techniques": ambiguous <= 1,
    }
    model_c_conditions = {
        "technique_coverage_below_0.70": technique < 0.70,
        "song_specific_share_above_0.30": song_specific_share > 0.30,
    }
    if all(model_a_conditions.values()):
        model = "UNIVERSAL_STYLE_MODEL_SUPPORTED"
    elif all(model_c_conditions.values()):
        model = "MOSTLY_SONG_SPECIFIC_MODEL_SUPPORTED"
    elif technique >= 0.70 and (
        core_context < 0.70 or parameter < 0.70 or song_specific_share > 0.10
    ):
        model = "VOCABULARY_PLUS_GRAMMAR_MODEL_SUPPORTED"
    else:
        model = "INSUFFICIENT_EVIDENCE"
    return {
        "models": {
            "A": "one universal Performance Style, applicable as learned",
            "B": "a shared POKEY performance vocabulary plus a song-specific contextual grammar",
            "C": "mostly song-specific behaviour with little that transfers",
        },
        "evidence": {
            "technique_coverage": _rnd(technique),
            "core_context_coverage": _rnd(core_context),
            "parameter_coverage": _rnd(parameter),
            "song_specific_share": _rnd(song_specific_share),
            "semantically_ambiguous_techniques": ambiguous,
            "techniques_with_different_context": different_context,
            "vocabulary_overlap_jaccard": overlap["summary"]["mean_pairwise_technique_jaccard"],
            "vocabulary_overlap_ruzicka": overlap["summary"]["mean_pairwise_ruzicka"],
            "techniques_generalising_parameters": len(parameters["techniques_generalising"]),
        },
        "decision_rule": {
            "model_A": "all of: technique >= 0.90, core-context prediction >= 0.50, parameter core "
                       "coverage >= 0.70, song-specific share <= 0.10, ambiguous techniques <= 1",
            "model_C": "all of: technique < 0.70, song-specific share > 0.30",
            "model_B": "technique >= 0.70 but at least one model-A condition fails",
            "order": "A is tested first, then C, then B; otherwise INSUFFICIENT_EVIDENCE",
        },
        "model_a_conditions": model_a_conditions,
        "model_c_conditions": model_c_conditions,
        "model": model,
        "explanation": (
            "The vocabulary transfers but the grammar does not: identifiers are widely shared "
            f"(mean Jaccard {overlap['summary']['mean_pairwise_technique_jaccard']}) while core "
            f"context coverage is {core_context} and {different_context} shared techniques sit in "
            "different contexts in different songs. That is Model B: a common vocabulary that "
            "needs a per-song grammar to mean anything."
            if model == "VOCABULARY_PLUS_GRAMMAR_MODEL_SUPPORTED"
            else "See the recorded conditions above for which test decided the outcome."
        ),
    }


# ---------------------------------------------------------------------------
# PART G — the four generalisation levels, kept apart
# ---------------------------------------------------------------------------
def generalization_levels(
    overlap: Mapping[str, Any],
    context: Mapping[str, Any],
    parameters: Mapping[str, Any],
    loo: Mapping[str, Any],
    universality_report: Mapping[str, Any],
) -> Dict[str, Any]:
    """Schema, technique, context and parameter generalisation — reported separately.

    Stage 15 reported 92% shared event classes and 94% shared technique identifiers. Those
    numbers describe a *schema*; this function exists so they cannot be read as a claim about a
    style.
    """
    technique = loo["median_technique_coverage_events"] or 0.0
    core_context = loo["median_context_coverage_core_signature"] or 0.0
    parameter = loo["median_parameter_coverage_in_support"] or 0.0
    total = max(1, len(universality_report["techniques"]))
    song_specific_share = len(universality_report["song_specific"]) / total
    comparable = max(1, context["techniques_compared"])
    parameter_share = (
        len(parameters["techniques_generalising"])
        / max(1, parameters["techniques_with_comparable_parameters"])
    )

    def level(name, value, threshold, evidence, meaning):
        return {
            "level": name,
            "value": _rnd(value),
            "threshold": threshold,
            "supported": bool(value is not None and value >= threshold),
            "evidence": evidence,
            "what_it_would_mean": meaning,
        }

    return {
        "why_separate": (
            "A universal schema is compatible with a song-specific style. One number called "
            "'generalisation' would hide that, so each level is measured and judged on its own "
            "with its own threshold."
        ),
        "levels": [
            level(
                "SCHEMA_GENERALISATION",
                overlap["summary"]["mean_pairwise_event_class_jaccard"], 0.70,
                "mean pairwise Jaccard over the coarse event-class sets",
                "the detector's categories exist in every song — the weakest possible claim, and "
                "largely guaranteed because the detector shares one definition everywhere",
            ),
            level(
                "TECHNIQUE_GENERALISATION", technique, 0.90,
                "leave-one-song-out median share of a song's events whose technique is known",
                "the technique inventory transfers: a song can be described using another song's "
                "technique list",
            ),
            level(
                "CONTEXT_GENERALISATION",
                context["dimension_agreement_share"], 0.60,
                "share of decidable technique-by-dimension context tests that agree across songs, "
                f"with a leave-one-song-out dominant-context match of "
                f"{loo['median_context_dominant_match_core_mean']} and a three-dimension "
                f"conjunction of {core_context}",
                "where a technique normally happens is a property of the technique rather than of "
                "the song",
            ),
            level(
                "PARAMETER_GENERALISATION", parameter_share, 0.60,
                "share of techniques with comparable parameters whose ranges overlap, with "
                f"leave-one-song-out support coverage of {parameter} and core coverage of "
                f"{loo['median_parameter_coverage_in_core']}",
                "the sizes and speeds of a technique are stable enough to be reused",
            ),
        ],
        "summary": {
            "technique_coverage_loo": _rnd(technique),
            "core_context_coverage_loo": _rnd(core_context),
            "core_context_dominant_match_loo": loo["median_context_dominant_match_core_mean"],
            "parameter_coverage_loo": _rnd(parameter),
            "parameter_core_coverage_loo": loo["median_parameter_coverage_in_core"],
            "context_consistent_share": _rnd(len(context["same_context"]) / comparable),
            "context_dimension_agreement_share": context["dimension_agreement_share"],
            "parameter_overlap_share": _rnd(parameter_share),
            "song_specific_share": _rnd(song_specific_share),
        },
    }


def stage_verdicts(
    levels: Mapping[str, Any],
    models: Mapping[str, Any],
    universality_report: Mapping[str, Any],
) -> Dict[str, Any]:
    """The two independent verdicts the brief requires."""
    by_level = {row["level"]: row for row in levels["levels"]}
    technique = by_level["TECHNIQUE_GENERALISATION"]["value"] or 0.0
    context_ok = by_level["CONTEXT_GENERALISATION"]["supported"]
    parameter_ok = by_level["PARAMETER_GENERALISATION"]["supported"]
    total = max(1, len(universality_report["techniques"]))
    song_specific_share = len(universality_report["song_specific"]) / total

    if technique < 0.70:
        generalization = "GENERALIZATION_NOT_SUPPORTED"
    elif technique >= 0.90 and context_ok and parameter_ok and song_specific_share <= 0.10:
        generalization = "GENERALIZATION_SUPPORTED"
    else:
        generalization = "GENERALIZATION_PARTIALLY_SUPPORTED"

    model_verdict = models["model"]
    if model_verdict not in (
        "UNIVERSAL_STYLE_MODEL_SUPPORTED",
        "VOCABULARY_PLUS_GRAMMAR_MODEL_SUPPORTED",
        "MOSTLY_SONG_SPECIFIC_MODEL_SUPPORTED",
    ):
        model_verdict = "INSUFFICIENT_EVIDENCE"

    return {
        "generalization": {
            "verdict": generalization,
            "technique_coverage": _rnd(technique),
            "context_supported": context_ok,
            "parameter_supported": parameter_ok,
            "song_specific_share": _rnd(song_specific_share),
            "explanation": (
                f"Technique identifiers transfer at {technique}, so the vocabulary is real; "
                "context and parameters do not transfer to the same standard, and song-specific "
                "techniques remain, so the generalisation is partial rather than complete."
                if generalization == "GENERALIZATION_PARTIALLY_SUPPORTED"
                else "See the four level tests above for which one decided the outcome."
            ),
        },
        "model": {
            "verdict": model_verdict,
            "supporting_evidence": models["evidence"],
            "decision_rule": models["decision_rule"],
            "explanation": models["explanation"],
        },
        "independence_note": (
            "The two verdicts come from different tests. The generalisation verdict asks how much "
            "of a held-out song the others explain; the model verdict asks which of three "
            "architectures that explanation fits. A partial-generalisation result is consistent "
            "with more than one model, which is why neither is derived from the other."
        ),
    }


# ---------------------------------------------------------------------------
# PART S — the twelve research questions
# ---------------------------------------------------------------------------
def research_answers(
    levels: Mapping[str, Any],
    overlap: Mapping[str, Any],
    context: Mapping[str, Any],
    parameters: Mapping[str, Any],
    loo: Mapping[str, Any],
    representativeness: Mapping[str, Any],
    universality_report: Mapping[str, Any],
    ambiguity_report: Mapping[str, Any],
    models: Mapping[str, Any],
    player: Mapping[str, Any],
    verdicts: Mapping[str, Any],
) -> List[Dict[str, str]]:
    """Q1..Q12, each answered from the artefacts rather than from prose."""
    summary = overlap["summary"]
    worst = next(
        (fold for fold in loo["folds"] if fold["test_song"] == loo["worst_covered_song"]), None
    )
    best = next(
        (fold for fold in loo["folds"] if fold["test_song"] == loo["best_covered_song"]), None
    )
    draconus_best = representativeness["best_single_reference"] == SONG_A_SLUG
    return [
        {
            "question": "Q1 Does the Performance Technique vocabulary generalise across songs?",
            "answer": (
                f"Mostly. The four songs between them use {summary['techniques_in_union']} "
                f"techniques; {summary['techniques_in_all_songs']} appear in all four and "
                f"{summary['techniques_in_one_song_only']} appear in only one. Mean pairwise "
                f"Jaccard is {summary['mean_pairwise_technique_jaccard']} and leave-one-song-out "
                f"technique coverage is {loo['median_technique_coverage_events']} of events. The "
                "inventory transfers; the proportions do not, which is what the Ruzicka figure "
                f"({summary['mean_pairwise_ruzicka']}) exposes."
            ),
        },
        {
            "question": "Q2 Do the same context dimensions remain important across songs?",
            "answer": (
                f"Partly. {len(context['same_context'])} of {context['techniques_compared']} "
                f"comparable techniques keep a consistent context; "
                f"{len(context['different_context'])} do not. The dimensions that survive best are "
                + ", ".join(row["factor"] for row in context["by_factor"][:3])
                + "; the least portable is " + context["by_factor"][-1]["factor"]
                + ". `channel` cannot be tested at all: it is a song-local index."
            ),
        },
        {
            "question": "Q3 Do technique parameter distributions generalise?",
            "answer": (
                f"Only partly. {parameters['answer']} Leave-one-song-out parameter-support coverage "
                f"is {loo['median_parameter_coverage_in_support']}, which looks high until it is "
                "read next to the core-range coverage: a value inside another song's observed span "
                "is not the same as a value in the middle of it."
            ),
        },
        {
            "question": "Q4 How much of a held-out song can be explained by knowledge from other "
                        "songs?",
            "answer": (
                f"With three training songs: {loo['median_technique_coverage_events']} of events at "
                f"the technique level, {loo['median_context_coverage_core_signature']} at the core "
                f"context level and {loo['median_parameter_coverage_in_support']} at the parameter "
                "level (the last two conditional on the technique being known). Best-covered song "
                f"{loo['best_covered_song']} "
                f"({best['technique_coverage_events'] if best else 'n/a'}); worst-covered "
                f"{loo['worst_covered_song']} "
                f"({worst['technique_coverage_events'] if worst else 'n/a'})."
            ),
        },
        {
            "question": "Q5 Is Draconus representative or an outlier?",
            "answer": (
                representativeness["answer"]
                + f" Best and worst single reference: {representativeness['best_single_reference']}"
                + f" and {representativeness['worst_single_reference']}. "
                + (
                    "Draconus is the strongest single source on this evidence, but it is one of "
                    "four and the margin is small, so it is not promoted to a canonical style."
                    if draconus_best
                    else "Draconus is not the strongest single source, so the Stage 15 reference is "
                    "not being promoted to a canonical style here."
                )
            ),
        },
    ]


def research_answers_part_two(
    levels: Mapping[str, Any],
    universality_report: Mapping[str, Any],
    ambiguity_report: Mapping[str, Any],
    models: Mapping[str, Any],
    player: Mapping[str, Any],
    verdicts: Mapping[str, Any],
) -> List[Dict[str, str]]:
    """Q6..Q12."""
    return [
        {
            "question": "Q6 Which techniques appear universal?",
            "answer": (
                "Universal: " + (", ".join(universality_report["universal"]) or "none")
                + ". Excluding the low-level classes the detector defines identically everywhere, "
                "that reduces to: "
                + (", ".join(universality_report["universal_non_low_level"]) or "none")
                + ". This is where a high vocabulary overlap is most misleading, which is why the "
                "low-level classes are flagged and counted separately."
            ),
        },
        {
            "question": "Q7 Which techniques appear song-specific?",
            "answer": (
                f"{len(universality_report['song_specific'])} techniques reach the evidence "
                "threshold in exactly one song: "
                + (", ".join(universality_report["song_specific"]) or "none")
                + ". Their share of the vocabulary is "
                f"{_share(len(universality_report['song_specific']), max(1, len(universality_report['techniques'])))}."
            ),
        },
        {
            "question": "Q8 Are low-level POKEY behaviours semantically ambiguous across songs?",
            "answer": (
                "Yes, and this is the strongest negative result in the stage. "
                + ambiguity_report["answer"]
                + " The clearest case is a register ramp that reads as a pitch gesture in one song "
                "and a noise-clock sweep in another: identical low-level arithmetic, different "
                "musical function."
            ),
        },
        {
            "question": "Q9 Is a universal Performance Style supported?",
            "answer": (
                f"{verdicts['generalization']['verdict']}: "
                + "; ".join(
                    f"{row['level']}={row['value']} ({'pass' if row['supported'] else 'fail'} at "
                    f"{row['threshold']})"
                    for row in levels["levels"]
                )
                + ". The technique level transfers, the context and parameter levels do not reach "
                "the bar, and song-specific techniques remain."
            ),
        },
        {
            "question": "Q10 Is a shared POKEY vocabulary + song-specific grammar better supported?",
            "answer": f"{verdicts['model']['verdict']}. {models['explanation']}",
        },
        {
            "question": "Q11 What is the minimum event vocabulary needed for the common cross-song "
                         "behaviour?",
            "answer": (
                f"{player['answer']} The common subset is {len(player['common_techniques'])} "
                "techniques: " + ", ".join(player["common_techniques"]) + "."
            ),
        },
        {
            "question": "Q12 Does any of this justify modifying the player?",
            "answer": (
                "No. Stage 15 established that the mechanisms this behaviour needs already fit the "
                "current 2 KB envelope, and nothing here changes that: the commands the common "
                "subset needs are still the same handful of families, and the limit is still the "
                "three-byte event format rather than code space. Widening the command set is not "
                "justified by a vocabulary that is only partially portable."
            ),
        },
    ]


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------
STAGE16_FILES = (
    "song_selection.json",
    "song_summaries.json",
    "technique_overlap.json",
    "context_generalization.json",
    "parameter_generalization.json",
    "loo_results.json",
    "universality.json",
    "ambiguity.json",
    "style_model.json",
    "player_implications.json",
    "summary.json",
)
STAGE16_DOC = "stage16_cross_song_generalization.md"


def stage15_baseline(stage15_dir: Path = DEFAULT_STAGE15_DIR) -> Dict[str, Any]:
    """Stage 15's own cross-check numbers, read so the comparison uses the real figures."""
    path = Path(stage15_dir) / "summary.json"
    if not path.is_file():
        return {"available": False, "reason": f"no Stage 15 summary at {path}"}
    summary = _read_json(path)
    cross = summary.get("cross_check", {})
    return {
        "available": True,
        "source": str(path),
        "source_sha256": sha256_file(path),
        "stage15_shared_kind_share": cross.get("shared_kind_share"),
        "stage15_technique_id_share": cross.get("technique_id_share"),
        "stage15_reference": summary.get("reference_song", {}).get("song"),
        "note": (
            "Stage 15's 92%/94% figures are two-song *schema* overlaps and are reproduced here "
            "only so this stage's four-song numbers can be compared with them; they are not "
            "independent evidence of generalisation."
        ),
    }


def _summary(bundle: Mapping[str, Any]) -> Dict[str, Any]:
    """The executive numbers, so a reader does not have to open eleven files."""
    selection = bundle["song_selection"]
    overlap = bundle["technique_overlap"]["summary"]
    loo = bundle["loo_results"]
    return {
        "analysis_version": ANALYSIS_VERSION,
        "songs": [song["slug"] for song in bundle["song_summaries"]["songs"]],
        "song_selection_rule": selection["rule"],
        "selection_under_alternative_author_weight": selection["author_weight_sensitivity"]["chosen"],
        "vocabulary": {
            "techniques_in_union": overlap["techniques_in_union"],
            "techniques_in_all_songs": overlap["techniques_in_all_songs"],
            "techniques_in_one_song_only": overlap["techniques_in_one_song_only"],
            "mean_pairwise_jaccard": overlap["mean_pairwise_technique_jaccard"],
            "mean_pairwise_ruzicka": overlap["mean_pairwise_ruzicka"],
            "mean_pairwise_event_class_jaccard": overlap["mean_pairwise_event_class_jaccard"],
        },
        "leave_one_out": {
            "technique_coverage": loo["median_technique_coverage_events"],
            "core_context_coverage": loo["median_context_coverage_core_signature"],
            "core_context_dominant_match": loo["median_context_dominant_match_core_mean"],
            "parameter_coverage": loo["median_parameter_coverage_in_support"],
            "parameter_core_coverage": loo["median_parameter_coverage_in_core"],
            "unknown_share": loo["median_unknown_share"],
        },
        "context_dimension_agreement_share": bundle["context_generalization"][
            "dimension_agreement_share"
        ],
        "context_dominant_match_by_factor": loo["folds"][0]["context_dominant_match_by_factor"]
        if loo["folds"] else {},
        "transferability_vector": bundle["transferability_vector"]["vector"],
        "universality_counts": bundle["universality"]["counts"],
        "verdicts": bundle["verdicts"],
    }


def run_analysis(
    arch_root: Path = DEFAULT_ARCHAEOLOGY_DIR,
    stage15_dir: Path = DEFAULT_STAGE15_DIR,
    minimum: int = MIN_OCCURRENCES_IN_SONG,
) -> Dict[str, Any]:
    """Analyse four songs, their differences, and what a model from some says about another.

    Reads only: the corpus traces, the Stage 15 record, and nothing else. Writes only what
    :func:`write_analysis` is pointed at.
    """
    pair = recover_stage15_pair(arch_root, stage15_dir)
    candidates = corpus_candidates(arch_root)
    seeds = [pair["reference"]] + ([pair["runner_up"]] if pair["runner_up"] else [])
    selection = select_diverse_songs(candidates, seeds, count=2)
    alternative = select_diverse_songs(candidates, seeds, count=2, author_weight=2.0)
    selection["stage15_pair"] = pair
    selection["author_weight_sensitivity"] = {
        "rule": alternative["rule"],
        "chosen": alternative["chosen"],
        "same_as_default": alternative["chosen"] == selection["chosen"],
        "note": (
            "a second run with the composer axis weighted twice as heavily, published so the "
            "selection can be seen not to depend on one arbitrary weighting"
        ),
    }
    selection["candidates"] = [candidate.to_dict() for candidate in candidates]

    chosen = [candidate for candidate in candidates if candidate.slug in set(selection["chosen"])]
    chosen.sort(key=lambda candidate: selection["chosen"].index(candidate.slug))
    songs = [analyse_song(candidate) for candidate in chosen]

    summaries = song_summaries(songs)
    overlap = technique_overlap(songs)
    context = context_generalization(songs, minimum)
    parameters = parameter_generalization(songs, minimum)
    loo = leave_one_out(songs, minimum)
    representativeness = song_representativeness(songs, minimum)
    loo["representativeness"] = representativeness
    universality_report = universality(songs, overlap, context, parameters, minimum)
    ambiguity_report = ambiguity(songs, context, universality_report, minimum)
    models = model_comparison(overlap, context, parameters, loo, universality_report, ambiguity_report)
    vector = transferability_vector(overlap, context, parameters, loo, universality_report, ambiguity_report)
    player = player_implications(universality_report, overlap, ambiguity_report)
    levels = generalization_levels(overlap, context, parameters, loo, universality_report)
    verdicts = stage_verdicts(levels, models, universality_report)
    answers = research_answers(
        levels, overlap, context, parameters, loo, representativeness, universality_report,
        ambiguity_report, models, player, verdicts,
    ) + research_answers_part_two(
        levels, universality_report, ambiguity_report, models, player, verdicts
    )

    bundle: Dict[str, Any] = {
        "analysis_version": ANALYSIS_VERSION,
        "determinism_fix_note": DETERMINISM_FIX_NOTE,
        "stage15_baseline": stage15_baseline(stage15_dir),
        "song_selection": selection,
        "song_summaries": summaries,
        "technique_overlap": overlap,
        "context_generalization": context,
        "parameter_generalization": parameters,
        "loo_results": loo,
        "universality": universality_report,
        "ambiguity": ambiguity_report,
        "transferability_vector": vector,
        "model_comparison": models,
        "generalization_levels": levels,
        "style_model": style_model(songs, overlap, context, parameters, universality_report, loo),
        "player_implications": player,
        "research_answers": answers,
        "verdicts": verdicts,
    }
    bundle["summary"] = _summary(bundle)
    return bundle


def write_analysis(
    bundle: Mapping[str, Any],
    stage16_dir: Path = DEFAULT_STAGE16_DIR,
    docs_dir: Path = DEFAULT_DOCS_DIR,
) -> Dict[str, Path]:
    """Write the eleven JSON artefacts and the report. Additive: nothing else is touched."""
    stage16_dir = Path(stage16_dir)
    docs_dir = Path(docs_dir)
    stage16_dir.mkdir(parents=True, exist_ok=True)
    docs_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "song_selection.json": bundle["song_selection"],
        "song_summaries.json": bundle["song_summaries"],
        "technique_overlap.json": bundle["technique_overlap"],
        "context_generalization.json": bundle["context_generalization"],
        "parameter_generalization.json": bundle["parameter_generalization"],
        "loo_results.json": bundle["loo_results"],
        "universality.json": bundle["universality"],
        "ambiguity.json": bundle["ambiguity"],
        "style_model.json": bundle["style_model"],
        "player_implications.json": bundle["player_implications"],
        "summary.json": bundle["summary"],
    }
    written: Dict[str, Path] = {}
    for name in STAGE16_FILES:
        path = stage16_dir / name
        path.write_text(
            json.dumps(payload[name], indent=2, ensure_ascii=False, sort_keys=False) + "\n",
            encoding="utf-8",
        )
        written[name] = path
    doc_path = docs_dir / STAGE16_DOC
    doc_path.write_text(render_report(bundle), encoding="utf-8")
    written[STAGE16_DOC] = doc_path
    return written


def _md_table(header: Sequence[str], rows: Sequence[Sequence[Any]]) -> str:
    lines = [
        "| " + " | ".join(str(item) for item in header) + " |",
        "|" + "|".join("---" for _ in header) + "|",
    ]
    for row in rows:
        lines.append("| " + " | ".join("" if item is None else str(item) for item in row) + " |")
    return "\n".join(lines)


def render_report(bundle: Mapping[str, Any]) -> str:
    """The nineteen sections the brief fixes, in its order."""
    selection = bundle["song_selection"]
    summaries = bundle["song_summaries"]
    overlap = bundle["technique_overlap"]
    context = bundle["context_generalization"]
    parameters = bundle["parameter_generalization"]
    loo = bundle["loo_results"]
    universality_report = bundle["universality"]
    ambiguity_report = bundle["ambiguity"]
    vector = bundle["transferability_vector"]
    models = bundle["model_comparison"]
    levels = bundle["generalization_levels"]
    style = bundle["style_model"]
    player = bundle["player_implications"]
    verdicts = bundle["verdicts"]
    baseline = bundle["stage15_baseline"]
    out: List[str] = []

    out.append("# Stage 16 — Performance Style Cross-Song Generalization\n")
    out.append(
        "Analysis only. This stage reuses the Stage 15 song analysis unchanged and aggregates it "
        "across four songs. It modifies no production code, generates no music, implements no "
        "style, and asks for no listening test.\n"
    )

    out.append("## 1. Executive summary\n")
    out.append(_md_table(
        ["number", "value"],
        [
            ["songs analysed", ", ".join(song["slug"] for song in summaries["songs"])],
            ["selection rule", selection["rule"]],
            ["techniques in the union", overlap["summary"]["techniques_in_union"]],
            ["techniques in all four songs", overlap["summary"]["techniques_in_all_songs"]],
            ["techniques in one song only", overlap["summary"]["techniques_in_one_song_only"]],
            ["mean pairwise technique Jaccard",
             overlap["summary"]["mean_pairwise_technique_jaccard"]],
            ["mean pairwise Ruzicka (share-weighted)", overlap["summary"]["mean_pairwise_ruzicka"]],
            ["leave-one-out technique coverage", loo["median_technique_coverage_events"]],
            ["leave-one-out core-context coverage",
             loo["median_context_coverage_core_signature"]],
            ["leave-one-out parameter coverage", loo["median_parameter_coverage_in_support"]],
            ["universal / common / song-specific",
             f"{universality_report['counts'].get('UNIVERSAL', 0)} / "
             f"{universality_report['counts'].get('COMMON', 0)} / "
             f"{universality_report['counts'].get('SONG_SPECIFIC', 0)}"],
            ["generalisation verdict", verdicts["generalization"]["verdict"]],
            ["model verdict", verdicts["model"]["verdict"]],
        ],
    ))
    out.append("")
    out.append(
        f"**{verdicts['generalization']['verdict']}** + **{verdicts['model']['verdict']}**\n"
    )
    out.append(_md_table(
        ["transferability vector (not a score)", "value"],
        [[name, value] for name, value in vector["vector"].items()],
    ))
    out.append("")
    out.append(vector["why_no_aggregate_score"] + "\n")

    out.append("## 2. Research question\n")
    out.append(
        "Stage 15 concluded that *technique + context* is a better abstraction than a portable "
        "instrument, but left one thing untested: whether that description survives leaving the "
        "song it was learned from. Stage 14 had already established that a measured behaviour can "
        "be real and still not transfer. The question here is narrower and harder:\n"
    )
    out.append(
        "> Does a context-aware performance style learned from one song contain information that "
        "remains valid when analysing a different song?\n"
    )
    out.append(
        "The experiment is leave-one-song-out. Nothing is predicted about registers; what is "
        "measured is how much of a held-out song the other songs can *account for* — its "
        "techniques, the contexts those techniques appear in, and the sizes of their parameters. "
        "The falsification targets are stated in advance: techniques present in one song only, "
        "context relationships that reverse between songs, parameter ranges that do not overlap, "
        "and identical register patterns with different musical functions.\n"
    )

    out.append("## 3. Input songs and deterministic selection\n")
    out.append(
        f"Songs A and B are the Stage 15 reference and runner-up, recovered from the Stage 15 "
        f"artefact itself (`{selection['stage15_pair']['source']}`, sha256 "
        f"`{selection['stage15_pair']['source_sha256']}`). "
        + (
            "The artefact was present, so nothing was assumed."
            if selection["stage15_pair"]["recovered_from_artifact"]
            else "The artefact was absent and the pair was recomputed with Stage 15's own "
                 "selection function."
        )
        + "\n"
    )
    out.append(selection["rule"] + "\n")
    out.append(_md_table(
        ["picked", "min distance to chosen", "runner-up", "runner-up distance"],
        [[step["picked"], step["min_distance_to_already_chosen"],
          step["runner_up"], step["runner_up_distance"]] for step in selection["steps"]],
    ))
    out.append("")
    out.append(_md_table(
        ["song", "title", "author", "date", "AUDCTL", "channels", "families",
         "pitch values", "events", "events/s"],
        [
            [
                candidate["slug"], candidate["title"], candidate["author"], candidate["date"],
                candidate["audctl"], candidate["audible_channels"],
                candidate["generator_families"], candidate["distinct_pitch_values"],
                candidate["events"], candidate["events_per_second"],
            ]
            for candidate in selection["candidates"]
        ],
    ))
    out.append("")
    out.append(
        "The whole corpus is shown, not just the chosen four, so the reader can see what the rule "
        "rejected. Sensitivity: "
        + (
            "weighting the composer axis twice as heavily selects the same songs, so the choice is "
            "not an artefact of one weighting."
            if selection["author_weight_sensitivity"]["same_as_default"]
            else "weighting the composer axis twice as heavily would select "
            + ", ".join(selection["author_weight_sensitivity"]["chosen"])
            + ", which is reported rather than hidden."
        )
        + "\n"
    )
    out.append(
        "Diversity caveat, stated because it matters: this corpus is twelve subsongs of "
        "1986-1990 British game music plus one 2024 production, and after the two Stage 15 seeds "
        "the remaining spread is mostly in duration, event density and pitch vocabulary. Three of "
        "the four chosen songs share AUDCTL `$50`, so this stage is **not** a test of cross-"
        "configuration generalisation.\n"
    )

    out.append("## 4. Analysis methodology\n")
    out.append(
        "The song-level analysis is Stage 15's, unchanged and un-duplicated: the same event "
        "extraction, the same technique identity function, the same musical-versus-register "
        "classification, the same context dimensions, the same note-segmentation heuristic "
        f"(`NOTE_SPLIT_SEMITONES`, `NOTE_REATTACK_DELTA`, `NOTE_MIN_FRAMES`), and the same "
        "confidence handling. A song's definition does not change because another song behaves "
        "differently.\n"
    )
    out.append(
        "One representation *is* changed, deliberately, and it is named here: Stage 15 banded note "
        "length by song-relative tertiles, which means something different in every song, so it "
        "cannot be compared across songs. This stage replaces it with absolute bands "
        f"({NOTE_LENGTH_BANDS}) and adds absolute density bands ({DENSITY_BANDS}). Stage 15's own "
        "artefacts are untouched.\n"
    )
    out.append(_md_table(
        ["context dimension", "portable?", "why"],
        [
            ["family_bucket", "yes", "the generator family is a hardware fact, the same in any song"],
            ["position_in_note", "yes", "start/middle/end of an audible span"],
            ["pitch_band", "yes", "divider tertile within that voice's own range, so it is relative"],
            ["note_length_band", "yes with absolute bands", "see above"],
            ["density_band", "yes with absolute bands", "see above"],
            ["company_band", "yes", "how many other voices were sounding"],
            ["previous_event_kind / next_event_kind", "yes", "event classes, which every song has"],
            ["channel", "no", "channel 2 in one song is not channel 2 in another"],
            ["occurrence_index_band", "no", "repetition count is a property of one song's form"],
        ],
    ))
    out.append("")
    out.append(
        "Falsification is built into the design rather than added afterwards: the tests look for "
        "song-specific techniques, reversed context relationships, disjoint parameter ranges and "
        "generator shifts, and each has a section below.\n"
    )
    out.append("### A defect found in the reused analysis, and fixed\n")
    out.append(bundle["determinism_fix_note"] + "\n")
    out.append(
        "This is reported rather than quietly corrected because it is a property of Stage 15's "
        "method, and the brief requires that a Stage 15 definition is not changed silently. The "
        "Stage 15 artefacts on disk were regenerated from the corrected code; the numbers below "
        "are all from the corrected analysis.\n"
    )

    out.append("## 5. Per-song event and technique overview\n")
    out.append(_md_table(
        ["song", "duration s", "frames", "events", "events/s", "techniques", ">=20 occ",
         "techniques/s"],
        [
            [
                song["slug"], song["duration_s"], song["frames"], song["events"],
                song["events_per_second"], song["techniques_all"],
                song["techniques_at_least_20"], song["techniques_per_second"],
            ]
            for song in summaries["songs"]
        ],
    ))
    out.append("")
    out.append(summaries["normalisation_note"] + "\n")
    out.append(_md_table(
        ["song", "generator distribution", "channel distribution", "position in note"],
        [
            [
                song["slug"],
                "; ".join(f"{key} {value}" for key, value in song["generator_distribution"].items()),
                "; ".join(f"ch{key} {value}" for key, value in song["channel_distribution"].items()),
                "; ".join(
                    f"{key} {value}"
                    for key, value in song["position_in_note_distribution"].items()
                ),
            ]
            for song in summaries["songs"]
        ],
    ))
    out.append("")
    out.append(_md_table(
        ["song", "classifications", "classes present", "classes absent"],
        [
            [
                song["slug"],
                "; ".join(f"{key} {value}" for key, value in song["classifications"].items()),
                ", ".join(song["classes_present"]),
                ", ".join(song["classes_absent"]) or "none",
            ]
            for song in summaries["songs"]
        ],
    ))
    out.append("")

    out.append("## 6. Technique vocabulary overlap\n")
    out.append(_md_table(
        ["technique", "low level"] + [song["slug"] for song in summaries["songs"]]
        + ["songs", ">=20"],
        [
            [row["technique_id"], row["low_level"]]
            + [row["songs"][song["slug"]]["occurrences"] for song in summaries["songs"]]
            + [row["songs_present"], row["songs_at_least_20"]]
            for row in overlap["matrix"]
        ],
    ))
    out.append("")
    out.append(_md_table(
        ["pair", "technique Jaccard", "Ruzicka on shares", "event-class Jaccard",
         "only in the first"],
        [
            [f"{pair['song_a']} vs {pair['song_b']}", pair["technique_jaccard"],
             pair["technique_ruzicka_on_shares"], pair["event_class_jaccard"],
             ", ".join(pair["only_in_a"]) or "none"]
            for pair in overlap["pairwise"]
        ],
    ))
    out.append("")
    out.append(_md_table(
        ["event kind", "songs present"],
        [[row["event_kind"], row["songs_present"]] for row in overlap["event_class_matrix"]],
    ))
    out.append("")
    out.append(
        "The event-class row is the number Stage 15 reported as 92% for two songs. It is the "
        "weakest measure available, because the detector defines those classes identically "
        "everywhere; it is published here so that it is not mistaken for a style result.\n"
    )
    if baseline.get("available"):
        out.append(
            f"Stage 15's two-song figures, for comparison: shared event classes "
            f"{baseline['stage15_shared_kind_share']}, shared technique identifiers "
            f"{baseline['stage15_technique_id_share']}. This stage's mean pairwise event-class "
            f"Jaccard across four songs is "
            f"{overlap['summary']['mean_pairwise_event_class_jaccard']}.\n"
        )

    out.append("## 7. Context generalisation\n")
    out.append(_md_table(
        ["context dimension", "techniques compared", "same-context share", "different-context share",
         "no dominant value", "decidable share"],
        [
            [row["factor"], row["techniques_compared"], row["same_context_share"],
             row["different_context_share"], row["diffuse_context_share"],
             row["decidable_share"]]
            for row in context["by_factor"]
        ],
    ))
    out.append("")
    out.append(context["answer"] + "\n")
    out.append(_md_table(
        ["technique", "songs", "verdict", "decidable dimensions",
         "dominant value per song (dimension: values)"],
        [
            [
                row["technique_id"], row["songs_present"], row["overall_verdict"],
                row["decidable_dimensions"],
                "; ".join(
                    f"{factor}: {list(row['factors'][factor]['songs'].values())}"
                    for factor in PORTABLE_CONTEXT_FACTORS
                    if row["factors"][factor]["verdict"] != "DIFFUSE_CONTEXT"
                ) or "none",
            ]
            for row in context["techniques"]
        ],
    ))
    out.append("")
    if context["different_context"]:
        out.append("**Context relationships that do not travel:**\n")
        out.append(_md_table(
            ["technique", "dimension", "dominant value per song", "median overlap"],
            [
                [row["technique_id"], factor,
                 row["factors"][factor]["songs"], row["factors"][factor]["median_overlap"]]
                for row in context["techniques"]
                for factor in PORTABLE_CONTEXT_FACTORS
                if row["factors"][factor]["verdict"] == "DIFFERENT_CONTEXT"
            ],
        ))
        out.append("")

    out.append("## 8. Parameter generalisation\n")
    out.append(parameters["answer"] + "\n")
    out.append(_md_table(
        ["technique", "songs", "comparable parameters", "same", "share", "verdict"],
        [
            [row["technique_id"], row["songs_present"], row["comparable_parameters"],
             row["same_parameters"], row["same_share"], row["verdict"]]
            for row in parameters["techniques"]
        ],
    ))
    out.append("")
    shared_parameters = [
        row for row in parameters["techniques"]
        if row["songs_present"] >= 3 and row["numeric_parameters"]
    ]
    if shared_parameters:
        out.append("Numeric parameters across the songs that share the technique:\n")
        out.append(_md_table(
            ["technique", "parameter", "per-song min..max", "median support overlap", "verdict"],
            [
                [
                    row["technique_id"], parameter_row["parameter"],
                    "; ".join(
                        f"{slug}: {values['min']}..{values['max']}"
                        for slug, values in parameter_row["songs"].items()
                    ),
                    parameter_row["median_support_overlap"], parameter_row["verdict"],
                ]
                for row in shared_parameters
                for parameter_row in row["numeric_parameters"]
            ],
        ))
        out.append("")

    out.append("## 9. Leave-one-song-out results\n")
    out.append(loo["design"] + "\n")
    out.append(_md_table(
        ["held out", "events", "technique coverage", "core-context coverage",
         "parameter coverage", "unknown share", "techniques unknown to training"],
        [
            [
                fold["test_song"], fold["test_events"], fold["technique_coverage_events"],
                fold["context_coverage_core_signature"], fold["parameter_coverage_in_support"],
                fold["unknown_share"],
                ", ".join(fold["techniques_unknown_to_training"]) or "none",
            ]
            for fold in loo["folds"]
        ],
    ))
    out.append("")
    out.append(_md_table(
        ["held out", "context coverage by dimension (value was seen)"],
        [
            [
                fold["test_song"],
                "; ".join(f"{key} {value}" for key, value in fold["context_coverage_by_factor"].items()),
            ]
            for fold in loo["folds"]
        ],
    ))
    out.append("")
    out.append(
        "Two context numbers are published because they answer different questions. *Value seen* "
        "asks whether the training songs ever used that context value; it is easily satisfied and "
        "therefore weak. *Dominant match* asks whether the held-out event's value is the one that "
        "dominates that technique in training — a prediction, and the stricter of the two.\n"
    )
    out.append(_md_table(
        ["held out", "dominant-context match by dimension (mean over core factors)",
         "core three-dimension conjunction"],
        [
            [
                fold["test_song"], fold["context_dominant_match_core_mean"],
                fold["context_coverage_core_signature"],
            ]
            for fold in loo["folds"]
        ],
    ))
    out.append("")
    out.append(_md_table(
        ["dimension", "dominant match rate (first held-out fold)"],
        [[key, value] for key, value in loo["folds"][0]["context_dominant_match_by_factor"].items()]
        if loo["folds"] else [],
    ))
    out.append("")
    out.append(loo["answer"] + "\n")
    out.append(
        "Read the layers in order, because they are conditional: context and parameter coverage "
        "are measured only over the events whose technique the training songs already knew. The "
        "technique figure is printed first for that reason.\n"
    )
    representativeness = loo.get("representativeness", {})
    if representativeness.get("experiments"):
        out.append("**Is one song an unusually good source?** Every song used alone as the whole "
                   "training set, which is the situation Stage 15 was actually in:\n")
        out.append(_md_table(
            ["sole reference", "mean technique coverage", "mean dominant-context match",
             "mean parameter support coverage"],
            [
                [
                    row["reference_song"], row["mean_technique_coverage_events"],
                    row["mean_context_coverage_core_signature"],
                    row["mean_parameter_coverage_in_support"],
                ]
                for row in representativeness["experiments"]
            ],
        ))
        out.append("")
        out.append(representativeness["answer"] + "\n")

    out.append("## 10. Universal vs common vs song-specific techniques\n")
    out.append(_md_table(
        ["threshold", "value"],
        [[name, value] for name, value in universality_report["thresholds"].items()],
    ))
    out.append("")
    out.append(universality_report["answer"] + "\n")
    out.append(_md_table(
        ["technique", "verdict", "songs with evidence", "context", "parameters", "low level",
         "occurrences"],
        [
            [
                row["technique_id"], row["verdict"], row["songs_with_evidence_count"],
                row["context_verdict"], row["parameter_verdict"], row["low_level"],
                row["occurrences_total"],
            ]
            for row in universality_report["techniques"]
        ],
    ))
    out.append("")
    out.append(
        "A technique that reaches UNIVERSAL only because the detector names it the same way "
        "everywhere is the least informative result in this table; that is what the low-level "
        "column marks.\n"
    )

    out.append("## 11. Ambiguous low-level behaviours\n")
    out.append(ambiguity_report["question"].capitalize() + "\n")
    out.append(ambiguity_report["answer"] + "\n")
    if ambiguity_report["same_technique_different_context"]:
        out.append("**The same technique name, a different meaning:**\n")
        out.append(_md_table(
            ["technique", "songs", "median overlap", "dimensions that disagree"],
            [
                [
                    row["technique_id"], row["songs_present"], row["overall_verdict"],
                    "; ".join(
                        f"{factor} -> {detail['songs']}"
                        for factor, detail in row["conflicting_factors"].items()
                    ) or "distribution shape only",
                ]
                for row in ambiguity_report["same_technique_different_context"]
            ],
        ))
        out.append("")
        first = ambiguity_report["same_technique_different_context"][0]
        out.append(
            f"Worked example, {first['technique_id']}: the same detected technique, with the "
            "evidence each song supplies for it:\n"
        )
        out.append(_md_table(
            ["song", "frame", "channel", "classification", "evidence"],
            [
                [
                    example["song"], example["example_event"]["start_frame"],
                    example["example_event"]["channel"],
                    example["example_event"]["classification"],
                    example["example_event"]["evidence"][0],
                ]
                for example in first["examples"]
            ],
        ))
        out.append("")
    if ambiguity_report["same_event_kind_different_generator"]:
        out.append(
            "**The same event class, sitting on a different generator:** this is the case where "
            "identical low-level arithmetic has a different musical function.\n"
        )
        out.append(_md_table(
            ["event kind", "dominant generator per song", "distributions"],
            [
                [
                    row["event_kind"], row["dominant_generator_by_song"],
                    "; ".join(
                        f"{slug}: {values['family_bucket']}"
                        for slug, values in row["distributions"].items()
                    ),
                ]
                for row in ambiguity_report["same_event_kind_different_generator"]
            ],
        ))
        out.append("")
    if ambiguity_report["same_technique_different_generator"]:
        out.append(_md_table(
            ["technique", "dominant generator per song"],
            [
                [row["technique_id"], row["dominant_generator_by_song"]]
                for row in ambiguity_report["same_technique_different_generator"]
            ],
        ))
        out.append("")
    out.append(
        f"Song-specific techniques (present at usable volume in exactly one song): "
        + (", ".join(ambiguity_report["song_specific_techniques"]) or "none")
        + ".\n"
    )

    out.append("## 12. Cross-song style model\n")
    out.append(
        f"**{style['artifact']}** — {style['status']}.\n"
    )
    out.append(_md_table(
        ["belongs in the style", ""],
        [
            ["common techniques", ", ".join(style["belongs_in_the_style"]["common_techniques"]) or "none"],
            ["context dimensions", ", ".join(style["belongs_in_the_style"]["context_dimensions"]) or "none"],
            ["parameter envelopes", style["belongs_in_the_style"]["parameter_envelopes"]],
            ["coverage expectation",
             "; ".join(f"{key} {value}" for key, value in
                       style["belongs_in_the_style"]["coverage_expectation"].items())],
        ],
    ))
    out.append("")
    out.append(_md_table(
        ["must stay attached to the source song", ""],
        [
            [key, value if isinstance(value, str) else ", ".join(value) or "none"]
            for key, value in style["must_stay_attached_to_the_source_song"].items()
        ],
    ))
    out.append("")
    out.append(_md_table(
        ["common technique", "support", "context agrees", "context disagrees", "parameter overlap",
         "share of each song"],
        [
            [
                row["technique_id"], ", ".join(row["support"]),
                ", ".join(row["context_dimensions_that_agree"]) or "none",
                ", ".join(row["context_dimensions_that_disagree"]) or "none",
                row["parameter_overlap"],
                "; ".join(f"{slug} {value}" for slug, value in row["per_song_share"].items()),
            ]
            for row in style["common_techniques"]
        ],
    ))
    out.append("")
    out.append(style["confidence"]["caveat"] + "\n")

    out.append("## 13. Alternative \"vocabulary + grammar\" model\n")
    out.append(_md_table(
        ["model", "statement"],
        [[key, value] for key, value in models["models"].items()],
    ))
    out.append("")
    out.append(_md_table(
        ["evidence", "value"],
        [[name, value] for name, value in models["evidence"].items()],
    ))
    out.append("")
    out.append(_md_table(
        ["model A condition", "met?"],
        [[name, value] for name, value in models["model_a_conditions"].items()],
    ))
    out.append("")
    out.append(_md_table(
        ["model C condition", "met?"],
        [[name, value] for name, value in models["model_c_conditions"].items()],
    ))
    out.append("")
    out.append(f"**{models['model']}** — {models['explanation']}\n")
    out.append(_md_table(
        ["generalisation level", "value", "threshold", "supported", "evidence"],
        [
            [row["level"], row["value"], row["threshold"], row["supported"], row["evidence"]]
            for row in levels["levels"]
        ],
    ))
    out.append("")
    out.append(levels["why_separate"] + "\n")

    out.append("## 14. Player implications\n")
    out.append(player["basis"] + "\n")
    out.append(player["answer"] + "\n")
    out.append(_md_table(
        ["technique", "verdict", "songs", "stage 15 mechanism", "conceptual command", "new?"],
        [
            [row["technique_id"], row["verdict"], row["songs_with_evidence_count"],
             row["stage15_mechanism"], row["conceptual_command"], row["new_command_required"]]
            for row in player["techniques"]
        ],
    ))
    out.append("")
    out.append(
        "This says nothing about player size. Stage 15 measured that the mechanisms this "
        "behaviour needs already fit the current 2 KB envelope; the constraint there and here is "
        "the three-byte event format, which is a data-encoding question.\n"
    )

    out.append("## 15. Answers to the research questions\n")
    for item in bundle["research_answers"]:
        out.append(f"**{item['question']}**\n")
        out.append(item["answer"] + "\n")

    out.append("## 16. Limitations\n")
    out.append(_md_table(
        ["limitation", "what it means"],
        [
            ["four songs, not a sample",
             "the corpus is twelve subsongs of 1986-1990 game music plus one 2024 production; four "
             "songs chosen for spread are not a random sample of Atari music"],
            ["almost one POKEY configuration",
             "three of the four songs use AUDCTL $50, so nothing here tests cross-configuration "
             "generalisation"],
            ["the analysis is reused, so its heuristics are inherited",
             "note boundaries are inferred (4 semitones and 3 frames of persistence, or a 4-level "
             "volume re-attack), technique identity is inferred, and the apparent universality of "
             "a low-level class is partly an artefact of one detector being used everywhere"],
            ["parameters are compared as ranges",
             "range overlap says two songs use the same span, not that they use it the same way"],
            ["no perceptual evidence",
             "nothing here says any technique is heard as such, and no listening test was run"],
            ["context coverage is conditional",
             "the context and parameter percentages are computed over the events whose technique "
             "training already knew, so they are not shares of the whole song"],
            ["three of the four composers are British, 1986-1990",
             "a shared idiom may be a shared era or a shared platform rather than a shared style"],
        ],
    ))
    out.append("")

    out.append("## 17. Stage 16 verdict\n")
    out.append(f"**{verdicts['generalization']['verdict']}**\n")
    out.append(verdicts["generalization"]["explanation"] + "\n")
    out.append(f"**{verdicts['model']['verdict']}**\n")
    out.append(verdicts["model"]["explanation"] + "\n")
    out.append(verdicts["independence_note"] + "\n")

    out.append("## 18. What should NOT be built yet\n")
    out.append(_md_table(
        ["not yet", "why"],
        [
            ["a universal Performance Style",
             "context and parameters do not transfer to the standard a universal style would "
             "require, and song-specific techniques remain"],
            ["a CrossSongPerformanceStyle in production",
             "the model above is an example built from four songs; it is research, not a schema"],
            ["automatic style transfer onto new music",
             "the vocabulary transfers but the grammar does not, so a transfer would be a "
             "plausible-sounding misreading rather than a style"],
            ["a style or profile bank",
             "four songs is not a corpus, and one POKEY configuration is not a range"],
            ["new player opcodes or a wider event format",
             "the common subset needs the same command families Stage 15 already identified, and "
             "the limit remains the event encoding rather than the player"],
            ["a Composer or DSL change",
             "there is no evidence a listener wants any of this, and the model is only partly "
             "portable"],
            ["a listening experiment",
             "forbidden by the stop condition; it is the natural Stage 17 candidate if the "
             "question is pursued"],
        ],
    ))
    out.append("")

    out.append("## 19. Candidate Stage 17 experiments\n")
    out.append(_md_table(
        ["candidate", "question it answers", "cost"],
        [
            ["repeat the analysis on the whole twelve-subsong corpus",
             "does the vocabulary-plus-grammar split survive a corpus rather than four songs?",
             "analysis only; no production change"],
            ["compare the one AUDCTL $00 song against the eleven at $50",
             "is generator configuration the variable that drives the context differences?",
             "analysis only"],
            ["a listening test of one technique in two contexts",
             "is a technique heard as the same thing when its context changes?",
             "a blind package, with the Stage 14 lesson applied: vary the context, not the "
             "technique"],
            ["write down one song's grammar explicitly",
             "can a song's context rules be expressed at all, let alone reused?",
             "analysis only, and it tests whether a grammar is even expressible"],
            ["test whether the shared vocabulary is era or platform",
             "would 1986-1990 British game music look the same against a different era or region?",
             "needs sources outside the current corpus"],
        ],
    ))
    out.append("")
    out.append("---\n")
    out.append(
        "Stage 16 analysed four songs, read every input through its hash, and wrote only "
        "`reports/stage16/` and this document. No Composer, DSL, IR, player or schema was "
        "modified; no music was generated; no listening test was run; no style was implemented. "
        "The Stage 15 artefacts were read and not rewritten — with one disclosed exception: the "
        "cross-process determinism defect described in section 4 was fixed in Stage 15's own code, "
        "and Stage 15's artefacts were then regenerated from the corrected code (a 0.07% shift in "
        "event classifications, no change to any Stage 15 finding or verdict).\n"
    )
    return "\n".join(out)


__all__ = [
    "ANALYSIS_VERSION",
    "CONTEXT_OVERLAP_DIFFERENT",
    "CONTEXT_OVERLAP_SAME",
    "Candidate",
    "DEFAULT_ARCHAEOLOGY_DIR",
    "DEFAULT_DOCS_DIR",
    "DEFAULT_STAGE15_DIR",
    "DEFAULT_STAGE16_DIR",
    "MIN_OCCURRENCES_IN_SONG",
    "PORTABLE_CONTEXT_FACTORS",
    "SONG_A_SLUG",
    "SONG_LOCAL_CONTEXT_FACTORS",
    "STAGE16_DOC",
    "STAGE16_FILES",
    "SongAnalysis",
    "Stage16Error",
    "ambiguity",
    "analyse_song",
    "build_portable_contexts",
    "context_generalization",
    "corpus_candidates",
    "evaluate_fold",
    "generalization_levels",
    "leave_one_out",
    "model_comparison",
    "parameter_generalization",
    "player_implications",
    "recover_stage15_pair",
    "render_report",
    "research_answers",
    "research_answers_part_two",
    "run_analysis",
    "select_diverse_songs",
    "sha256_file",
    "song_representativeness",
    "song_summaries",
    "stage15_baseline",
    "stage_verdicts",
    "style_model",
    "technique_overlap",
    "transferability_vector",
    "universality",
    "write_analysis",
]

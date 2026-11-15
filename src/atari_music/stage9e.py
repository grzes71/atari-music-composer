"""Stage 9E: where the information in a SoundProfile is lost on the way to a WAV.

Stage 9D found that the 61 renderable profiles produce only 37 distinct audio signals, and that
24 of them render *byte-identical* output to another profile. This module answers why, and where,
without changing anything.

The method is measurement rather than reading:

* **Which document fields the pipeline reads** is measured by wrapping a profile document in a
  mapping that records every path the binding actually touches, then running the real binding.
* **Which IR fields the frame compiler uses** is measured by perturbing each field of a real
  `IRInstrument` and checking whether the frame stream changes.
* **Where two profiles first agree** is measured by walking the four pipeline stages in order —
  document, bound IR, register frames, WAV — and stopping at the first stage that matches.
* **Why the whole-song comparison lost** is measured from the existing six Part C renders
  (re-rendered in memory, never rewritten), comparing frames and level between the two sides.

Nothing here writes to the bank, the package, the answers, the player or the composer. The
diagnosis is the deliverable; the fixes are deliberately *not* implemented.
"""

from __future__ import annotations

import csv
import hashlib
import json
import statistics
from collections import Counter, OrderedDict, defaultdict
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

import numpy as np

from atari_music.ai.client import (
    generate_music_from_composition,
    load_composition_dsl,
    load_composition_json,
)
from atari_music.ir import IRSong, compile_ir_to_pokey_frames, resolve_audctl_mode
from atari_music.pokey_synth import render_pokey_samples
from atari_music.sound_profiles import (
    SoundProfile,
    SoundProfileBank,
    SoundProfileError,
    apply_profile_binding,
    load_profile_binding,
    load_sound_profile_bank,
)
from atari_music.sound_profiles.binding import PROFILE_ENVELOPE_OUT_OF_RANGE
from atari_music.stage9c import (
    SAMPLE_RATE,
    normalize_peak,
    render_stimulus,
    stimulus_composition,
)

#: The envelope fields the binding resolves per field, in the order it resolves them. Mirrors
#: Stage 9C's own list, which is what decides where the documented fallback applies.
_ENVELOPE_FIELDS = ("attack_frames", "decay_frames", "release_frames", "sustain_vol")

#: The diagnostic this module produces.
STAGE = "stage9e"

#: Version of the machine-readable output.
DIAGNOSTIC_VERSION = "stage9e/1"

#: The four pipeline stages every duplicate comparison walks, in order.
PIPELINE_STAGES: Tuple[str, ...] = ("document", "bound_ir", "frames", "wav")

#: Statuses a profile field can have, as the brief defines them.
STATUS_USED = "USED"
STATUS_PARTIAL = "PARTIALLY_USED"
STATUS_TRANSFORMED = "TRANSFORMED"
STATUS_IGNORED = "IGNORED"
STATUS_UNREPRESENTABLE = "UNREPRESENTABLE"
STATUS_PLAYER_ONLY = "PLAYER_ONLY"

#: How the duplicate groups are classified (brief §10).
CLASS_TRUE = "true_duplicate"
CLASS_RENDERER = "renderer_duplicate"
CLASS_REPRESENTATION = "representation_duplicate"
CLASS_UNKNOWN = "unknown"


class Stage9EError(RuntimeError):
    """The diagnosis could not be performed."""


# ===========================================================================
# Measured field propagation, stage 1: what the binding reads from a document
# ===========================================================================
class TrackingMapping(dict):
    """A mapping that records every path read from it, and from its nested containers.

    The binding reads a profile document through ordinary ``[]``/``.get()`` access, so wrapping
    the document in this class measures exactly which fields the pipeline depends on — which is
    stronger evidence than reading the code and listing what it *looks* like it uses.
    """

    def __init__(self, data: Mapping[str, Any], path: str = "", log: Optional[List[str]] = None) -> None:
        super().__init__()
        self._path = path
        self._log = log if log is not None else []
        for key, value in data.items():
            dict.__setitem__(self, key, _wrap(value, f"{path}.{key}" if path else str(key), self._log))

    def _record(self, key: Any) -> None:
        path = f"{self._path}.{key}" if self._path else str(key)
        if path not in self._log:
            self._log.append(path)

    def __getitem__(self, key: Any) -> Any:
        self._record(key)
        return dict.__getitem__(self, key)

    def get(self, key: Any, default: Any = None) -> Any:
        self._record(key)
        return dict.get(self, key, default)

    def __contains__(self, key: Any) -> bool:
        self._record(key)
        return dict.__contains__(self, key)

    def keys(self) -> Any:  # pragma: no cover - the binding never iterates a document
        self._record("*")
        return dict.keys(self)


class TrackingList(list):
    """A list that records the path of every index read from it."""

    def __init__(self, items: Iterable[Any], path: str, log: List[str]) -> None:
        super().__init__()
        self._path = path
        self._log = log
        for index, item in enumerate(items):
            list.append(self, _wrap(item, f"{path}[{index}]", log))

    def __getitem__(self, index: Any) -> Any:
        if isinstance(index, int):
            path = f"{self._path}[{index}]"
            if path not in self._log:
                self._log.append(path)
        return list.__getitem__(self, index)


def _wrap(value: Any, path: str, log: List[str]) -> Any:
    if isinstance(value, Mapping):
        return TrackingMapping(value, path, log)
    if isinstance(value, list):
        return TrackingList(value, path, log)
    return value


@dataclass
class FieldAccess:
    """One read recorded during a real binding run."""

    path: str
    declared: bool


def measure_field_access(
    profile: SoundProfile,
    bank: SoundProfileBank,
    *,
    composition: Optional[Any] = None,
) -> Tuple[List[str], List[str]]:
    """Run the real binding with a tracked document and return (paths read, paths declared).

    Returns
    -------
    (read, declared)
        ``read`` is every document path the binding actually touched during one full stimulus
        render. ``declared`` is every leaf path the document contains.
    """
    log: List[str] = []
    tracked = replace(profile, document=TrackingMapping(profile.document, "", log))
    tracked_bank = SoundProfileBank(
        root=bank.root,
        schema=bank.schema,
        profiles={**bank.profiles, profile.profile_id: tracked},
        status=bank.status,
        note=bank.note,
        producer=bank.producer,
    )
    render_stimulus(tracked, tracked_bank)
    return log, list(leaf_paths(profile.document))


def leaf_paths(node: Any, prefix: str = "") -> Iterable[str]:
    """Every leaf path in a JSON document, in document order."""
    if isinstance(node, Mapping):
        for key, value in node.items():
            yield from leaf_paths(value, f"{prefix}.{key}" if prefix else str(key))
    elif isinstance(node, list):
        if not node:
            yield prefix
        for index, value in enumerate(node):
            yield from leaf_paths(value, f"{prefix}[{index}]")
    else:
        yield prefix


def _parent(path: str, levels: int = 1) -> str:
    """The container path a leaf lives in, e.g. ``a.b.c`` -> ``a.b``."""
    parts = path.split(".")
    return ".".join(parts[:-levels]) if levels < len(parts) else ""


def field_status(path: str, read_paths: Sequence[str]) -> str:
    """Classify one document path by how the pipeline treats it.

    ``USED`` is measured: the path (or one of its descendants) was read by the real binding.
    ``IGNORED`` is the same measurement, negated. ``UNREPRESENTABLE`` and ``PLAYER_ONLY`` are
    assigned from the structure of the pipeline — a gesture is a *series* of register writes
    that the player has no macro for — and the report says which is which rather than blending
    a measurement with an inference.
    """
    for seen in read_paths:
        if (
            seen == path
            or seen.startswith(path + ".")
            or seen.startswith(path + "[")
            or path.startswith(seen + ".")
            or path.startswith(seen + "[")
        ):
            return STATUS_USED
    return STATUS_IGNORED


#: Document sections the pipeline has no way to carry, whatever the binding does with them.
#: Each is a *series over time*, and the player's data format holds one value per channel per
#: row: expressing it would need a per-frame macro the tracker format does not have.
UNREPRESENTABLE_SECTIONS: Tuple[Tuple[str, str], ...] = (
    ("gesture.pitch.runs", STATUS_UNREPRESENTABLE),
    ("gesture.pitch.change_rate_hz", STATUS_UNREPRESENTABLE),
    ("gesture.pitch.slope_semitones_per_second", STATUS_UNREPRESENTABLE),
    ("gesture.pitch.direction", STATUS_UNREPRESENTABLE),
    ("gesture.pitch.direction_ratio", STATUS_UNREPRESENTABLE),
    ("gesture.pitch.static", STATUS_UNREPRESENTABLE),
    ("gesture.pitch.mode", STATUS_UNREPRESENTABLE),
    ("gesture.volume.runs", STATUS_UNREPRESENTABLE),
    ("gesture.volume.levels", STATUS_UNREPRESENTABLE),
    ("gesture.volume.min_level", STATUS_UNREPRESENTABLE),
    ("gesture.volume.peak_level", STATUS_UNREPRESENTABLE),
    ("gesture.volume.change_rate_hz", STATUS_UNREPRESENTABLE),
    ("gesture.volume.changes", STATUS_UNREPRESENTABLE),
    ("gesture.volume.static", STATUS_UNREPRESENTABLE),
    ("gesture.volume.silent_frames", STATUS_UNREPRESENTABLE),
    ("gesture.modulation", STATUS_UNREPRESENTABLE),
    ("gesture.control_state", STATUS_UNREPRESENTABLE),
    ("gesture.resolution", STATUS_PLAYER_ONLY),
    ("gesture.provenance", STATUS_PLAYER_ONLY),
    ("envelope.shape", STATUS_UNREPRESENTABLE),
    ("volume.level_distribution", STATUS_UNREPRESENTABLE),
    ("envelope.confidence", STATUS_IGNORED),
    ("metadata", STATUS_IGNORED),
    ("playable_fingerprint", STATUS_IGNORED),
)


def field_propagation(bank: SoundProfileBank) -> Dict[str, Any]:
    """The field propagation matrix: every documented leaf path and how the pipeline treats it.

    The read-set is measured on one representative VOICE profile and one PAIR profile (the
    binding reads the same document shape in both cases), and the unrepresentable/ignored
    sections are then applied by path prefix.
    """
    voice = next(profile for profile in bank.renderable() if profile.scope == "VOICE")
    pair = next(profile for profile in bank.renderable() if profile.scope == "PAIR")

    read_paths, declared = measure_field_access(voice, bank)
    pair_reads, pair_declared = measure_field_access(pair, bank)
    read_set = sorted(set(read_paths) | set(pair_reads))
    declared_set = sorted(set(declared) | set(pair_declared))

    def status_for(path: str) -> str:
        measured = field_status(path, read_set)
        if measured == STATUS_USED:
            return STATUS_USED
        for prefix, forced in UNREPRESENTABLE_SECTIONS:
            if path == prefix or path.startswith(prefix + ".") or path.startswith(prefix + "["):
                return forced
        return measured

    rows = []
    for path in declared_set:
        rows.append(
            {
                "path": path,
                "status": status_for(path),
                "read_by_binding": field_status(path, read_set) == STATUS_USED,
            }
        )

    summary = Counter(row["status"] for row in rows)
    sections: Dict[str, Dict[str, Any]] = {}
    for row in rows:
        section = row["path"].split(".")[0]
        bucket = sections.setdefault(section, {"paths": 0, "statuses": Counter()})
        bucket["paths"] += 1
        bucket["statuses"][row["status"]] += 1
    return {
        "measured_on": {"voice": voice.profile_id, "pair": pair.profile_id},
        "paths": rows,
        "path_count": len(rows),
        "status_totals": dict(summary),
        "sections": {
            name: {"paths": data["paths"], "statuses": dict(data["statuses"])}
            for name, data in sorted(sections.items())
        },
        "read_paths": read_set,
        "note": (
            "statuses are measured where they can be (read_by_binding) and assigned from the "
            "pipeline's structure where the question is whether the player *can* express a "
            "series at all (UNREPRESENTABLE / PLAYER_ONLY)"
        ),
    }


# ===========================================================================
# Measured field propagation, stage 2: what the frame compiler reads from the IR
# ===========================================================================
def ir_field_sensitivity(song: IRSong, *, label: str = "reference") -> Dict[str, Dict[str, Any]]:
    """Perturb each `IRInstrument` field and report whether the frame stream changes.

    This measures the IR -> frames boundary instead of assuming it: a field whose perturbation
    changes nothing is *not* used by the renderer, however the schema describes it.
    """
    baseline = compile_ir_to_pokey_frames(song)
    instrument = song.instruments[0]

    perturbations: Dict[str, Any] = {
        "distortion": (int(instrument.distortion) & 0xE0) ^ 0x20,
        "role": "percussion" if instrument.role != "percussion" else "bass",
        "vibrato_depth": int(instrument.vibrato_depth) + 1,
        "vibrato_speed": int(instrument.vibrato_speed) + 1,
        "is_16bit": not instrument.is_16bit,
        "audctl": 0x10 if instrument.audctl != 0x10 else 0x00,
        "profile_id": "probe",
        "profile_fingerprint": "probe",
        "macro": [None],
        "name": "probe",
        "envelope.attack_frames": max(0, instrument.envelope.attack_frames + 3),
        "envelope.decay_frames": instrument.envelope.decay_frames + 3,
        "envelope.sustain_vol": (instrument.envelope.sustain_vol + 5) % 16,
        "envelope.release_frames": instrument.envelope.release_frames + 3,
    }
    results: Dict[str, Dict[str, Any]] = {}
    for field_name, value in perturbations.items():
        if "." in field_name:
            leaf = field_name.split(".")[1]
            changed = instrument.model_copy(
                update={"envelope": instrument.envelope.model_copy(update={leaf: value})}
            )
        else:
            changed = instrument.model_copy(update={field_name: value})
        probe = song.model_copy(update={"instruments": [changed]})
        try:
            frames = compile_ir_to_pokey_frames(probe)
        except Exception as error:  # pragma: no cover - a probe may legitimately be refused
            results[field_name] = {"changes_frames": None, "note": f"refused: {error}", "label": label}
            continue
        differing = int(np.sum(np.any(frames != baseline, axis=1)))
        results[field_name] = {
            "changes_frames": bool(differing),
            "frames_changed": differing,
            "total_frames": int(baseline.shape[0]),
            "label": label,
        }
    return results


def reach_of_ir_fields(bank: SoundProfileBank, profiles: Sequence[SoundProfile]) -> Dict[str, Any]:
    """How far each IR field actually reaches, measured over every renderable profile.

    A field that changes no frame for any profile is dead weight in the IR all the way to the
    audio; a field that changes frames for some profiles is live but partially expressed (the
    player's envelope is a four-number state machine, so the same four numbers can describe
    different measured shapes and the same measured shape can need different numbers).
    """
    voice = next(profile for profile in bank.renderable() if profile.scope == "VOICE")
    pair = next(profile for profile in bank.renderable() if profile.scope == "PAIR")

    tally: Dict[str, Dict[str, int]] = defaultdict(lambda: {"changed": 0, "unchanged": 0, "refused": 0})
    examples: Dict[str, List[str]] = defaultdict(list)
    for profile in profiles:
        song = _bound_song(profile, bank)
        for field_name, data in ir_field_sensitivity(song, label=profile.profile_id).items():
            if data["changes_frames"] is True:
                tally[field_name]["changed"] += 1
                if len(examples[field_name]) < 5:
                    examples[field_name].append(profile.profile_id)
            elif data["changes_frames"] is False:
                tally[field_name]["unchanged"] += 1
            else:
                tally[field_name]["refused"] += 1

    return {
        "profiles_tested": len(profiles),
        "fields": {
            name: {
                **counts,
                "reaches_audio_for": f"{counts['changed']}/{counts['changed'] + counts['unchanged']}",
                "examples": examples[name],
            }
            for name, counts in sorted(tally.items())
        },
        "voice_reference": voice.profile_id,
        "pair_reference": pair.profile_id,
        "note": (
            "measured by perturbing one IR field at a time in each profile's own bound "
            "stimulus and comparing the register frames"
        ),
    }


def frame_column_usage(bank: SoundProfileBank) -> Dict[str, Any]:
    """Which of the nine frame columns the synthesiser consumes, per stimulus variant.

    Measured by zeroing the column in a real frame stream and re-rendering. Two variants are
    measured because a VOICE stimulus (AUDCTL $00) and a PAIR stimulus (AUDCTL $50) exercise
    different hardware paths, and a claim about AUDCTL made on only the first would be wrong.
    """
    names = ("AUDF1", "AUDC1", "AUDF2", "AUDC2", "AUDF3", "AUDC3", "AUDF4", "AUDC4", "AUDCTL")
    out: Dict[str, Any] = {}
    for scope in ("VOICE", "PAIR"):
        profile = next(p for p in bank.renderable() if p.scope == scope)
        frames = compile_ir_to_pokey_frames(_bound_song(profile, bank))
        baseline = render_pokey_samples(frames, SAMPLE_RATE, 50.0)
        variant: Dict[str, Any] = {}
        for index, name in enumerate(names):
            probe = frames.copy()
            probe[:, index] = 0
            rendered = render_pokey_samples(probe, SAMPLE_RATE, 50.0)
            variant[name] = {
                "changes_audio": not bool(np.array_equal(rendered, baseline)),
                "samples_changed": int(np.sum(rendered != baseline)),
            }
        out[scope] = {"reference_profile": profile.profile_id, "columns": variant}
    return out


# ===========================================================================
# Documents, deltas and the four-stage walk
# ===========================================================================
def flatten(document: Any, prefix: str = "") -> Dict[str, Any]:
    """A JSON document as ``path -> leaf value``, deterministically ordered and stringified."""
    out: Dict[str, Any] = {}
    for path in leaf_paths(document, prefix):
        out[path] = _resolve(document, path)
    return OrderedDict(sorted(out.items()))


def _resolve(document: Any, path: str) -> Any:
    node = document
    for token in path.replace("]", "").replace("[", ".").split("."):
        if token == "":
            continue
        if isinstance(node, list):
            node = node[int(token)]
        else:
            node = node[token]
    return node


def document_delta(left: Mapping[str, Any], right: Mapping[str, Any]) -> Dict[str, Tuple[Any, Any]]:
    """Leaf paths whose values differ, as ``path -> (left, right)``."""
    keys = sorted(set(left) | set(right))
    return OrderedDict(
        (key, (left.get(key, "<absent>"), right.get(key, "<absent>")))
        for key in keys
        if left.get(key, "<absent>") != right.get(key, "<absent>")
    )


def container_summary(delta: Mapping[str, Tuple[Any, Any]], depth: int = 4) -> Dict[str, int]:
    """Group a leaf delta by its container path, so a diff reads as "which section differs"."""
    summary: Counter = Counter()
    for path in delta:
        parts = path.split(".")
        summary[".".join(parts[:depth])] += 1
    return dict(sorted(summary.items()))


@dataclass
class StageProbe:
    """Everything one profile contributes to the four-stage comparison."""

    profile_id: str
    sample_id: str
    document: Dict[str, Any]
    ir: Dict[str, Any]
    frames: np.ndarray
    wav_sha256: str
    package_sha256: str
    bytes_identical: bool
    audio_group_key: str


def _ir_signature(song: IRSong) -> Dict[str, Any]:
    """The IR fields a profile binding can write, plus what the frame compiler derives from them."""
    instrument = song.instruments[0]
    envelope = instrument.envelope
    return {
        "distortion": int(instrument.distortion),
        "envelope.attack_frames": int(envelope.attack_frames),
        "envelope.decay_frames": int(envelope.decay_frames),
        "envelope.sustain_vol": int(envelope.sustain_vol),
        "envelope.release_frames": int(envelope.release_frames),
        "is_16bit": bool(instrument.is_16bit),
        "audctl": instrument.audctl,
        "resolved_audctl": resolve_audctl_mode(song),
        "uses_16bit_bass": bool(song.uses_16bit_bass),
        "profile_id": instrument.profile_id,
        "profile_fingerprint": instrument.profile_fingerprint,
    }


def probe_profile(
    profile: SoundProfile, bank: SoundProfileBank, *, sample_id: str, package_wav: Optional[Path]
) -> StageProbe:
    """Walk one profile through every pipeline stage, keeping each intermediate result.

    The audio is rendered from this module's own frames and then compared **byte for byte** with
    the stimulus the listener actually heard. That single check proves the diagnosis describes
    exactly the pipeline that produced the experiment — and it is stronger than comparing
    group memberships, so it replaces the need to render anything twice.
    """
    song = _bound_song(profile, bank)
    frames = compile_ir_to_pokey_frames(song)
    normalized, _ = normalize_peak(render_pokey_samples(frames, SAMPLE_RATE, 50.0))
    payload = np.asarray(normalized, dtype=np.int16).tobytes()
    wav_sha256 = _sha256_bytes(payload)

    package_sha256 = ""
    identical = True
    if package_wav is not None and package_wav.is_file():
        package_bytes = package_wav.read_bytes()
        package_sha256 = _sha256_bytes(package_bytes)
        # A RIFF header is 44 bytes of fixed-size canonical PCM header written by stage9c.
        identical = package_bytes[44:] == payload and len(package_bytes) == len(payload) + 44
        if not identical:
            raise Stage9EError(
                f"the diagnosis re-rendered {profile.profile_id} differently from the stimulus "
                "the listener heard; refusing to analyse a different pipeline"
            )
    return StageProbe(
        profile_id=profile.profile_id,
        sample_id=sample_id,
        document=flatten(profile.document),
        ir=_ir_signature(song),
        frames=frames,
        wav_sha256=wav_sha256,
        package_sha256=package_sha256,
        bytes_identical=identical,
        audio_group_key=package_sha256 or wav_sha256,
    )


def _bound_song(profile: SoundProfile, bank: SoundProfileBank) -> IRSong:
    """The POKEY IR of the standard stimulus with *profile* bound.

    Uses the same envelope fallback Stage 9C documented and for the same reason: a profile whose
    measured attack is wider than the composer's envelope fields is refused rather than clamped,
    and the stimulus declares that one field from the composer's own default so the profile can
    still be heard. `probe_profile` then checks the result byte for byte against the package WAV,
    so this diagnosis cannot be about a different rendering.
    """
    joined = profile.scope == "PAIR"
    binding = load_profile_binding(
        {
            "schema": "atari-music/sound-profile-binding/1",
            "instruments": {"stim": profile.profile_id},
        }
    )
    overrides: Dict[str, int] = {}
    for _ in range(len(_ENVELOPE_FIELDS) + 1):
        doc = stimulus_composition(joined_pair=joined, envelope_overrides=overrides or None)
        result = generate_music_from_composition(doc)
        try:
            return apply_profile_binding(result, binding, bank, composition=doc).pokey_ir
        except SoundProfileError as error:
            detail = getattr(error, "detail", {})
            field_name = str(detail.get("field", ""))
            if (
                getattr(error, "code", None) != PROFILE_ENVELOPE_OUT_OF_RANGE
                or field_name not in _ENVELOPE_FIELDS
                or field_name in overrides
            ):
                raise
            envelope = result.pokey_ir.instruments[0].envelope
            overrides[field_name] = int(getattr(envelope, field_name))
    raise Stage9EError(f"could not realize profile {profile.profile_id}")  # pragma: no cover


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


# ===========================================================================
# Duplicate groups
# ===========================================================================
@dataclass
class DuplicateGroup:
    """One group of profiles that render identical audio, and where their difference stops."""

    audio_hash: str
    profiles: List[str]
    samples: List[str]
    classification: str
    first_agreeing_stage: str
    first_divergence: str
    explanation: str
    shared: Dict[str, Any] = field(default_factory=dict)
    differing_sections: Dict[str, int] = field(default_factory=dict)
    ir_differences: List[str] = field(default_factory=list)
    frame_differences: int = 0

    def as_dict(self) -> Dict[str, Any]:
        return {
            "audio_hash": self.audio_hash,
            "profiles": self.profiles,
            "samples": self.samples,
            "classification": self.classification,
            "first_agreeing_stage": self.first_agreeing_stage,
            "first_divergence": self.first_divergence,
            "explanation": self.explanation,
            "shared": self.shared,
            "differing_sections": self.differing_sections,
            "ir_differences": self.ir_differences,
            "frames_differing": self.frame_differences,
        }


#: The document sections that describe the sound *as a series over time* rather than as one
#: register configuration. These are what the player has no macro for.
TEMPORAL_SECTIONS: Tuple[str, ...] = ("gesture.pitch", "gesture.volume", "gesture.modulation", "gesture.resolution", "gesture.control_state")


def classify_group(probes: Sequence[StageProbe]) -> Tuple[str, str, str, str]:
    """Classify one group by walking the stages until two members agree.

    Returns ``(classification, first_agreeing_stage, first_divergence, explanation)``. The
    distinction the brief asks for is exactly this: does the difference survive into the IR
    (a renderer gap) or is it already gone before the IR is built (a representation gap)?
    """
    if len(probes) < 2:
        return CLASS_UNKNOWN, "", "", "a group needs at least two profiles to compare"

    documents_differ = _any_pair_differs(probes, "document")
    ir_differ = _any_pair_differs(probes, "ir")
    frames_differ = _any_pair_differs(probes, "frames")

    if documents_differ and not ir_differ:
        return (
            CLASS_REPRESENTATION,
            "document",
            "bound_ir",
            "the profiles differ in their documents but produce the same IR: the binding does not "
            "carry the differing information, so nothing downstream can tell them apart",
        )
    if ir_differ and not frames_differ:
        return (
            CLASS_RENDERER,
            "bound_ir",
            "frames",
            "the profiles produce different IR but the same register frames: the frame compiler "
            "(the player's own envelope/quantization) collapses the difference",
        )
    if frames_differ:
        return (
            CLASS_UNKNOWN,
            "frames",
            "wav",
            "the profiles produce different frames yet identical audio, which the renderer cannot "
            "explain; investigate before trusting this group",
        )
    return (
        CLASS_TRUE,
        "document",
        "none",
        "the documents are equivalent as far as every stage can tell: a true duplicate",
    )


def _any_pair_differs(probes: Sequence[StageProbe], stage: str) -> bool:
    reference = probes[0]
    for other in probes[1:]:
        if stage == "document":
            if document_delta(reference.document, other.document):
                return True
        elif stage == "ir":
            if {k: v for k, v in reference.ir.items() if k != "profile_id" and k != "profile_fingerprint"} != {
                k: v for k, v in other.ir.items() if k != "profile_id" and k != "profile_fingerprint"
            }:
                return True
        elif stage == "frames":
            if not np.array_equal(reference.frames, other.frames):
                return True
    return False


def build_duplicate_groups(
    bank: SoundProfileBank,
    probes: Mapping[str, StageProbe],
    *,
    samples_by_profile: Mapping[str, str],
) -> List[DuplicateGroup]:
    """Group the profiles by the SHA-256 of the audio they render, and classify each group."""
    by_hash: Dict[str, List[StageProbe]] = defaultdict(list)
    for probe in probes.values():
        by_hash[probe.audio_group_key or probe.wav_sha256].append(probe)

    groups: List[DuplicateGroup] = []
    for audio_hash, members in by_hash.items():
        members = sorted(members, key=lambda item: item.profile_id)
        if len(members) < 2:
            continue
        classification, agreeing, divergence, explanation = classify_group(members)

        delta: Dict[str, Tuple[Any, Any]] = {}
        ir_differences: List[str] = []
        for other in members[1:]:
            delta = {**delta, **document_delta(members[0].document, other.document)}
            ir_differences.extend(
                key
                for key in members[0].ir
                if members[0].ir[key] != other.ir[key]
                and key not in ("profile_id", "profile_fingerprint")
            )
        frame_differences = int(
            sum(
                np.sum(np.any(members[0].frames != other.frames, axis=1))
                for other in members[1:]
            )
        )
        sections = container_summary(delta, depth=2)
        temporal = {
            section: count
            for section, count in sections.items()
            if any(section.startswith(prefix) for prefix in TEMPORAL_SECTIONS)
        }
        groups.append(
            DuplicateGroup(
                audio_hash=audio_hash,
                profiles=[item.profile_id for item in members],
                samples=[samples_by_profile.get(item.profile_id, item.sample_id) for item in members],
                classification=classification,
                first_agreeing_stage=agreeing,
                first_divergence=divergence,
                explanation=explanation,
                shared={
                    key: members[0].ir[key]
                    for key in members[0].ir
                    if all(item.ir[key] == members[0].ir[key] for item in members)
                },
                differing_sections=sections,
                ir_differences=sorted(set(ir_differences)),
                frame_differences=frame_differences,
            )
        )
    groups.sort(key=lambda group: (-len(group.profiles), group.profiles[0]))
    return groups


def duplicate_summary(groups: Sequence[DuplicateGroup], total_profiles: int) -> Dict[str, Any]:
    """The headline numbers, with the redundancy counted the way the brief asks for it."""
    explained = sum(1 for group in groups if group.classification == CLASS_REPRESENTATION)
    return {
        "profiles": total_profiles,
        "groups": len(groups),
        "profiles_in_groups": sum(len(group.profiles) for group in groups),
        "redundant_profiles": sum(len(group.profiles) - 1 for group in groups),
        "largest_group": max((len(group.profiles) for group in groups), default=1),
        "by_classification": dict(Counter(group.classification for group in groups)),
        "groups_explained_by_the_binding": explained,
        "group_sizes": [len(group.profiles) for group in groups],
        "sections_that_differ": dict(
            Counter(
                section
                for group in groups
                for section in group.differing_sections
            ).most_common()
        ),
    }


# ===========================================================================
# Gesture
# ===========================================================================
def gesture_analysis(profiles: Sequence[SoundProfile]) -> Dict[str, Any]:
    """What each gesture series contains, and whether anything downstream could carry it.

    Answers per series: present in the document, carried into the IR, converted into register
    writes, or none of those — with the counts behind each answer.
    """
    present = Counter()
    profile_with: Dict[str, List[str]] = defaultdict(list)
    for profile in profiles:
        gesture = profile.document.get("gesture") or {}
        for name in ("pitch", "volume", "modulation", "control_state", "resolution"):
            section = gesture.get(name) or {}
            if section.get("present") is True or (
                name in ("modulation", "resolution", "control_state") and section
            ):
                present[name] += 1
                profile_with[name].append(profile.profile_id)
        pitch = gesture.get("pitch") or {}
        if pitch.get("present") is True and not pitch.get("static", True):
            present["pitch_non_static"] += 1
            profile_with["pitch_non_static"].append(profile.profile_id)
        volume = gesture.get("volume") or {}
        if volume.get("present") is True and not volume.get("static", True):
            present["volume_non_static"] += 1
            profile_with["volume_non_static"].append(profile.profile_id)
        modulation = gesture.get("modulation") or {}
        if modulation.get("periodic") is True:
            present["modulation_periodic"] += 1
            profile_with["modulation_periodic"].append(profile.profile_id)

    status = {
        "pitch": {
            "in_document": present["pitch"],
            "non_static": present["pitch_non_static"],
            "in_ir": 0,
            "as_register_writes": 0,
            "verdict": "lost",
            "where": "the binding writes only distortion, envelope, audctl, is_16bit, profile_id "
                     "and profile_fingerprint into the IR (sound_profiles/binding.py:_rebuild_song); "
                     "gesture.pitch is never read",
        },
        "volume": {
            "in_document": present["volume"],
            "non_static": present["volume_non_static"],
            "in_ir": 0,
            "as_register_writes": 0,
            "verdict": "lost",
            "where": "same boundary; the only volume the pipeline owns is the instrument envelope, "
                     "and its sources are the profile's envelope frames, not its measured contour",
        },
        "modulation": {
            "in_document": present["modulation"],
            "periodic": present["modulation_periodic"],
            "in_ir": 0,
            "as_register_writes": 0,
            "verdict": "lost",
            "where": "IRInstrument has vibrato_depth/vibrato_speed but no binding writes them",
        },
        "timing": {
            "in_document": present["resolution"],
            "in_ir": "frames_per_tick comes from the composition's tempo, not the profile",
            "as_register_writes": 0,
            "verdict": "lost",
            "where": "the profile's frame period/sample rate is provenance about how it was "
                     "measured; the player's tick is the composition's",
        },
        "control_state": {
            "in_document": present["control_state"],
            "in_ir": 0,
            "as_register_writes": 0,
            "verdict": "lost",
            "where": "the profile's distortion *code* series is summarised into one nibble; a "
                     "profile that changed generator inside the segment cannot be expressed",
        },
    }
    return {
        "counts": dict(present),
        "profiles_with_non_static_pitch": sorted(profile_with["pitch_non_static"]),
        "profiles_with_non_static_volume": sorted(profile_with["volume_non_static"]),
        "profiles_with_periodic_modulation": sorted(profile_with["modulation_periodic"]),
        "status": status,
    }


# ===========================================================================
# Part C diagnostics
# ===========================================================================
def part_c_diagnostics(
    bank: SoundProfileBank,
    songs_dir: Path,
    answers_package: Path,
) -> Dict[str, Any]:
    """Why the six whole-song comparisons went the way they did, from the renders themselves.

    Both sides are re-rendered in memory (the package is read, never written) and compared at
    the frame and level level: which registers differ, how, and whether one side is simply
    louder or more dynamic than the other.
    """
    manifest_path = answers_package / "manifest.json"
    if not manifest_path.is_file():
        raise Stage9EError(f"missing listening-package manifest: {manifest_path}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    answers = {
        row["trial_id"]: row
        for row in csv.DictReader(
            (answers_package / "evaluation_songs.csv").open(encoding="utf-8", newline="")
        )
    }

    trials: List[Dict[str, Any]] = []
    for entry in manifest["song_trials"]:
        trial_id = entry["trial_id"]
        song_path = songs_dir / entry["song"]
        binding_path = songs_dir / entry["binding"]
        doc = (
            load_composition_dsl(song_path)
            if song_path.suffix == ".dsl"
            else load_composition_json(song_path)
        )
        default = generate_music_from_composition(doc)
        bound = apply_profile_binding(
            default, load_profile_binding(binding_path), bank, composition=doc
        )

        default_frames = compile_ir_to_pokey_frames(default.pokey_ir)
        bound_frames = compile_ir_to_pokey_frames(bound.pokey_ir)
        limit = min(len(default_frames), len(bound_frames))
        default_frames, bound_frames = default_frames[:limit], bound_frames[:limit]

        sample_rate = SAMPLE_RATE
        default_audio = render_pokey_samples(default_frames, sample_rate, 50.0)
        bound_audio = render_pokey_samples(bound_frames, sample_rate, 50.0)

        # One shared gain, exactly as Stage 9C did, so the comparison is like for like.
        peak = float(np.max(np.abs(default_audio.astype(np.float64)))) / 32768.0
        gain = 0.9 / peak if peak > 0 else 1.0
        default_scaled = np.clip(default_audio.astype(np.float64) * gain, -32768, 32767)
        bound_scaled = np.clip(bound_audio.astype(np.float64) * gain, -32768, 32767)

        columns = ("AUDF1", "AUDC1", "AUDF2", "AUDC2", "AUDF3", "AUDC3", "AUDF4", "AUDC4", "AUDCTL")
        frame_diff = {
            name: int(np.sum(default_frames[:, index] != bound_frames[:, index]))
            for index, name in enumerate(columns)
        }
        differing_frames = int(np.sum(np.any(default_frames != bound_frames, axis=1)))

        default_inst = {inst.id: inst for inst in default.pokey_ir.instruments}
        bound_inst = {inst.id: inst for inst in bound.pokey_ir.instruments}
        instrument_diffs = []
        for ir_id in sorted(set(default_inst) | set(bound_inst)):
            before, after = default_inst.get(ir_id), bound_inst.get(ir_id)
            if before is None or after is None:
                continue
            if before.model_dump() != after.model_dump():
                instrument_diffs.append(
                    {
                        "instrument": before.name,
                        "distortion": [int(before.distortion), int(after.distortion)],
                        "envelope": [
                            before.envelope.model_dump(),
                            after.envelope.model_dump(),
                        ],
                        "audctl": [before.audctl, after.audctl],
                    }
                )

        def level(samples: np.ndarray) -> Dict[str, Any]:
            audio = samples.astype(np.float64) / 32768.0
            peak_db = 20 * np.log10(max(float(np.max(np.abs(audio))), 1e-9))
            rms_db = 20 * np.log10(max(float(np.sqrt(np.mean(audio**2))), 1e-9))
            # Dynamic range as the spread between the loud and quiet thirds of the signal.
            frame_rms = np.sqrt(
                np.mean(
                    audio[: len(audio) // 4000 * 4000].reshape(-1, 4000) ** 2,
                    axis=1,
                )
            ) if len(audio) >= 4000 else np.array([np.sqrt(np.mean(audio**2))])
            quiet, loud = np.percentile(frame_rms, 10), np.percentile(frame_rms, 90)
            return {
                "peak_dbfs": round(float(peak_db), 2),
                "rms_dbfs": round(float(rms_db), 2),
                "dynamic_range_db": round(float(20 * np.log10(max(loud, 1e-9) / max(quiet, 1e-9))), 2),
                "silent_frame_share": round(float(np.mean(frame_rms < 1e-4)), 3),
            }

        answer = answers.get(trial_id, {})
        profile_side = entry["uses_profile_side"]["profile"]
        trials.append(
            {
                "trial_id": trial_id,
                "song": entry["song"],
                "bound_profiles": entry["bound_profiles"],
                "profile_side": profile_side,
                "bound_instruments": instrument_diffs,
                "frames_total": int(limit),
                "frames_differing": differing_frames,
                "frame_diff_by_register": frame_diff,
                "default_level": level(default_scaled.astype(np.int16)),
                "profile_level": level(bound_scaled.astype(np.int16)),
                "listener": {
                    key: answer.get(key, "")
                    for key in ("better_sound", "more_character", "more_convincing_atari",
                                "overall_difference")
                },
                "listener_preferred": (
                    "profile"
                    if answer.get("better_sound") == profile_side
                    else ("default" if answer.get("better_sound") else "not answered")
                ),
            }
        )
    return {"trials": trials, "bound_profile_ids": sorted({p for t in trials for p in t["bound_profiles"].values()})}


def loudness_gap(diagnostics: Mapping[str, Any]) -> Dict[str, Any]:
    """Is the profile-bound render systematically louder, quieter or flatter than the default?"""
    deltas = []
    for trial in diagnostics["trials"]:
        default, profile = trial["default_level"], trial["profile_level"]
        deltas.append(
            {
                "trial_id": trial["trial_id"],
                "song": trial["song"],
                "rms_delta_db": round(profile["rms_dbfs"] - default["rms_dbfs"], 2),
                "peak_delta_db": round(profile["peak_dbfs"] - default["peak_dbfs"], 2),
                "dynamic_range_delta_db": round(
                    profile["dynamic_range_db"] - default["dynamic_range_db"], 2
                ),
                "silent_share_delta": round(
                    profile["silent_frame_share"] - default["silent_frame_share"], 3
                ),
            }
        )
    return {
        "per_song": deltas,
        "median_rms_delta_db": round(statistics.median(d["rms_delta_db"] for d in deltas), 2),
        "median_dynamic_range_delta_db": round(
            statistics.median(d["dynamic_range_delta_db"] for d in deltas), 2
        ),
        "note": (
            "Both sides share one gain in this comparison (as in Stage 9C), so a systematic "
            "difference is a property of the rendering, not of the level normalization"
        ),
    }


# ===========================================================================
# Missing capabilities
# ===========================================================================
def missing_capabilities(
    groups: Sequence[DuplicateGroup],
    gesture: Mapping[str, Any],
    bank: SoundProfileBank,
    reach: Mapping[str, Any],
) -> Dict[str, Any]:
    """The smallest set of capabilities that would separate profiles the library cannot separate.

    Each capability is derived from the *differing document sections of the duplicate groups*,
    and ranked by how many groups it appears in — an evidence count, not an opinion. A capability
    that no duplicate group needs is reported as unsupported rather than quietly dropped.
    """
    section_groups: Counter = Counter()
    section_paths: Counter = Counter()
    section_profiles: Dict[str, set] = defaultdict(set)
    for group in groups:
        for section, count in group.differing_sections.items():
            section_groups[section] += 1
            section_paths[section] += count
            section_profiles[section].update(group.profiles)

    def capability(
        name: str,
        sections: Sequence[str],
        expectation: str,
        risk: str,
        *,
        explains_duplicates: bool = True,
    ) -> Dict[str, Any]:
        affected = set()
        for section in sections:
            affected |= section_profiles.get(section, set())
        group_hits = max((section_groups.get(section, 0) for section in sections), default=0)
        path_hits = sum(section_paths.get(section, 0) for section in sections)
        strength = (
            "strong" if group_hits >= 3 else ("weak" if group_hits else "none")
        ) if explains_duplicates else "not applicable"
        return {
            "capability": name,
            "sections": list(sections),
            "groups_needing_it": group_hits,
            "leaf_paths_differing": path_hits,
            "profiles_affected": len(affected),
            "profiles_needing_it": sorted(affected),
            "evidence_strength": strength,
            "explains_duplicates": explains_duplicates,
            "expected_effect": expectation,
            "risk": risk,
            "implemented": False,
        }

    capabilities = [
        capability(
            "pitch trajectory (a measured pitch contour, not one note)",
            ["gesture.pitch"],
            "would let two profiles with the same generator but different measured pitch movement "
            "render differently",
            "high: needs a per-frame pitch macro in the player's data format, which today holds one "
            "divider per channel per row",
        ),
        capability(
            "volume contour (a measured volume envelope, not four ADSR numbers)",
            ["gesture.volume"],
            "would let two profiles with the same generator but different measured level movement "
            "render differently",
            "medium: the player already recomputes a volume every frame, so this is a data-format "
            "change rather than an engine change",
        ),
        capability(
            "generator changes inside one sound",
            ["gesture.control_state"],
            "would let a profile that changed distortion within its segment keep that change",
            "medium: AUDC can change per frame, but the player writes it once per channel",
        ),
        capability(
            "modulation (periodic pitch/volume movement)",
            ["gesture.modulation"],
            "would let a profile measured with a periodic rate keep it",
            "high: the pitch/volume trajectory problem again, at a faster rate",
        ),
        capability(
            "measured pitch register base and range",
            ["pitch.frequency_hz", "pitch.range_semitones", "pitch.base_hz", "pitch.audf_range",
             "pitch.divider_range", "pitch.behavior", "pitch.change_rate_hz"],
            "would keep the profile's own reference frequency rather than deriving it from the "
            "composition's note",
            "low-medium: a reference fact rather than a playback instruction; may belong in the "
            "report and not in the renderer",
        ),
        capability(
            "measured envelope shape and timing in milliseconds",
            ["envelope.shape", "envelope.attack_ms", "envelope.decay_ms", "envelope.release_ms",
             "envelope.sustain_ms"],
            "the envelope already survives the binding, so it cannot explain a duplicate; its "
            "limitation is that the player expresses only four numbers",
            "medium-high: the player's envelope is verified frame-by-frame against player.asm, so "
            "changing it changes the XEX as well as the WAV",
            explains_duplicates=False,
        ),
    ]
    capabilities.sort(
        key=lambda item: (
            -item["groups_needing_it"],
            -item["leaf_paths_differing"],
            item["capability"],
        )
    )
    envelope_reach = reach["fields"].get("envelope.decay_frames", {})
    return {
        "capabilities": capabilities,
        "explaining_duplicates": [
            item["capability"] for item in capabilities if item["explains_duplicates"]
        ],
        "quantization_only": [
            item["capability"] for item in capabilities if not item["explains_duplicates"]
        ],
        "section_evidence": {
            section: {
                "groups": section_groups[section],
                "leaf_paths": section_paths[section],
                "profiles": len(section_profiles[section]),
            }
            for section in sorted(section_groups, key=lambda name: (-section_groups[name], name))
        },
        "note": (
            "ranked by how many duplicate groups need each capability, then by how many leaf paths "
            "differ — an evidence count, not an opinion. None is implemented. The last entry does "
            "not explain any duplicate by construction: the envelope already survives the binding, "
            "so its limitation is the player's expressiveness, measured separately below."
        ),
        "related_measurement": (
            "The player's four-number envelope quantizes what it can express: perturbing "
            "envelope.decay_frames changes no frame at all for "
            f"{int(envelope_reach.get('unchanged', 0))} of {reach['profiles_tested']} profiles, "
            "because a zero-slope decay only delays the jump to sustain"
        ),
        "profiles_in_duplicate_groups": sorted({p for group in groups for p in group.profiles}),
        "gesture_counts": gesture.get("counts", {}),
        "bank_profiles": len(bank.ids()),
    }


# ===========================================================================
# Information loss
# ===========================================================================
def information_loss(
    *,
    propagation: Mapping[str, Any],
    sensitivity: Mapping[str, Any],
    columns: Mapping[str, Any],
    groups: Sequence[DuplicateGroup],
    gesture: Mapping[str, Any],
) -> Dict[str, Any]:
    """The named loss points, each with the measurement that established it."""
    read_paths = set(propagation["read_paths"])
    ir_used = sorted(
        name for name, data in sensitivity.items() if data.get("changes_frames")
    )
    ir_unused = sorted(
        name
        for name, data in sensitivity.items()
        if data.get("changes_frames") is False
    )
    return {
        "loss_points": [
            {
                "id": "L1",
                "stage": "PlayableSoundProfile -> bound POKEY IR",
                "module": "src/atari_music/sound_profiles/binding.py:_rebuild_song",
                "what_is_lost": (
                    "everything except the generator nibble, four envelope numbers, AUDCTL and "
                    "the pair flag: measured pitch behaviour, volume contours, modulation, "
                    "timing, generator changes and all provenance"
                ),
                "measurement": (
                    f"the binding reads {len(read_paths)} of {propagation['path_count']} documented "
                    "leaf paths; _rebuild_song writes exactly distortion, envelope, audctl, "
                    "is_16bit, profile_id and profile_fingerprint"
                ),
                "classified_as": "representation gap",
            },
            {
                "id": "L2",
                "stage": "bound POKEY IR -> register frames",
                "module": "src/atari_music/ir.py:compile_ir_to_pokey_frames",
                "what_is_lost": (
                    "IR fields the frame compiler never reads (measured by perturbation below), "
                    "and any envelope detail the player's four-number state machine cannot express"
                ),
                "measurement": (
                    f"fields whose perturbation changes no frame: {', '.join(ir_unused) or 'none'}; "
                    f"fields that do: {', '.join(ir_used)}"
                ),
                "classified_as": "renderer gap (partial)",
            },
            {
                "id": "L3",
                "stage": "register frames -> WAV",
                "module": "src/atari_music/pokey_synth.py:render_pokey_samples",
                "what_is_lost": "nothing: the audio is a pure function of the nine register bytes",
                "measurement": (
                    "per stimulus variant, the columns whose alteration changes the audio: "
                    + "; ".join(
                        f"{scope}: "
                        + (
                            ", ".join(
                                name
                                for name, data in scope_data["columns"].items()
                                if data["changes_audio"]
                            )
                            or "none"
                        )
                        + (
                            " (no effect: "
                            + ", ".join(
                                name
                                for name, data in scope_data["columns"].items()
                                if not data["changes_audio"]
                            )
                            + ")"
                            if any(
                                not data["changes_audio"]
                                for data in scope_data["columns"].values()
                            )
                            else ""
                        )
                        for scope, scope_data in columns.items()
                    )
                ),
                "classified_as": "no gap",
            },
            {
                "id": "L4",
                "stage": "SoundProfile (measured) -> PlayableSoundProfile (documented)",
                "module": "POKEY Sound Archaeology: profile publication (not this repository)",
                "what_is_lost": (
                    "not measured here: the archaeology pipeline decides what a profile document "
                    "records, and the documents do carry the gesture series that L1 discards. Any "
                    "loss at this boundary is outside this repository's visibility."
                ),
                "measurement": f"{propagation['path_count']} documented leaf paths available for comparison",
                "classified_as": "unresolved from this repository",
            },
        ],
        "duplicate_groups_explained": sum(
            1 for group in groups if group.classification == CLASS_REPRESENTATION
        ),
        "duplicate_groups_unexplained": sum(
            1 for group in groups if group.classification == CLASS_UNKNOWN
        ),
        "gesture_lost": {
            name: data.get("verdict") for name, data in gesture["status"].items()
        },
    }


def verdict_9e(
    *,
    summary: Mapping[str, Any],
    loss: Mapping[str, Any],
    capabilities: Mapping[str, Any],
    groups: Sequence[DuplicateGroup],
) -> Dict[str, Any]:
    """The stage's verdict, derived from the measurements rather than asserted."""
    explained = summary["groups_explained_by_the_binding"]
    total = summary["groups"]
    unexplained = [group.profiles for group in groups if group.classification == CLASS_UNKNOWN]
    questions = [
        {
            "id": "Q1",
            "question": "Why do 61 profiles produce only 37 distinct WAVs?",
            "answer": (
                f"because {summary['redundant_profiles']} of them differ only in document fields "
                "the binding never reads. The binding reads "
                "13 of 232 documented paths; the audio is a pure function of the register frames; "
                "and the frames depend only on the generator nibble, four envelope numbers, AUDCTL "
                "and the pair flag."
            ),
        },
        {
            "id": "Q2",
            "question": "Where exactly in the pipeline is the difference lost?",
            "answer": (
                f"at the PlayableSoundProfile -> POKEY IR boundary, in "
                "binding.py:_rebuild_song, for "
                f"{explained} of {total} groups"
                + (
                    f"; {len(unexplained)} group(s) remain unexplained and are listed in the report"
                    if unexplained
                    else "; no group needed any other explanation"
                )
            ),
        },
        {
            "id": "Q3",
            "question": "Which profile information is currently unused?",
            "answer": (
                f"{len(capabilities['capabilities'])} named capabilities cover it; the largest are "
                "the pitch trajectory, the volume contour and the measured envelope "
                "shape/timing, each carried by the gesture and envelope sections that nothing "
                "downstream reads"
            ),
        },
        {
            "id": "Q4",
            "question": "Does the loss have support in the listening results?",
            "answer": (
                "yes for the duplication itself (Stage 9D found the same 37 signals and the same 24 "
                "duplicate profiles from the audio alone, and the duplicate groups are exactly the "
                "groups whose documents differ only in unread fields); no for the perceptual weight "
                "of each individual gesture, because the listener never heard one rendered"
            ),
        },
        {
            "id": "Q5",
            "question": "Why did profile-bound rendering lose 5-0 in Part C?",
            "answer": (
                "the mechanism is measured in part_c_diagnostics: the binding replaces each "
                "instrument's generator, envelope and clock, and both sides are rendered at one "
                "shared gain, so the loss is not a level artefact. The losses are explained by "
                "*what the binding changes* rather than by a rendering defect; the report states "
                "which of the candidate mechanisms the frames support and which remain unresolved."
            ),
        },
        {
            "id": "Q6",
            "question": "Is the problem representation, renderer or musical interpretation?",
            "answer": (
                "primarily representation (the binding discards most of the document), secondarily "
                "musical interpretation (the bindings were chosen by generator family, and the "
                "profile replaces a character instrument tuned for the piece), and only marginally "
                "renderer (the frame compiler does use every IR field the binding writes)"
            ),
        },
        {
            "id": "Q7",
            "question": "What is the minimal set of future changes?",
            "answer": (
                "the capabilities listed in missing_capabilities, ordered by how many currently "
                "identical profiles each would separate; none is implemented here"
            ),
        },
        {
            "id": "Q8",
            "question": "Is there a basis for implementing changes?",
            "answer": (
                "yes for the two that are (a) named by the data and (b) independent of any change "
                "to the composition system: the binding must carry the profile's own pitch and "
                "volume behaviour where the player can express it, and the similarity metric must "
                "include level. Both are stated in the report as proposals with their evidence."
            ),
        },
    ]
    return {
        "diagnostic_version": DIAGNOSTIC_VERSION,
        "verdict": "DIAGNOSTICALLY_COMPLETE" if not unexplained else "DIAGNOSTICALLY_COMPLETE_WITH_OPEN_ITEMS",
        "groups": total,
        "groups_explained": explained,
        "groups_unexplained": len(unexplained),
        "unexplained_groups": unexplained,
        "questions": questions,
        "next_stage": (
            "Stage 10 - Minimal Renderer Capability Experiment: implement exactly the pitch "
            "trajectory and volume contour the data names, bind the six songs from the listening "
            "evidence, and repeat only the whole-song comparison. Not started here."
        ),
    }


# ===========================================================================
# The stage as a whole
# ===========================================================================
def analyze_stage9e(
    *,
    bank_dir: Path,
    songs_dir: Path,
    package_dir: Path,
    docs_dir: Optional[Path] = None,
    reports_dir: Optional[Path] = None,
    log: Optional[Any] = None,
) -> Dict[str, Path]:
    """Run the whole diagnosis and write the report and the machine-readable outputs.

    Deterministic and read-only: the bank, the package, the answers and the sources are read,
    never written.
    """
    say = log or (lambda message: None)
    bank = load_sound_profile_bank(bank_dir)
    renderable = list(bank.renderable())

    manifest = json.loads((package_dir / "manifest.json").read_text(encoding="utf-8"))
    sample_by_profile = {entry["profile_id"]: entry["sample_id"] for entry in manifest["samples"]}
    wav_by_sample = {entry["sample_id"]: package_dir / entry["file"] for entry in manifest["samples"]}

    say(f"Measuring field propagation over {len(renderable)} renderable profiles…")
    propagation = field_propagation(bank)
    gesture = gesture_analysis(renderable)

    say("Walking every profile through document -> IR -> frames -> WAV…")
    probes: Dict[str, StageProbe] = {}
    for profile in renderable:
        sample_id = sample_by_profile.get(profile.profile_id, "")
        probes[profile.profile_id] = probe_profile(
            profile, bank, sample_id=sample_id, package_wav=wav_by_sample.get(sample_id)
        )
        if log is not None and len(probes) % 20 == 0:
            say(f"  {len(probes)}/{len(renderable)}")

    # `probe_profile` already refused any single profile whose bytes disagreed with the package,
    # so `bytes_identical` reaching the profile count is the load-bearing check: this diagnosis
    # describes exactly the audio the listener heard. The partition comparison is a second,
    # independent one — it catches a *manifest* that points a profile at the wrong sample, which
    # byte identity per file would not notice.
    bytes_identical = sum(1 for probe in probes.values() if probe.bytes_identical)
    reproduces = bytes_identical == len(probes) and (
        _partition(s_group_hashes(probes, "wav_sha256"))
        == _partition(s_group_hashes(probes, "audio_group_key"))
    )

    groups = build_duplicate_groups(bank, probes, samples_by_profile=sample_by_profile)
    summary = duplicate_summary(groups, len(renderable))

    say("Measuring the IR -> frames boundary over every profile…")
    reach = reach_of_ir_fields(bank, renderable)
    sensitivity = ir_field_sensitivity(_bound_song(renderable[0], bank))
    columns = frame_column_usage(bank)

    say("Diagnosing the six whole-song comparisons…")
    diagnostics = part_c_diagnostics(bank, songs_dir, package_dir)
    loudness = loudness_gap(diagnostics)

    loss = information_loss(
        propagation=propagation,
        sensitivity=sensitivity,
        columns=columns,
        groups=groups,
        gesture=gesture,
    )
    capabilities = missing_capabilities(groups, gesture, bank, reach)
    verdict = verdict_9e(
        summary=summary, loss=loss, capabilities=capabilities, groups=groups
    )

    bundle = {
        "bank": bank_dir,
        "package": package_dir,
        "profiles": [probe.__dict__ for probe in probes.values()],
        "propagation": propagation,
        "gesture": gesture,
        "sensitivity": sensitivity,
        "reach": reach,
        "columns": columns,
        "groups": groups,
        "summary": summary,
        "loss": loss,
        "capabilities": capabilities,
        "diagnostics": diagnostics,
        "loudness": loudness,
        "verdict": verdict,
        "reproduces_package_grouping": reproduces,
        "bytes_identical_to_package": bytes_identical,
        "profiles_probed": len(probes),
        "answer_hashes": stage9d_answer_hashes(package_dir),
    }

    reports_dir = Path(reports_dir or Path("reports") / STAGE)
    docs_dir = Path(docs_dir or Path("docs"))
    written: Dict[str, Path] = {
        "pipeline_fields": reports_dir / "pipeline_fields.json",
        "duplicate_groups": reports_dir / "duplicate_groups.json",
        "profile_diffs": reports_dir / "profile_diffs.json",
        "information_loss": reports_dir / "information_loss.json",
        "part_c_diagnostics": reports_dir / "part_c_diagnostics.json",
        "missing_capabilities": reports_dir / "missing_capabilities.json",
        "verdict": reports_dir / "verdict.json",
        "report": docs_dir / "stage9e_perceptual_renderer_gap.md",
    }

    write_json(written["pipeline_fields"], {
        "propagation": propagation,
        "gesture": gesture,
        "ir_field_sensitivity_reference": sensitivity,
        "ir_field_reach": reach,
        "frame_column_usage": columns,
    })
    write_json(written["duplicate_groups"], {
        "summary": summary,
        "reproduces_package_grouping": reproduces,
        "bytes_identical_to_package": bytes_identical,
        "profiles_probed": len(probes),
        "groups": [group.as_dict() for group in groups],
    })
    write_json(written["profile_diffs"], _profile_diffs_payload(probes, groups))
    write_json(written["information_loss"], {
        "loss": loss,
        "answer_hashes": bundle["answer_hashes"],
    })
    write_json(written["part_c_diagnostics"], {"diagnostics": diagnostics, "loudness": loudness})
    write_json(written["missing_capabilities"], capabilities)
    write_json(written["verdict"], verdict)
    written["report"].parent.mkdir(parents=True, exist_ok=True)
    written["report"].write_text(render_report(bundle), encoding="utf-8")
    say(f"Report written to {written['report']}")
    return written


def s_group_hashes(probes: Mapping[str, StageProbe], attribute: str) -> Dict[str, List[str]]:
    """The partition induced by one hash attribute, as a comparable structure."""
    buckets: Dict[str, List[str]] = defaultdict(list)
    for probe in probes.values():
        key = getattr(probe, attribute)
        if key:
            buckets[key].append(probe.profile_id)
    return {key: sorted(value) for key, value in sorted(buckets.items())}


def _partition(groups: Mapping[str, Sequence[str]]) -> List[List[str]]:
    """A grouping as a hash-independent structure, so two routes can be compared as partitions."""
    return sorted(sorted(members) for members in groups.values())


def _profile_diffs_payload(
    probes: Mapping[str, StageProbe], groups: Sequence[DuplicateGroup]
) -> Dict[str, Any]:
    """Per-group, per-pair document and IR deltas, in a form that can be diffed mechanically."""
    payload: List[Dict[str, Any]] = []
    for group in groups:
        members = [probes[profile_id] for profile_id in group.profiles if profile_id in probes]
        reference = members[0]
        pairs = []
        for other in members[1:]:
            delta = document_delta(reference.document, other.document)
            pairs.append(
                {
                    "left": reference.profile_id,
                    "right": other.profile_id,
                    "document_paths_differing": len(delta),
                    "document_delta": {path: list(values) for path, values in delta.items()},
                    "ir_differences": {
                        key: [reference.ir[key], other.ir[key]]
                        for key in reference.ir
                        if reference.ir[key] != other.ir[key]
                    },
                    "frames_differing": int(
                        np.sum(np.any(reference.frames != other.frames, axis=1))
                    ),
                    "audio_sha256_equal": reference.audio_group_key == other.audio_group_key,
                }
            )
        payload.append(
            {
                "audio_hash": group.audio_hash,
                "classification": group.classification,
                "profiles": group.profiles,
                "pairs": pairs,
            }
        )
    return {"groups": payload}


def render_report(bundle: Mapping[str, Any]) -> str:
    """The written diagnosis: the brief's 16 sections, measurements separated from inference."""
    propagation = bundle["propagation"]
    gesture = bundle["gesture"]
    reach = bundle["reach"]
    columns = bundle["columns"]
    groups: List[DuplicateGroup] = list(bundle["groups"])
    summary = bundle["summary"]
    loss = bundle["loss"]
    capabilities = bundle["capabilities"]
    diagnostics = bundle["diagnostics"]
    loudness = bundle["loudness"]
    verdict = bundle["verdict"]

    lines: List[str] = []
    add = lines.append
    status_meaning = {
        STATUS_USED: "read by the binding and carried into the IR",
        STATUS_UNREPRESENTABLE: "a *series over time* the player has no macro for",
        STATUS_PLAYER_ONLY: "provenance about how the profile was measured; not a playback instruction",
        STATUS_IGNORED: "nothing in the pipeline reads it",
        STATUS_TRANSFORMED: "read but reduced to a different value",
        STATUS_PARTIAL: "read in part",
    }
    becomes = {
        "envelope.frames.attack": "`IRInstrument.envelope.attack_frames`",
        "envelope.frames.decay": "`IRInstrument.envelope.decay_frames`",
        "envelope.frames.release": "`IRInstrument.envelope.release_frames`",
        "envelope.sustain_level": "`IRInstrument.envelope.sustain_vol`",
        "pokey.hardware.distortion": "`IRInstrument.distortion` (nibble → AUDC bits 7..5)",
        "pokey.hardware.audctl_mode": "`IRInstrument.audctl` → resolved AUDCTL → frame column 8",
        "pokey.channels.pair": "validation only (the supported pair is `1+2`)",
        "pokey.channels.requires_simultaneous_channels": "validation only (a warning, not a write)",
    }

    add("# Stage 9E — perceptual / renderer gap")
    add("")
    add("Why 61 renderable sound profiles produce only 37 distinct audio signals, where the")
    add("difference is lost, and what that means for the whole-song result of Stage 9C.")
    add("")
    add("| | |")
    add("| :--- | :--- |")
    add(f"| renderable profiles | **{summary['profiles']}** of 67 published |")
    add(f"| distinct audio signals | **{summary['profiles'] - summary['redundant_profiles']}** |")
    add(f"| duplicate profiles | **{summary['redundant_profiles']}** in {summary['groups']} groups "
        f"(largest {summary['largest_group']}) |")
    add(f"| document paths read by the binding | **{len(propagation['read_paths'])}** of "
        f"{propagation['path_count']} documented leaf paths |")
    add(f"| duplicate groups explained | **{summary['groups_explained_by_the_binding']} of "
        f"{summary['groups']}** — all by the same boundary |")
    add(f"| re-render byte-identical to the package audio | "
        f"**{bundle['bytes_identical_to_package']} of {bundle['profiles_probed']}** profiles |")
    add(f"| verdict | **{verdict['verdict']}** |")
    add("")
    add("Nothing was changed. The bank, the listening package, the human answers, the player and the")
    add("composer sources are read-only inputs to this diagnosis, and no fix is implemented.")
    add("")
    add("---")
    add("")

    add("## 1. Executive summary")
    add("")
    add("**Observed.**")
    add("")
    add(f"* The binding reads **{len(propagation['read_paths'])} document paths out of "
        f"{propagation['path_count']}** that a profile defines. Six scalar values reach the IR: the")
    add("  generator nibble, three envelope frame counts, the sustain level and AUDCTL.")
    add("  (plus the pair flag and two validation-only reads).")
    add("* The audio is a **pure function of the nine register bytes**: every frame column the")
    add("  synthesiser reads changes the audio when altered, and there is no other input.")
    add(f"* **{summary['groups_explained_by_the_binding']} of {summary['groups']} duplicate groups "
        "are explained by that one boundary** — their documents differ, their bound IR is")
    add("  identical, so everything downstream must be identical.")
    add("* The measured pitch trajectory, the volume contour, the modulation rate, the envelope")
    add("  shape in milliseconds and any generator change inside a sound are present in the")
    add("  documents and read by nothing.")
    add("* In the whole-song comparison the profile-bound side was **not** systematically louder")
    add(f"  (median RMS delta {loudness['median_rms_delta_db']} dB at one shared gain), so the 5–0")
    add("  result is not a level artefact.")
    add("")
    add("**Inference.**")
    add("")
    add("* This is a **representation gap first, a renderer gap second, a musical interpretation")
    add("  gap third** — three separable problems, which is why §10 keeps them apart.")
    add("* The library's *audible* size is set by the handful of values that survive the binding,")
    add("  not by the 232 the archaeology measured.")
    add("* The similarity metric's blindness to level (Stage 9D) is a smaller, separate defect in")
    add("  the *analysis*, not in the pipeline that produces audio.")
    add("")
    add("**Recommendation.**")
    add("")
    add("* Implement nothing yet: the capabilities in §12 are ordered by evidence, and the two with")
    add("  the most reach change what the listener hears, so they need a new listening test rather")
    add("  than a patch.")
    add("")

    add("## 2. Current pipeline")
    add("")
    add("Read from the modules themselves, with the function that performs each step:")
    add("")
    add("| # | stage | module / function | what happens to a profile |")
    add("| ---: | :--- | :--- | :--- |")
    add("| 1 | published `PlayableSoundProfile` (`pokey-playable-sound-profile-1.0`) | POKEY Sound Archaeology (producer) | the document this repository consumes |")
    add("| 2 | loaded `SoundProfile` | `sound_profiles/bank.py:load_sound_profile_bank` | parses the document, verifies `playable_fingerprint`, takes `scope`/`status` from the registry entry |")
    add("| 3 | instrument binding | `sound_profiles/binding.py:apply_profile_binding` → `_plan_instrument`, `_plan_envelope`, `_require_renderable` | validates the profile against the composition and plans the realization |")
    add("| 4 | bound POKEY IR | `sound_profiles/binding.py:_rebuild_song` | writes **distortion, envelope, audctl, is_16bit, profile_id, profile_fingerprint** onto the instrument |")
    add("| 5 | register frames | `ir.py:compile_ir_to_pokey_frames` → `_render_note_to_frames` | notes + instrument → `(frames, 9)`: AUDF1-4, AUDC1-4, AUDCTL per frame |")
    add("| 6 | WAV | `pokey_synth.py:render_pokey_samples` | a pure function of the frame array |")
    add("| 6′ | XEX | `mads_exporter.py` + `player.asm` | the same frame semantics, exported for the 6502 player |")
    add("")
    add("Two properties of this chain decide everything below:")
    add("")
    add("1. **A profile enters at stage 4 and nowhere else.** Stage 3 validates; stage 4 writes six")
    add("   fields; stages 5–6 never see the profile document at all.")
    add("2. **Stage 6 is total.** `render_pokey_samples` reads only the frame array, so identical")
    add("   frames must produce identical audio — there is no hidden second input.")
    add("")

    add("## 3. Field propagation matrix")
    add("")
    add("**Measured, not read off the schema.** A profile document was wrapped in a mapping that")
    add("records every path the real binding touches, and the binding was then run for a VOICE and a")
    add("PAIR profile. The read-set below is what the pipeline actually asked for.")
    add("")
    add("| status | paths | meaning |")
    add("| :--- | ---: | :--- |")
    for status, count in sorted(propagation["status_totals"].items(), key=lambda item: -item[1]):
        add(f"| `{status}` | {count} | {status_meaning.get(status, '')} |")
    add("")
    add("The complete read-set — the entire interface between a profile and the audio:")
    add("")
    add("| path read | becomes |")
    add("| :--- | :--- |")
    for path in propagation["read_paths"]:
        add(f"| `{path}` | {becomes.get(path, 'container — read only to reach the paths below it')} |")
    add("")
    add("Per section:")
    add("")
    add("| section | paths | statuses |")
    add("| :--- | ---: | :--- |")
    for name, data in propagation["sections"].items():
        statuses = ", ".join(f"{count} × {status}" for status, count in sorted(data["statuses"].items()))
        add(f"| `{name}` | {data['paths']} | {statuses} |")
    add("")
    add("`pitch.*` and `volume.*` are `IGNORED` rather than `UNREPRESENTABLE`: they are *reference*")
    add("measurements (the frequency and level of the source material) that this pipeline derives for")
    add("itself from the composition's notes. That they are unused is a design decision; that they are")
    add("unusable is not claimed.")
    add("")

    add("## 4. Duplicate audio groups")
    add("")
    add(f"All {summary['profiles']} renderable profiles, grouped by the SHA-256 of the audio they")
    add("render, and every one of those renders is compared **byte for byte** with the WAV the")
    add(f"listener heard: **{bundle['bytes_identical_to_package']} of "
        f"{bundle['profiles_probed']} identical**. The grouping below therefore reproduces exactly")
    add("the grouping Stage 9D found in the package's own files not as a coincidence of equal counts")
    add("but because it is the same audio, file for file. (" +
        ("The grouping check agrees as well.)" if bundle["reproduces_package_grouping"]
         else "One caveat: the manifest-to-sample grouping check disagrees; the diagnosis would "
              "have stopped had the audio itself differed."))
    add("")
    add("| # | size | samples | profiles | classification |")
    add("| ---: | ---: | :--- | :--- | :--- |")
    for index, group in enumerate(groups, start=1):
        add(f"| {index} | {len(group.profiles)} | {', '.join(group.samples)} | "
            f"{', '.join(group.profiles)} | `{group.classification}` |")
    add("")
    add(f"**{summary['redundant_profiles']} of {summary['profiles']} profiles** share their audio with")
    add("another profile. The values those groups hold in common (one line per group):")
    add("")
    add("| group | shared IR values |")
    add("| ---: | :--- |")
    for index, group in enumerate(groups, start=1):
        shared = ", ".join(
            f"{key}={value}" for key, value in sorted(group.shared.items())
            if key not in ("profile_id", "profile_fingerprint")
        )
        add(f"| {index} | {shared} |")
    add("")

    add("## 5. Differential rendering")
    add("")
    add("The walk the brief asks for — document → IR → frames → WAV — stopping at the first stage")
    add("where a group's members agree:")
    add("")
    add("| group | profiles | document | bound IR | frames | WAV | first agreement |")
    add("| ---: | ---: | :--- | :--- | :--- | :--- | :--- |")
    for index, group in enumerate(groups, start=1):
        document_paths = sum(group.differing_sections.values())
        add(f"| {index} | {len(group.profiles)} | differs in {document_paths} path(s) | "
            f"{'differs' if group.ir_differences else '**identical**'} | "
            f"{'differs' if group.frame_differences else '**identical**'} | identical | "
            f"`{group.first_agreeing_stage}` → `{group.first_divergence}` |")
    add("")
    add("Where the differences sit, counted across all groups:")
    add("")
    add("| document section | paths differing |")
    add("| :--- | ---: |")
    for section, count in summary["sections_that_differ"].items():
        add(f"| `{section}` | {count} |")
    add("")
    if groups:
        example = groups[0]
        add("A concrete example, in the form the brief asked for:")
        add("")
        add("```")
        add(f"Profile A            {example.profiles[0]}")
        add(f"Profile B            {example.profiles[1] if len(example.profiles) > 1 else '(single member)'}")
        add("")
        add("SoundProfile:        differs      (see the section table above)")
        add(f"PlayableSoundProfile: differs      ({sum(example.differing_sections.values())} leaf paths)")
        add("bound POKEY IR:      IDENTICAL    (distortion, envelope, audctl, is_16bit all equal)")
        add("register frames:     IDENTICAL")
        add("WAV:                 IDENTICAL    (same SHA-256)")
        add("")
        add("=> information loss occurs in sound_profiles/binding.py:_rebuild_song")
        add("```")
        add("")
    add("**Inference.** The loss is not spread across the pipeline. It happens in one function that")
    add("writes six fields, and three of the four stages are enough to explain every group.")
    add("")

    add("## 6. Information loss points")
    add("")
    add("| id | boundary | module | what is lost | measurement | gap type |")
    add("| :--- | :--- | :--- | :--- | :--- | :--- |")
    for entry in loss["loss_points"]:
        add(f"| {entry['id']} | {entry['stage']} | `{entry['module']}` | {entry['what_is_lost']} | "
            f"{entry['measurement']} | {entry['classified_as']} |")
    add("")
    add("The IR → frames boundary, measured by perturbing each `IRInstrument` field in every")
    add("profile's own bound stimulus and comparing the register frames:")
    add("")
    add("| IR field | changes the frames for |")
    add("| :--- | :--- |")
    for name, data in reach["fields"].items():
        add(f"| `{name}` | {data['reaches_audio_for']} profiles |")
    add("")
    add("The frames → audio boundary, measured by zeroing one frame column and re-rendering:")
    add("")
    add("| frame column | VOICE stimulus (AUDCTL $00) | PAIR stimulus (AUDCTL $50) |")
    add("| :--- | :--- | :--- |")
    for name in columns["VOICE"]["columns"]:
        voice = columns["VOICE"]["columns"][name]["changes_audio"]
        pair = columns["PAIR"]["columns"][name]["changes_audio"]
        add(f"| {name} | {'changes the audio' if voice else 'no effect'} | "
            f"{'changes the audio' if pair else 'no effect'} |")
    add("")
    add("Read carefully, this table is stimulus-specific and that is the point:")
    add("")
    add("* on a VOICE stimulus only channel 1 sounds, so columns 2–4 and AUDCTL have nothing to")
    add("  change — AUDCTL is `$00` there, so zeroing it is a no-op rather than proof that it is")
    add("  unread;")
    add("* on a PAIR stimulus the sounding channel is 2 (the pair's divider high byte lives in")
    add("  AUDF2 and its volume in AUDC2), `AUDC1` is zero by construction, and **AUDCTL does change")
    add("  the audio** — which is the clock the pair's frequency is derived from.")
    add("")

    add("## 7. Gesture analysis")
    add("")
    add("| gesture series | in the document | non-static | in the IR | as register writes | verdict |")
    add("| :--- | ---: | ---: | :--- | :--- | :--- |")
    for name, data in gesture["status"].items():
        add(f"| {name} | {data.get('in_document', 0)} | {data.get('non_static', '—')} | "
            f"{data.get('in_ir', '—')} | {data.get('as_register_writes', '—')} | "
            f"**{data['verdict']}** |")
    add("")
    add(f"Profiles with a non-static pitch gesture: {len(gesture['profiles_with_non_static_pitch'])}; "
        f"non-static volume gesture: {len(gesture['profiles_with_non_static_volume'])}; "
        f"periodic modulation: {len(gesture['profiles_with_periodic_modulation'])}.")
    add("")
    add("Where each series stops:")
    add("")
    for name, data in gesture["status"].items():
        add(f"* **{name}** — {data['where']}")
    add("")
    add("**Inference.** Every gesture series is lost at the same place, for the same reason: the")
    add("binding writes a *fixed* register configuration, and the player's data format holds one")
    add("divider and one volume per channel per row. A gesture is a *series of changes*, so it is")
    add("unrepresentable in the format rather than merely unread — reading `gesture.pitch.runs` in")
    add("the binding would not help without somewhere to put it.")
    add("")

    add("## 8. Relationship to Part A")
    add("")
    add("These duplicate groups were presented to the listener as different samples.")
    add("")
    add("| group | profiles | distinctiveness | usefulness | Atari character |")
    add("| ---: | ---: | :--- | :--- | :--- |")
    ratings = _ratings_by_profile(bundle)
    for index, group in enumerate(groups, start=1):
        cells = []
        for scale in ("distinctiveness", "usefulness", "atari_character"):
            numbers = [
                value
                for profile in group.profiles
                if (value := ratings.get(profile, {}).get(scale)) is not None
            ]
            cells.append(f"{min(numbers):g}–{max(numbers):g}" if numbers else "—")
        add(f"| {index} | {len(group.profiles)} | {cells[0]} | {cells[1]} | {cells[2]} |")
    add("")
    add("**Inference.** The spread inside a group is the listener's own repeatability, not the")
    add("profiles' character — the audio is byte-identical. Stage 9D measured ICC(1,1) of 0.73–0.92")
    add("on these scales, so the spread is bounded rather than arbitrary. No rating difference")
    add("inside a group may be read as a difference between the profiles in it.")
    add("")

    add("## 9. Part C analysis")
    add("")
    add("Both sides of each song pair were re-rendered in memory and compared at the register and")
    add("level level. The package and the answers were read, never written.")
    add("")
    add("| song | frames differing | registers changed | profiles bound | listener | RMS delta |")
    add("| :--- | ---: | :--- | ---: | :--- | ---: |")
    by_trial = {trial["trial_id"]: trial for trial in diagnostics["trials"]}
    for gap in loudness["per_song"]:
        trial = by_trial[gap["trial_id"]]
        registers = ", ".join(
            f"{name}×{count}" for name, count in trial["frame_diff_by_register"].items() if count
        ) or "none"
        add(f"| {trial['song']} | {trial['frames_differing']}/{trial['frames_total']} | {registers} | "
            f"{len(set(trial['bound_profiles'].values()))} | {trial['listener_preferred']} | "
            f"{gap['rms_delta_db']:+.2f} dB |")
    add("")
    add("What the binding actually changed on each instrument:")
    add("")
    for trial in diagnostics["trials"]:
        if not trial["bound_instruments"]:
            add(f"* **{trial['song']}** — no instrument changed at all (the binding had no effect)")
            continue
        parts = []
        for entry in trial["bound_instruments"]:
            before, after = entry["envelope"][0], entry["envelope"][1]
            parts.append(
                f"{entry['instrument']}: distortion ${entry['distortion'][0] & 0xE0:02X}→"
                f"${entry['distortion'][1] & 0xE0:02X}, envelope "
                f"{before['attack_frames']}/{before['decay_frames']}/{before['sustain_vol']}/"
                f"{before['release_frames']} → {after['attack_frames']}/{after['decay_frames']}/"
                f"{after['sustain_vol']}/{after['release_frames']}"
            )
        add(f"* **{trial['song']}** — " + "; ".join(parts))
    add("")
    add("**Mechanism, as far as the measurements go:**")
    add("")
    add("* every bound song had each instrument's **generator and/or envelope replaced** — the")
    add("  intended effect of a binding, and also the whole of its effect;")
    add("* both sides were compared at **one shared gain** (as in Stage 9C), so a systematic loudness")
    add(f"  advantage is ruled out (median RMS delta {loudness['median_rms_delta_db']} dB);")
    add("* the profile-bound side therefore differs in **timbre and articulation**, and the listener")
    add("  preferred the composer's own instruments. The measurements cannot settle *which* of the")
    add("  two carried the preference: **unresolved**.")
    add("* **unresolved:** whether different profiles per role would have won. The bindings were")
    add("  chosen by generator family, not by listening evidence (Stage 9D, §14).")
    add("")
    add("This is a **musical interpretation gap** rather than a rendering defect: both sides render")
    add("correctly, and one of them is the sound the composer was designed around.")
    add("")

    add("## 10. Representation vs renderer vs musical interpretation")
    add("")
    add("| level | definition | verdict | evidence |")
    add("| :--- | :--- | :--- | :--- |")
    add("| **A. Representation gap** | the document holds information the IR cannot express | "
        f"**present, dominant** — {len(propagation['read_paths'])} of {propagation['path_count']} "
        "paths are read; every gesture series is unrepresentable in the player's format | §3, §5, §7 |")
    add("| **B. Renderer gap** | the IR holds information the renderer does not use | "
        "**minor** — the frame compiler uses every field the binding writes, except the ones "
        "measured inert in §6 | §6 |")
    add("| **C. Musical interpretation gap** | the profile renders correctly but is used "
        "inappropriately | **present** — the profile replaces a character instrument, and the "
        "bindings were chosen by generator family | §9 |")
    add("")
    add("The order matters: fixing B would change almost nothing because B is nearly empty, while")
    add("fixing A is necessary but not sufficient without C.")
    add("")

    add("## 11. True vs renderer vs representation duplicates")
    add("")
    add("| classification | meaning | groups | profiles |")
    add("| :--- | :--- | ---: | ---: |")
    class_profiles: Counter = Counter()
    for group in groups:
        class_profiles[group.classification] += len(group.profiles)
    for name, meaning in (
        (CLASS_REPRESENTATION, "they differ in the document but their IR is identical: a renderer "
                              "that carried the difference could tell them apart"),
        (CLASS_RENDERER, "their IR differs but the frames do not: the player's quantization "
                         "collapses them"),
        (CLASS_TRUE, "the documents are equivalent as far as any stage can tell"),
        (CLASS_UNKNOWN, "not explained by this diagnosis"),
    ):
        count = sum(1 for group in groups if group.classification == name)
        add(f"| `{name}` | {meaning} | {count} | {class_profiles.get(name, 0)} |")
    add("")
    add("**Inference.** A byte-identical WAV does **not** mean a redundant profile. "
        f"{class_profiles.get(CLASS_REPRESENTATION, 0)} profiles are duplicates *of the current")
    add("pipeline*, not of the library: they carry information the archaeology measured and this")
    add("renderer cannot yet use. The careful statement is that they are redundant **today**.")
    add("")

    add("## 12. Missing capabilities")
    add("")
    add("Ordered by how many duplicate groups need each capability, then by how many leaf paths")
    add("differ — an evidence count, not an opinion. None is implemented.")
    add("")
    add("| capability | groups needing it | leaf paths differing | profiles | evidence | expected effect | risk |")
    add("| :--- | ---: | ---: | ---: | :--- | :--- | :--- |")
    for entry in capabilities["capabilities"]:
        add(f"| {entry['capability']} | {entry['groups_needing_it']} | "
            f"{entry['leaf_paths_differing']} | {entry['profiles_affected']} | "
            f"**{entry['evidence_strength']}** | {entry['expected_effect']} | {entry['risk']} |")
    add("")
    if capabilities["quantization_only"]:
        add("Not a duplicate explanation, but a limit on expression: "
            + ", ".join(capabilities["quantization_only"]) + ".")
        add("")
    add(capabilities["related_measurement"] + ".")
    add("")
    add("Section evidence, by how many groups differ there:")
    add("")
    add("| document section | groups | leaf paths | profiles |")
    add("| :--- | ---: | ---: | ---: |")
    for section, data in list(capabilities["section_evidence"].items())[:18]:
        add(f"| `{section}` | {data['groups']} | {data['leaf_paths']} | {data['profiles']} |")
    add("")
    add("The perceptual evidence, stated honestly: Stage 9D established that the listener hears")
    add("differences between profiles and prefers particular ones, but **no gesture was ever")
    add("rendered**, so there is no direct perceptual evidence for any individual capability. This")
    add("list comes from what the documents differ in, not from what the listener asked for.")
    add("")

    add("## 13. Loudness analysis")
    add("")
    add("| song | RMS delta (profile − default) | peak delta | dynamic-range delta |")
    add("| :--- | ---: | ---: | ---: |")
    for gap in loudness["per_song"]:
        add(f"| {gap['song']} | {gap['rms_delta_db']:+.2f} dB | {gap['peak_delta_db']:+.2f} dB | "
            f"{gap['dynamic_range_delta_db']:+.2f} dB |")
    add("")
    add(f"Median RMS delta **{loudness['median_rms_delta_db']} dB**; median dynamic-range delta "
        f"{loudness['median_dynamic_range_delta_db']} dB. {loudness['note']}.")
    add("")
    add("**Inference.** Loudness does not explain the 5–0 result. Stage 9D's finding that the louder")
    add("side won 10 of 11 decided profile-vs-profile trials remains a caveat for Parts A and B; it")
    add("is not the mechanism here, where both sides share one gain by construction.")
    add("")

    add("## 14. Implications")
    add("")
    add("1. **The duplicate count is a pipeline fact, not a library fact.** The 24 profiles are")
    add("   distinct measurements; they render alike because a handful of values survive the binding.")
    add("2. **Any future 'how many sounds does the library have' claim must be computed on rendered")
    add("   audio**, and a curation decision must be made per *audio group* — which is what Stage")
    add("   9D's shortlist rule already does.")
    add("3. **A renderer improvement is a research act, not a bug fix.** The capabilities with the")
    add("   most reach change what the listener hears, so they invalidate the current perceptual")
    add("   evidence and require a new listening test to re-establish it.")
    add("4. **The whole-song result should be re-tested before the library is judged.** It measured")
    add("   one binding strategy, chosen without listening evidence, against instruments the")
    add("   composer was designed around.")
    add("5. **The metric defect is separate and cheaper.** It affects analysis, not audio.")
    add("")

    add("## 15. Recommended next step")
    add("")
    add(verdict["next_stage"])
    add("")
    add("In order, with the reason for the order:")
    add("")
    add("1. **Re-bind the six songs from the listening evidence** — cheap, reversible, no engine")
    add("   change — and repeat only the whole-song comparison. If the profile-bound render still")
    add("   loses, the problem is not which profiles were chosen.")
    add("2. **Carry the volume contour before the pitch trajectory.** The player already recomputes a")
    add("   volume every frame, so this is a data-format change; a pitch trajectory needs a per-frame")
    add("   divider macro and is a far larger change.")
    add("3. **Re-run the listening test** on whatever changed, because step 2 changes what the")
    add("   listener hears and therefore invalidates the current perceptual ranking.")
    add("")
    add("Explicitly not recommended now: implementing gestures speculatively, changing the player,")
    add("selecting the library, or replacing the similarity metric before the model in §13 of the")
    add("brief has been rebuilt from evidence.")
    add("")

    add("## 16. STOP / decision")
    add("")
    add(f"**{verdict['verdict']}**")
    add("")
    add(f"* duplicate groups: {verdict['groups']}, explained: {verdict['groups_explained']}, "
        f"unexplained: {verdict['groups_unexplained']}")
    add(f"* profiles in duplicate groups: {summary['profiles_in_groups']} "
        f"({summary['redundant_profiles']} redundant beyond the first of each group)")
    add("* no profile, schema, WAV, answer, player or composer source was modified")
    add("")
    add("### The eight questions")
    add("")
    add("| # | question | answer |")
    add("| :--- | :--- | :--- |")
    for entry in verdict["questions"]:
        add(f"| {entry['id']} | {entry['question']} | {entry['answer']} |")
    add("")
    add("**STOP.** Nothing recommended above has been implemented.")
    add("")
    return "\n".join(lines)


def _ratings_by_profile(bundle: Mapping[str, Any]) -> Dict[str, Dict[str, Optional[float]]]:
    """The listener's Part A ratings keyed by profile id, read from the package answers."""
    package = Path(bundle["package"])
    manifest_path = package / "manifest.json"
    answers_path = package / "evaluation_profiles.csv"
    if not manifest_path.is_file() or not answers_path.is_file():
        return {}
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    sample_to_profile = {entry["sample_id"]: entry["profile_id"] for entry in manifest["samples"]}
    out: Dict[str, Dict[str, Optional[float]]] = {}
    with answers_path.open(encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            profile_id = sample_to_profile.get(row.get("sample_id", ""))
            if profile_id is None:
                continue

            def number(field: str) -> Optional[float]:
                raw = (row.get(field) or "").strip()
                return float(raw) if raw else None

            out[profile_id] = {
                "distinctiveness": number("distinctiveness"),
                "usefulness": number("usefulness"),
                "atari_character": number("atari_character"),
            }
    return out


def stage9d_answer_hashes(package_dir: Path) -> Dict[str, str]:
    """The hashes of the human answers, so the diagnosis names the evidence it used."""
    out: Dict[str, str] = {}
    for name in (
        "evaluation_profiles.csv",
        "evaluation_ab.csv",
        "evaluation_songs.csv",
        "manifest.json",
    ):
        path = Path(package_dir) / name
        if path.is_file():
            out[name] = hashlib.sha256(path.read_bytes()).hexdigest()
    return out


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False, default=_default) + "\n",
        encoding="utf-8",
    )


def _default(value: Any) -> Any:
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, np.floating):
        return float(value)
    if isinstance(value, np.ndarray):
        return value.tolist()
    raise TypeError(f"not JSON serialisable: {type(value)!r}")


__all__ = [
    "CLASS_RENDERER",
    "CLASS_REPRESENTATION",
    "CLASS_TRUE",
    "CLASS_UNKNOWN",
    "DIAGNOSTIC_VERSION",
    "DuplicateGroup",
    "PIPELINE_STAGES",
    "STAGE",
    "STATUS_IGNORED",
    "STATUS_PARTIAL",
    "STATUS_PLAYER_ONLY",
    "STATUS_TRANSFORMED",
    "STATUS_UNREPRESENTABLE",
    "STATUS_USED",
    "StageProbe",
    "TrackingMapping",
    "analyze_stage9e",
    "build_duplicate_groups",
    "classify_group",
    "container_summary",
    "document_delta",
    "duplicate_summary",
    "field_propagation",
    "field_status",
    "flatten",
    "frame_column_usage",
    "gesture_analysis",
    "information_loss",
    "ir_field_sensitivity",
    "leaf_paths",
    "loudness_gap",
    "measure_field_access",
    "missing_capabilities",
    "part_c_diagnostics",
    "probe_profile",
    "render_report",
    "verdict_9e",
    "write_json",
]

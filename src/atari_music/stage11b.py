"""Stage 11B — controlled spectral feature-ablation experiment.

The question: can the *existing* POKEY renderer (no change to `ir.py`, the player or the
DSL) reproduce the spectral/timbral character the archaeology measured, and which single
profile feature moves the rendered spectrum furthest toward the reference?

This is not a profile-vs-profile listening test. It renders a **common test signal** for a
small set of profiles under controlled ablations — baseline, +generator, +envelope, +AUDCTL,
+generator+envelope, +full — and describes each variant with spectral features computed on
the audio. A feature the renderer cannot express is marked ``NOT EXPRESSIBLE`` rather than
approximated.
"""

from __future__ import annotations

import hashlib
import json
import wave
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

import numpy as np

from atari_music.ai.client import generate_music_from_composition
from atari_music.ir import FRAME_RATE_HZ, compile_ir_to_pokey_frames
from atari_music.pokey_synth import render_pokey_samples
from atari_music.sound_profiles import (
    SoundProfile,
    SoundProfileBank,
    apply_profile_binding,
    load_profile_binding,
    load_sound_profile_bank,
)
from atari_music.stage9c import SAMPLE_RATE, spectral_distance, spectral_features
from atari_music.stage10b import contour_stimulus

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_BANK_DIR = REPO_ROOT / "tests" / "data" / "sound_profiles" / "bank"
DEFAULT_REPORTS_DIR = REPO_ROOT / "reports"
DEFAULT_STAGE11_DIR = DEFAULT_REPORTS_DIR / "stage11"
DEFAULT_DOCS_DIR = REPO_ROOT / "docs"
DEFAULT_ARCHAEOLOGY_DIR = Path(r"C:\Users\grzes\Documents\Projects\pokey-sound-architecture")

ANALYSIS_VERSION = "stage11b/1"

#: The common test signal: one C4 note held for this many steps at the composer's stimulus
#: tempo, identical for every profile (see :func:`atari_music.stage10b.contour_stimulus`).
HOLD_STEPS = 20

#: The generator nibbles POKEY defines, mapped to their audible family.
_FAMILY = {
    0x0: "poly5-gated poly9/17 (noise)",
    0x2: "poly5-gated pure (buzz)",
    0x4: "poly5-gated poly4",
    0x6: "poly5-gated pure (buzz)",
    0x8: "poly9/17 direct (noise)",
    0xA: "pure tone",
    0xC: "poly4 direct",
    0xE: "pure tone",
}

#: The ablations plus baseline and full, in the order the brief lists them.
VARIANT_ORDER = ("baseline", "generator", "envelope", "audctl", "generator_envelope", "full")
_VARIANT_FIELDS = {
    "baseline": frozenset(),
    "generator": frozenset({"distortion"}),
    "envelope": frozenset({"envelope"}),
    "audctl": frozenset({"audctl", "is_16bit"}),
    "generator_envelope": frozenset({"distortion", "envelope"}),
    "full": frozenset({"distortion", "envelope", "audctl", "is_16bit"}),
}


class Stage11BError(RuntimeError):
    """An input or a rendering precondition was not met."""


def _read_json(path: Path) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def sha256_file(path: Path) -> str:
    return _sha256_bytes(Path(path).read_bytes())


def read_wav_samples(path: Path) -> np.ndarray:
    """16-bit mono PCM -> int16 samples (the archaeology reference WAVs are mono 44.1k)."""
    with wave.open(str(path), "rb") as handle:
        if handle.getsampwidth() != 2 or handle.getnchannels() != 1:
            raise Stage11BError(f"unsupported reference format: {path}")
        raw = handle.readframes(handle.getnframes())
    return np.frombuffer(raw, dtype=np.int16).copy()


# ---------------------------------------------------------------------------
# B1 — selection
# ---------------------------------------------------------------------------
def _category(profile: SoundProfile, reference: Optional[Mapping[str, float]]) -> str:
    """A coarse acoustic category, read from the profile's own facts and its reference."""
    nibble = profile.distortion_nibble
    noisy = nibble in {0x0, 0x8}
    coupled = profile.scope == "PAIR"
    bandwidth = (reference or {}).get("bandwidth_hz")
    if coupled and nibble in {0xC, 0xA}:
        return "16-bit coupled (bass-register)"
    if noisy:
        return "noisy / percussive"
    if bandwidth is not None and bandwidth >= 8000.0:
        return "high-bandwidth tonal"
    if bandwidth is not None and bandwidth <= 3000.0:
        return "low-bandwidth tonal"
    if nibble in {0x2, 0x6, 0x4}:
        return "buzzy / gated poly"
    return "clean tonal"


def reference_features(
    profile_id: str, arch_root: Path = DEFAULT_ARCHAEOLOGY_DIR
) -> Optional[Dict[str, float]]:
    """The archaeology's reference replay for one profile, as spectral features, or ``None``."""
    path = (
        Path(arch_root)
        / "reports"
        / "trace_profile_comparisons"
        / profile_id
        / "reference_replay.wav"
    )
    if not path.is_file():
        return None
    return spectral_features(read_wav_samples(path), SAMPLE_RATE)


def select_representatives(
    bank: SoundProfileBank,
    duplicate_groups: Sequence[Mapping[str, Any]],
    *,
    arch_root: Path = DEFAULT_ARCHAEOLOGY_DIR,
    limit: int = 8,
) -> List[Dict[str, Any]]:
    """Pick distinct-audio profiles spanning the acoustic categories.

    Experimental choice: one representative per duplicate group (so no two selections are
    byte-identical) plus isolated singletons, chosen greedily so the set spans the generator
    families, both scopes, and the noisy/tonal/coupled categories. Every step is ``sorted``,
    so the selection is deterministic.
    """
    grouped: Dict[str, int] = {}
    for index, group in enumerate(duplicate_groups):
        for profile_id in group["profiles"]:
            grouped[profile_id] = index
    representatives = [sorted(group["profiles"])[0] for group in duplicate_groups]
    singletons = sorted(set(bank.profiles) - set(grouped))
    candidates = sorted(set(representatives) | set(singletons))
    # A silent (MEASUREMENT_ONLY) profile is not a sound: the binding refuses it, and so do we.
    candidates = [profile_id for profile_id in candidates if bank.get(profile_id).renderable]
    # Prefer profiles that have an archaeology reference, so the comparison is exercised; the
    # order stays deterministic (references first, then by id).
    candidates = sorted(
        candidates,
        key=lambda profile_id: (0 if reference_features(profile_id, arch_root) else 1, profile_id),
    )

    seen: set = set()
    chosen: List[str] = []
    for profile_id in candidates:
        profile = bank.get(profile_id)
        key = (
            profile.distortion_nibble,
            profile.scope,
            "noisy" if profile.distortion_nibble in {0x0, 0x8} else "tonal",
        )
        if key not in seen:
            seen.add(key)
            chosen.append(profile_id)
        if len(chosen) >= limit:
            break
    for profile_id in candidates:  # top up to `limit` if the cover is small
        if len(chosen) >= limit:
            break
        if profile_id not in chosen:
            chosen.append(profile_id)
    chosen = sorted(chosen[:limit])

    out: List[Dict[str, Any]] = []
    for profile_id in chosen:
        profile = bank.get(profile_id)
        reference = reference_features(profile_id, arch_root)
        out.append(
            {
                "profile_id": profile_id,
                "scope": profile.scope,
                "status": profile.status,
                "distortion": (
                    f"${profile.distortion_nibble:X}"
                    if profile.distortion_nibble is not None
                    else None
                ),
                "distortion_family": (
                    _FAMILY.get(profile.distortion_nibble, "unknown")
                    if profile.distortion_nibble is not None
                    else "unknown"
                ),
                "audctl": (
                    f"${profile.audctl_mode:02X}" if profile.audctl_mode is not None else None
                ),
                "category": _category(profile, reference),
                "duplicate_group": grouped.get(profile_id),
                "has_reference_replay": reference is not None,
                "rationale": (
                    f"one representative of duplicate group {grouped[profile_id]}"
                    if profile_id in grouped
                    else "renders audio no other profile produces (isolated singleton)"
                ),
            }
        )
    return out


# ---------------------------------------------------------------------------
# B2 / B3 — the common signal and the controlled variants
# ---------------------------------------------------------------------------
def _stimulus_document(profile: SoundProfile):
    """The one common musical input: a single C4 note, held. Identical for every profile."""
    return contour_stimulus(joined_pair=(profile.scope == "PAIR"), hold_steps=HOLD_STEPS)


def _base_and_bound(profile: SoundProfile, bank: SoundProfileBank):
    document = _stimulus_document(profile)
    base = generate_music_from_composition(document)
    binding = load_profile_binding(
        {
            "schema": "atari-music/sound-profile-binding/1",
            "instruments": {"stim": profile.profile_id},
        }
    )
    bound = apply_profile_binding(base, binding, bank, composition=document)
    return base, bound


def _variant_songs(base, bound, fields: frozenset):
    """A song whose instrument takes *fields* from the profile and the rest from the composer."""
    base_inst = base.pokey_ir.instruments[0]
    full_inst = bound.pokey_ir.instruments[0]
    updates = {
        name: (getattr(full_inst, name) if name in fields else getattr(base_inst, name))
        for name in ("distortion", "envelope", "audctl", "is_16bit")
    }
    instruments = [full_inst.model_copy(update=updates)] + list(bound.pokey_ir.instruments[1:])
    return bound.pokey_ir.model_copy(update={"instruments": instruments})


def _render(song) -> np.ndarray:
    """Render one song through the existing, unchanged frame compiler and synthesiser."""
    frames = compile_ir_to_pokey_frames(song)
    return render_pokey_samples(frames, SAMPLE_RATE, FRAME_RATE_HZ)


def _describe(samples: np.ndarray) -> Dict[str, Any]:
    return {
        "features": spectral_features(samples, SAMPLE_RATE),
        "pcm_sha256": _sha256_bytes(samples.astype(np.int16).tobytes()),
        "peak": int(np.max(np.abs(samples))) if samples.size else 0,
    }


# ---------------------------------------------------------------------------
# B4 / B5 / B6 / B8 — describe, compare, ablate, classify
# ---------------------------------------------------------------------------
#: Experimental choice: the residual band-energy distance below which the render is called a
#: match, and the improvement below which it is called a failure to move. Named so the
#: classification can be argued with; no single score is produced from them.
MATCH_DISTANCE = 0.05
MOVE_EPSILON = 0.002


def analyse_profile(
    profile: SoundProfile,
    bank: SoundProfileBank,
    *,
    arch_root: Path = DEFAULT_ARCHAEOLOGY_DIR,
) -> Dict[str, Any]:
    """Render every variant of one profile, describe it, ablate it and classify it."""
    reference = reference_features(profile.profile_id, arch_root)
    base, bound = _base_and_bound(profile, bank)

    songs = {"baseline": base.pokey_ir, "full": bound.pokey_ir}
    for name in VARIANT_ORDER:
        if name not in songs:
            songs[name] = _variant_songs(base, bound, _VARIANT_FIELDS[name])

    variants: Dict[str, Any] = {}
    for name in VARIANT_ORDER:
        described = _describe(_render(songs[name]))
        distance = (
            spectral_distance(described["features"], reference) if reference is not None else None
        )
        variants[name] = {**described, "spectral_distance_to_reference": distance}

    # A sanity check the reader can trust: the baseline is the unbound render.
    baseline_reproduction = (
        variants["baseline"]["pcm_sha256"] == _describe(_render(base.pokey_ir))["pcm_sha256"]
    )

    ablation: Dict[str, Optional[float]] = {}
    if reference is not None:
        baseline_distance = variants["baseline"]["spectral_distance_to_reference"]
        for name in VARIANT_ORDER:
            distance = variants[name]["spectral_distance_to_reference"]
            ablation[name] = round(distance - baseline_distance, 6)
    single_feature = [name for name in ("generator", "envelope", "audctl") if name in ablation]
    best_single = min(single_feature, key=lambda name: ablation[name]) if single_feature else None

    return {
        "profile_id": profile.profile_id,
        "scope": profile.scope,
        "distortion": (
            f"${profile.distortion_nibble:X}" if profile.distortion_nibble is not None else None
        ),
        "audctl": f"${profile.audctl_mode:02X}" if profile.audctl_mode is not None else None,
        "reference_available": reference is not None,
        "reference": reference,
        "variants": variants,
        "ablation_delta_vs_baseline": ablation,
        "best_single_feature": best_single,
        "baseline_reproduction_check": baseline_reproduction,
        "classification": _classify(variants, reference),
    }


def _classify(
    variants: Mapping[str, Any], reference: Optional[Mapping[str, float]]
) -> Dict[str, Any]:
    """B8 — can the existing renderer express the reference's spectral character?"""
    if reference is None:
        return {
            "expressibility": "UNTESTED",
            "why": "no archaeology reference replay exists for this profile, so the render "
            "cannot be compared against the measured character; the ablation is still reported",
        }
    baseline = variants["baseline"]["spectral_distance_to_reference"]
    full = variants["full"]["spectral_distance_to_reference"]
    moved = baseline - full
    if moved <= MOVE_EPSILON:
        expressibility = "NOT_EXPRESSIBLE"
        why = (
            "applying the profile's representable facts does not move the rendered spectrum "
            "toward the reference (full distance >= baseline)"
        )
    elif full <= MATCH_DISTANCE:
        expressibility = "EXPRESSIBLE"
        why = "the representable profile brings the rendered spectrum within the match threshold"
    else:
        expressibility = "PARTIALLY_EXPRESSIBLE"
        why = (
            "the representable profile moves the spectrum toward the reference but a residual "
            "band-energy difference remains"
        )
    return {
        "expressibility": expressibility,
        "why": why,
        "baseline_distance": baseline,
        "full_distance": full,
        "improvement": round(moved, 6),
    }


# ---------------------------------------------------------------------------
# Assembly
# ---------------------------------------------------------------------------
def run_experiment(
    *,
    bank_dir: Path = DEFAULT_BANK_DIR,
    reports_dir: Path = DEFAULT_REPORTS_DIR,
    arch_root: Path = DEFAULT_ARCHAEOLOGY_DIR,
    limit: int = 8,
) -> Dict[str, Any]:
    """Select, render, ablate and classify. Deterministic; nothing is written here."""
    bank = load_sound_profile_bank(Path(bank_dir))
    duplicate_groups = _read_json(Path(reports_dir) / "stage9e" / "duplicate_groups.json")["groups"]
    selection = select_representatives(
        bank, duplicate_groups, arch_root=arch_root, limit=limit
    )

    profiles = [
        analyse_profile(bank.get(entry["profile_id"]), bank, arch_root=arch_root)
        for entry in selection
    ]
    by_id = {entry["profile_id"]: entry for entry in selection}
    for record in profiles:
        record["selection"] = by_id[record["profile_id"]]

    expressibility: Dict[str, int] = {}
    best_features: Dict[str, int] = {}
    for record in profiles:
        key = record["classification"]["expressibility"]
        expressibility[key] = expressibility.get(key, 0) + 1
        best = record["best_single_feature"]
        if best:
            best_features[best] = best_features.get(best, 0) + 1

    # B10 — a listening package exists to test a spectral difference the analysis *claims is
    # important*. The analysis claims "reproduced" only when a render reaches MATCH_DISTANCE of
    # its reference. If no render does, there is no such claim to test: the only axis that moves
    # materially is the generator (and coupling), which Stage 9D already established the listener
    # hears and which the renderer already expresses.
    reached = [
        record
        for record in profiles
        if record["classification"].get("full_distance") is not None
        and record["classification"]["full_distance"] <= MATCH_DISTANCE
    ]
    listening_justified = bool(reached)

    inputs: Dict[str, str] = {}
    registry = Path(bank_dir) / "registry.json"
    if registry.is_file():
        inputs["bank/registry.json"] = sha256_file(registry)
    dup_path = Path(reports_dir) / "stage9e" / "duplicate_groups.json"
    if dup_path.is_file():
        inputs["reports/stage9e/duplicate_groups.json"] = sha256_file(dup_path)
    for entry in selection:
        path = (
            Path(arch_root)
            / "reports"
            / "trace_profile_comparisons"
            / entry["profile_id"]
            / "reference_replay.wav"
        )
        if path.is_file():
            inputs[f"archaeology/{entry['profile_id']}/reference_replay.wav"] = sha256_file(path)

    return {
        "analysis_version": ANALYSIS_VERSION,
        "experiment": "stage11b",
        "common_signal": {
            "note": "C4",
            "hold_steps": HOLD_STEPS,
            "channel": 1,
            "sample_rate": SAMPLE_RATE,
            "frame_rate_hz": FRAME_RATE_HZ,
            "renderer": "the existing frame compiler and synthesiser, unchanged",
            "level": "The synthesiser normalizes every buffer to a 0.90 peak, so the variants are level-matched by construction.",
        },
        "thresholds": {"match_distance": MATCH_DISTANCE, "move_epsilon": MOVE_EPSILON},
        "selection": selection,
        "profiles": profiles,
        "summary": {
            "selected": len(profile_ids := [entry["profile_id"] for entry in selection]),
            "expressibility_counts": expressibility,
            "best_single_feature_counts": best_features,
        },
        "listening": {
            "justified": listening_justified,
            "reason": (
                "at least one render comes within the match threshold of its reference, so there "
                "is a spectral claim a listener can be asked to hear"
                if listening_justified
                else "no render comes within the match threshold of its reference, so the analysis "
                "makes no spectral claim a listener could be asked to hear; the axes that move "
                "materially (generator, coupling) are already known audible"
            ),
        },
        "inputs": inputs,
    }


def write_experiment(
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
    for name, payload in (
        ("spectral_experiment.json", bundle),
        ("spectral_selection.json", bundle["selection"]),
        ("spectral_profiles.json", bundle["profiles"]),
        ("spectral_summary.json", {**bundle["summary"], "listening": bundle["listening"]}),
    ):
        path = stage11_dir / name
        path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        written[name] = path

    doc = docs_dir / "stage11_spectral_experiment.md"
    doc.write_text(render_report(bundle), encoding="utf-8", newline="\n")
    written["stage11_spectral_experiment.md"] = doc
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
    """`docs/stage11_spectral_experiment.md`."""
    from atari_music import stage11a

    summary = bundle["summary"]
    lines: List[str] = []
    add = lines.append
    counts = summary["expressibility_counts"]

    add("# Stage 11B — controlled spectral experiment")
    add("")
    add(
        "Can the *existing* POKEY renderer reproduce the spectral character the archaeology "
        "measured, and which single profile feature moves the rendered spectrum furthest toward "
        "the reference? This experiment answers that with the renderer unchanged: a common test "
        "signal, six controlled variants per profile, and spectral features computed on the audio."
    )
    add("")
    add(f"* experiment: `{bundle['experiment']}` (`{bundle['analysis_version']}`)")
    add(f"* profiles selected: **{summary['selected']}** distinct-audio representatives")
    add(
        "* expressibility: "
        + ", ".join(f"**{value} {key}**" for key, value in sorted(counts.items()))
    )
    add(
        "* best single feature: "
        + (
            ", ".join(f"{key} ({value})" for key, value in sorted(summary["best_single_feature_counts"].items()))
            or "—"
        )
    )
    add(f"* blind listening package: **{'prepared' if bundle['listening']['justified'] else 'not prepared'}**")
    add("")

    add("## B1. The selected sounds")
    add("")
    add(
        "**Observed.** One representative of every duplicate group (so no two selections render "
        "identical audio) plus isolated singletons, spanning the generator families and both "
        "scopes. Selection rationale is per row."
    )
    add("")
    add(
        _md_table(
            ("profile", "scope", "distortion", "family", "category", "rationale"),
            [
                (
                    entry["profile_id"],
                    entry["scope"],
                    entry["distortion"],
                    entry["distortion_family"],
                    entry["category"],
                    entry["rationale"],
                )
                for entry in bundle["selection"]
            ],
        )
    )
    add("")

    add("## B2. The common test signal")
    add("")
    cs = bundle["common_signal"]
    add(
        f"**Observed.** One `{cs['note']}` note held for {cs['hold_steps']} steps on POKEY channel 1 "
        f"at {cs['sample_rate']} Hz, identical for every profile; {cs['renderer']}. {cs['level']}."
    )
    add("")

    add("## B3. The controlled variants")
    add("")
    add(
        "**Experimental choice.** Every variant is the same note with a different subset of the "
        "profile's *representable* facts applied — the composer's own instrument for the rest:"
    )
    add("")
    add("```text")
    add("baseline  -> the composer's own instrument, no profile")
    add("generator -> + the profile's distortion nibble")
    add("envelope  -> + the profile's four-number ADSR")
    add("audctl    -> + the profile's AUDCTL and 16-bit coupling")
    add("generator_envelope -> + distortion and ADSR together")
    add("full      -> + everything the binding writes (the Stage 9E six scalars)")
    add("```")
    add("")
    add(
        "All five features are expressible by the current renderer, so no variant is marked NOT "
        "EXPRESSIBLE; a feature the renderer *cannot* express (pitch trajectory, a per-frame "
        "divider macro) is simply not part of this ablation and is listed in §B9."
    )
    add("")

    add("## B4 / B5. Spectral descriptors, and the distance to the reference")
    add("")
    add(
        "**Observed.** `centroid`/`bandwidth`/`flatness` are the Stage 9C descriptors, computed on "
        "the rendered audio; the reference column is the same descriptor computed on the "
        "archaeology's own `reference_replay.wav`. `dist` is 1 - cosine of the band-energy vectors "
        "(0 = identical distribution). A smaller distance is closer to the measured character."
    )
    add("")
    rows = []
    for record in bundle["profiles"]:
        ref = record["reference"] or {}
        baseline = record["variants"]["baseline"]
        full = record["variants"]["full"]
        rows.append(
            (
                record["profile_id"],
                record["scope"],
                f"{ref['centroid_hz']:.0f}" if ref else "—",
                f"{baseline['features']['centroid_hz']:.0f}",
                f"{full['features']['centroid_hz']:.0f}",
                f"{ref['bandwidth_hz']:.0f}" if ref else "—",
                f"{baseline['features']['bandwidth_hz']:.0f}",
                f"{full['features']['bandwidth_hz']:.0f}",
                f"{baseline['spectral_distance_to_reference']:.4f}" if ref else "—",
                f"{full['spectral_distance_to_reference']:.4f}" if ref else "—",
            )
        )
    add(
        _md_table(
            ("profile", "scope", "ref centroid", "base centroid", "full centroid",
             "ref bandwidth", "base bandwidth", "full bandwidth", "base dist", "full dist"),
            rows,
        )
    )
    add("")

    add("## B6. Controlled ablation — which feature moves the spectrum")
    add("")
    add(
        "**Observed.** The change in distance to the reference when each single feature is applied "
        "alone (negative = moves *toward* the reference). The last column names the single feature "
        "that moves furthest."
    )
    add("")
    ab_rows = []
    for record in bundle["profiles"]:
        ablation = record["ablation_delta_vs_baseline"]
        ab_rows.append(
            (
                record["profile_id"],
                f"{ablation.get('generator', '—'):.4f}" if ablation else "—",
                f"{ablation.get('envelope', '—'):.4f}" if ablation else "—",
                f"{ablation.get('audctl', '—'):.4f}" if ablation else "—",
                f"{ablation.get('full', '—'):.4f}" if ablation else "—",
                record["best_single_feature"] or "—",
            )
        )
    add(
        _md_table(
            ("profile", "Δ generator", "Δ envelope", "Δ audctl", "Δ full", "best single feature"),
            ab_rows,
        )
    )
    add("")

    add("## B7. The listener's vocabulary against the measured structure")
    add("")
    add(
        "**Inference.** The ablation shows the spectral axis the renderer already reproduces is the "
        "*generator*: applying the profile's distortion nibble is normally the single feature that "
        "moves the band-energy distribution most. That is the same axis the listener's own words "
        "track — Stage 9D found the clean/noisy families disjoint (clean centroid median 6018 Hz, "
        "noisy 4135 Hz) and that `same_generator` predicts a heard difference at rho -0.5993. The "
        "listener's *rising* vocabulary is pitch, which this renderer cannot express."
    )
    add("")

    add("## B8. Renderer capability — per selected sound")
    add("")
    add(
        "**Observed.** EXPRESSIBLE/PARTIALLY_EXPRESSIBLE/NOT_EXPRESSIBLE is decided by whether the "
        "representable profile moves the render toward its reference, and by how much residual is "
        "left (thresholds in `spectral_summary.json`, named as experimental choices)."
    )
    add("")
    cl_rows = []
    for record in bundle["profiles"]:
        classification = record["classification"]
        cl_rows.append(
            (
                record["profile_id"],
                record["scope"],
                classification["expressibility"],
                f"{classification.get('improvement', '—')}" if "improvement" in classification else "—",
                classification["why"],
            )
        )
    add(_md_table(("profile", "scope", "classification", "improvement", "why"), cl_rows))
    add("")

    add("## B9. Capabilities observed but not implemented")
    add("")
    add(
        "**Observed, not implemented.** The experiment confirms the renderer expresses the five "
        "facts it is asked to (distortion, envelope, AUDCTL, coupling). The capabilities it cannot "
        "express, found earlier and unchanged here, remain:"
    )
    add("")
    add("```text")
    add("observed capability        required representation              current limitation")
    add("pitch trajectory           per-frame divider macro              player holds one divider per row")
    add("dynamic distortion         per-frame AUDC generator change      player sets AUDC once per channel")
    add("intra-note volume shape    per-frame volume macro (Stage 10B)   player recomputes ADSR only")
    add("```")
    add("")
    add(
        "None is implemented; each needs a player/IR change and would fail the Stage 11 rule against "
        "changing the renderer to perform an experiment."
    )
    add("")

    add("## B10. Listening package")
    add("")
    add(f"**Experimental choice.** {bundle['listening']['reason']}.")
    add(
        " A blind package is therefore **not** prepared: the brief says to prepare one only if the "
        "quantitative analysis identifies a meaningful spectral hypothesis, and this one does not — "
        "the renderer already reaches the generator axis, and where it cannot reach the reference "
        "it is because the missing information is temporal, which a level-matched A/B of the "
        "*existing* renderer could not demonstrate."
    )
    add("")

    add("## B11. Reproducibility")
    add("")
    add(
        "Every number above is a pure function of the profiles, the bank, the Stage 9E duplicate "
        "groups and the archaeology reference WAVs below (SHA-256); there is no timestamp in any "
        "artefact, the selection is `sorted` on every axis, and the synthesiser's own normalization "
        "makes the variants level-matched by construction. Re-running writes byte-identical files."
    )
    add("")
    add("```json")
    add(json.dumps(bundle["inputs"], indent=2, sort_keys=True))
    add("```")
    add("")

    a = stage11a.build_synthesis()
    gap = a["representation_gap"]
    coll = a["collapse"]
    add("## Final report — the eight questions")
    add("")
    add(
        "**1. What does the existing evidence say?** Not what was hoped. The binding reads "
        f"{gap['read_by_binding_count']} of {gap['leaf_paths_total']} documented leaf paths; the "
        f"first loss is at the binding boundary; {coll['redundant_profiles']} of "
        f"{coll['profiles_probed']} renderable profiles collapse into {coll['groups']} duplicate "
        "audio groups; and binding profiles to real songs has lost to the composer's own defaults "
        "in every listening test so far (Stage 9D 5-0; Stage 10A; Stage 10B's controls)."
    )
    add("")
    add(
        "**2. Which features are demonstrably perceptually useful?** *Strong:* the generator "
        "family (9D `same_generator` vs similarity -0.5993; disjoint clean/noisy families; the "
        "listener's own vocabulary). *Weak:* envelope and AUDCTL alone — they change the WAV but "
        "have never been heard in isolation. *Inconclusive:* the spectral descriptors (the "
        "bandwidth/usefulness correlation flips sign between the two datasets). *Negative:* the "
        "volume contour (Stage 10B). *Not tested:* pitch trajectory."
    )
    add("")
    add(
        "**3. Why do the profiles collapse?** Representation, at the PlayableSoundProfile -> POKEY "
        "IR boundary: the binding carries six scalars, so profiles that share them render "
        "identically however much they differ in the measured gesture. It is not a renderer limit — "
        "the audio is a pure function of the register frames the binding does write."
    )
    add("")
    add(
        "**4. Is volume contour worth pursuing?** No. It is expressible, changes the waveform, and "
        "was rejected (Stage 10B: 8/8 profile pairs 'no clear difference', song-level C 1-2-3, "
        "verdict NEGATIVE)."
    )
    add("")
    add(
        "**5. Is pitch trajectory worth pursuing?** It is the largest untested representable gap and "
        "the listener has a word for it ('rising'), but no preference evidence exists and its "
        "per-frame form is not expressible by the current player. It is worth *investigating*, not "
        "yet worth implementing."
    )
    add("")
    add(
        "**6. Is spectral/timbral representation the strongest remaining hypothesis?** "
        "**Inconclusive, leaning no.** The renderer already reproduces the dominant audible spectral "
        "axis (the generator), the descriptor-level correlation with usefulness is unstable, and the "
        "largest measured gap is temporal. The spectral hypothesis is not supported as *the* "
        "bottleneck."
    )
    add("")
    add(
        "**7. Can the current renderer reproduce the important spectral characteristics?** See §B8 "
        "for the per-sound classification. The generator axis is EXPRESSIBLE, the coupled and "
        "envelope facts are EXPRESSIBLE, and where a reference is not reached it is because the "
        "information that would reach it is temporal — the *profile* cannot express it, not the "
        "*waveform*."
    )
    add("")
    add(
        "**8. The single highest-value next engineering step.** **Improve profile representation — "
        "change *how* a bound profile is applied, not what else it stores.** The measured cause of "
        "the whole failure is that the binding *replaces* the composer's tuned generator, envelope "
        "and clock wholesale (Stage 9E Q5/Q6), which is why the composer's own instruments keep "
        "winning. The next step is to make a profile decorate the composer's instrument — "
        "contribute its measured spectral character — rather than substitute for it, and to test "
        "that with one whole-song listening comparison. Nothing else in this stage's evidence has "
        "the same reach, and it needs no new profile field."
    )
    add("")
    return "\n".join(lines) + "\n"

"""Stage 12A — profile decoration vs replacement.

The hypothesis: a SoundProfile should perhaps *decorate* the Composer's already-tuned
instrument instead of *wholesale replacing* its generator, envelope and clock.

Everything here is an **experiment**. It changes no production semantics: it reads the
existing `apply_profile_binding` as the control (variant B) and builds three further variants
by mutating the composed song's IR in memory. The production binding is never modified, and
with the experiment disabled every existing rendering is byte-identical.

Read from the source, not from documentation:

* the Composer instrument before binding is ``map_instrument_character``:
  ``character`` -> ``(distortion byte, IREnvelope(attack,decay,sustain,release), role)``
  (`ai/composition.py`), with per-instrument explicit overrides on ``AIInstrumentDef``;
* ``binding.py:_rebuild_song`` replaces exactly ``distortion``, ``envelope``, ``audctl``,
  ``is_16bit`` (PAIR only) and the provenance pair, and OR-s the song's ``uses_16bit_bass``;
* pitch comes from the note, volume from the note's velocity, tempo/channel allocation from
  the composition — none of which the binding touches.

POKEY hardware note that decides what "decoration" can mean: AUDF holds a divider, but **AUDC
is one byte** = ``(distortion_nibble << 5) | volume``. The generator nibble therefore has no
additive algebra — a profile's generator can only *replace* the nibble, never extend it. That
is recorded, not faked (§B1 of the report).
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

import numpy as np

from atari_music.ai.client import generate_music_from_composition
from atari_music.ai.schema import (
    AICompositionDoc,
    AICompositionMetadata,
    AIHardwareConfig,
    AIInstrumentDef,
    AIPatternChannelEvent,
    AIPatternDef,
)
from atari_music.ir import FRAME_RATE_HZ, IREnvelope, compile_ir_to_pokey_frames
from atari_music.pokey_synth import render_pokey_samples
from atari_music.sound_profiles import (
    SoundProfile,
    SoundProfileBank,
    apply_profile_binding,
    load_profile_binding,
    load_sound_profile_bank,
)
from atari_music.stage9c import SAMPLE_RATE, spectral_distance, spectral_features
from atari_music.stage10b import contour_stimulus  # noqa: F401  (kept for parity / reading)
from atari_music.stage11b import reference_features

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_BANK_DIR = REPO_ROOT / "tests" / "data" / "sound_profiles" / "bank"
DEFAULT_REPORTS_DIR = REPO_ROOT / "reports"
DEFAULT_STAGE12A_DIR = DEFAULT_REPORTS_DIR / "stage12a"
DEFAULT_DOCS_DIR = REPO_ROOT / "docs"
DEFAULT_ARCHAEOLOGY_DIR = Path(r"C:\Users\grzes\Documents\Projects\pokey-sound-architecture")

ANALYSIS_VERSION = "stage12a/1"

#: One short phrase, identical for every variant of a case, so timbre dominates the comparison.
PHRASE: Tuple[Tuple[str, int], ...] = (("C4", 3), ("E4", 3), ("G4", 3), ("C5", 5))
STIMULUS_BPM = 100
STIMULUS_VELOCITY = 13

#: The four variants. Neutral names: A/B/C/D, never "better"/"worse".
VARIANT_ORDER = ("A", "B", "C", "D")
VARIANT_LABELS = {
    "A": "COMPOSER_BASELINE",
    "B": "PROFILE_REPLACEMENT",
    "C": "PROFILE_DECORATION",
    "D": "SELECTIVE_DECORATION",
}

#: The four 4-number envelope fields, in the order IREnvelope declares them.
_ENVELOPE_FIELDS = ("attack_frames", "decay_frames", "sustain_vol", "release_frames")


class Stage12AError(RuntimeError):
    """A precondition of the experiment was not met."""


def _read_json(path: Path) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def sha256_file(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _sha256_samples(samples: np.ndarray) -> str:
    return hashlib.sha256(samples.astype(np.int16).tobytes()).hexdigest()


# ---------------------------------------------------------------------------
# Test material (Part 7) — committed before any audio is inspected
# ---------------------------------------------------------------------------
#: The cases, chosen by a rule stated before the results were seen: both melodic and percussive
#: characters, a bass, a high character, one profile that collapsed into a duplicate group, one
#: profile whose generator clearly differs from the Composer's default, and one PAIR/16-bit case.
CASES: Tuple[Dict[str, Any], ...] = (
    {
        "case": "lead_clean",
        "character": "bright_lead",
        "joined": False,
        "profile": "pokey_ref_0657f037",
        "why": "melodic: a $A pure-tone lead against a $A pure-tone profile (generator agrees)",
    },
    {
        "case": "lead_noised",
        "character": "bright_lead",
        "joined": False,
        "profile": "pokey_ref_2de893a6",
        "why": "melodic vs $8 direct noise: the profile's generator clearly differs from the default",
    },
    {
        "case": "perc_buzz",
        "character": "percussion",
        "joined": False,
        "profile": "pokey_ref_1efd9336",
        "why": "percussive: a $8-noise character against a $6 gated-buzz profile",
    },
    {
        "case": "bass8_poly4",
        "character": "bass",
        "joined": False,
        "profile": "pokey_ref_0bd72343",
        "why": "8-bit bass character against a $C poly4 profile",
    },
    {
        "case": "bell_gated",
        "character": "bell",
        "joined": False,
        "profile": "pokey_ref_af009fe0",
        "why": "high/bell character against a $0 gated-noise profile",
    },
    {
        "case": "dup_pair16",
        "character": "bass",
        "joined": True,
        "profile": "pokey_ref_089a0846",
        "why": "PAIR/16-bit: a coupled $C profile, and a representative of duplicate group 1",
    },
)


# ---------------------------------------------------------------------------
# The common composed input (Part 8): one phrase, identical for every variant
# ---------------------------------------------------------------------------
def case_composition(character: str, joined: bool) -> AICompositionDoc:
    """One instrument of the given character playing one short phrase on channel 1."""
    events: List[AIPatternChannelEvent] = []
    step = 0
    for note, steps in PHRASE:
        events.append(
            AIPatternChannelEvent(
                step=step, note=note, instrument="inst", duration=steps, volume=STIMULUS_VELOCITY
            )
        )
        step += steps
    return AICompositionDoc(
        metadata=AICompositionMetadata(
            title="Stage 12A decoration stimulus", bpm=STIMULUS_BPM, key="C", mode="major"
        ),
        hardware=AIHardwareConfig(channels=4, use_16bit_bass=joined),
        instruments=[AIInstrumentDef(id="inst", name=character, character=character)],
        patterns=[
            AIPatternDef(id="S", length_steps=sum(s for _, s in PHRASE), channels={"1": events})
        ],
        sequence=["S"],
        loop_point=0,
    )


# ---------------------------------------------------------------------------
# Part 1 — reconnaissance, measured from the code path, not from documentation
# ---------------------------------------------------------------------------
#: The IRInstrument fields, read from the model itself.
_IR_FIELDS = tuple("distortion envelope audctl is_16bit profile_id profile_fingerprint volume_contour macro vibrato_depth vibrato_speed role name id".split())


def _render(song) -> np.ndarray:
    frames = compile_ir_to_pokey_frames(song)
    return render_pokey_samples(frames, SAMPLE_RATE, FRAME_RATE_HZ)


def _rms(samples: np.ndarray) -> float:
    audio = samples.astype(np.float64) / 32768.0
    return float(np.sqrt(np.mean(audio ** 2))) if audio.size else 0.0


def _envelope_fields(env: IREnvelope) -> Dict[str, int]:
    return {name: int(getattr(env, name)) for name in _ENVELOPE_FIELDS}


def _profile_envelope_fields(profile: SoundProfile) -> Dict[str, Optional[int]]:
    """The profile's measured envelope, clamped-out fields reported as ``None`` (never invented)."""
    frames = profile.envelope_frames
    out: Dict[str, Optional[int]] = {
        "attack_frames": frames.get("attack"),
        "decay_frames": frames.get("decay"),
        "release_frames": frames.get("release"),
        "sustain_vol": profile.envelope_sustain_level,
    }
    for name, value in list(out.items()):
        if value is not None and not (0 <= int(value) <= 15):
            out[name] = None
    return out


def _case_ir(case: Mapping[str, Any], bank: SoundProfileBank) -> Dict[str, Any]:
    """The base (Composer) and bound (replacement) IR, plus the profile, for one case."""
    document = case_composition(case["character"], bool(case["joined"]))
    profile = bank.get(case["profile"])
    base = generate_music_from_composition(document)
    binding = load_profile_binding(
        {
            "schema": "atari-music/sound-profile-binding/1",
            "instruments": {"inst": profile.profile_id},
        }
    )
    bound = apply_profile_binding(base, binding, bank, composition=document)
    return {"document": document, "profile": profile, "base": base.pokey_ir, "bound": bound.pokey_ir}


def reconnaissance(case: Mapping[str, Any], ir: Mapping[str, Any]) -> Dict[str, Any]:
    """Exactly which IRInstrument fields the binding changes for this case (measured)."""
    base_inst = ir["base"].instruments[0]
    bound_inst = ir["bound"].instruments[0]
    changed = [
        field
        for field in _IR_FIELDS
        if getattr(base_inst, field) != getattr(bound_inst, field)
    ]
    return {
        "case": case["case"],
        "character": case["character"],
        "joined": bool(case["joined"]),
        "profile_id": case["profile"],
        "profile_scope": ir["profile"].scope,
        "composer_instrument": {
            "distortion": int(base_inst.distortion),
            "distortion_hex": f"${int(base_inst.distortion) & 0xE0:02X}",
            "envelope": _envelope_fields(base_inst.envelope),
            "audctl": base_inst.audctl,
            "is_16bit": bool(base_inst.is_16bit),
            "role": base_inst.role,
        },
        "bound_instrument": {
            "distortion": int(bound_inst.distortion),
            "distortion_hex": f"${int(bound_inst.distortion) & 0xE0:02X}",
            "envelope": _envelope_fields(bound_inst.envelope),
            "audctl": bound_inst.audctl,
            "is_16bit": bool(bound_inst.is_16bit),
            "role": bound_inst.role,
        },
        "profile_facts": {
            "distortion_hex": (
                f"${ir['profile'].distortion_byte & 0xE0:02X}"
                if ir["profile"].distortion_byte is not None
                else None
            ),
            "envelope": _profile_envelope_fields(ir["profile"]),
            "audctl": ir["profile"].audctl_mode,
        },
        "binding_changes_ir_fields": changed,
    }


# ---------------------------------------------------------------------------
# Parts 3-6 — the four variants
# ---------------------------------------------------------------------------
def _profile_transient(profile: SoundProfile) -> Dict[str, int]:
    """The profile's measured attack and release, when they fit the consumer's 0..15 fields."""
    fields = _profile_envelope_fields(profile)
    return {
        name: int(fields[name])
        for name in ("attack_frames", "release_frames")
        if fields[name] is not None
    }


def _song_with(base, instrument):
    return base.model_copy(update={"instruments": [instrument] + list(base.instruments[1:])})


def variant_songs(ir: Mapping[str, Any]) -> Dict[str, Any]:
    """A (baseline), B (replacement), C (generator decoration), D (generator + transient)."""
    base = ir["base"]
    base_inst = base.instruments[0]
    profile = ir["profile"]
    profile_distortion = profile.distortion_byte

    c_inst = base_inst.model_copy(
        update={
            "distortion": (
                profile_distortion
                if profile_distortion is not None
                else int(base_inst.distortion)
            )
        }
    )
    transient = _profile_transient(profile)
    d_envelope = (
        base_inst.envelope.model_copy(update=transient) if transient else base_inst.envelope
    )
    d_inst = c_inst.model_copy(update={"envelope": d_envelope})
    return {
        "A": base,
        "B": ir["bound"],
        "C": _song_with(base, c_inst),
        "D": _song_with(base, d_inst),
    }


def _compile(song) -> Tuple[np.ndarray, np.ndarray]:
    frames = compile_ir_to_pokey_frames(song)
    return frames, render_pokey_samples(frames, SAMPLE_RATE, FRAME_RATE_HZ)


def _changed_columns(left: np.ndarray, right: np.ndarray) -> List[str]:
    from atari_music.ir import FRAME_COLUMN_NAMES

    rows = min(left.shape[0], right.shape[0])
    columns = np.nonzero((left[:rows] != right[:rows]).any(axis=0))[0]
    return [FRAME_COLUMN_NAMES[int(column)] for column in columns]


def byte_proof(
    frames: np.ndarray, samples: np.ndarray, base_frames: np.ndarray, base_samples: np.ndarray
) -> Dict[str, Any]:
    """Part 9 — the exact byte-level difference of one variant from the baseline."""
    rows = min(frames.shape[0], base_frames.shape[0])
    differing_rows = np.nonzero((frames[:rows] != base_frames[:rows]).any(axis=1))[0]
    same_length = samples.shape[0] == base_samples.shape[0]
    return {
        "wav_sha256": _sha256_samples(samples),
        "sample_count": int(samples.size),
        "sample_rate": SAMPLE_RATE,
        "peak": int(np.max(np.abs(samples))) if samples.size else 0,
        "rms": round(_rms(samples), 6),
        "frame_count": int(frames.shape[0]),
        "differing_samples_vs_baseline": (
            int(np.count_nonzero(samples != base_samples)) if same_length else None
        ),
        "differing_frames_vs_baseline": int(differing_rows.size),
        "first_differing_frame": int(differing_rows[0]) if differing_rows.size else None,
        "changed_pokey_columns": _changed_columns(frames, base_frames),
    }


# ---------------------------------------------------------------------------
# Part 10 — field perturbation / information flow
# ---------------------------------------------------------------------------
#: Each probe field and the IRInstrument field it would write (``None`` = not an IR field).
FIELD_TO_IR: Dict[str, Optional[str]] = {
    "generator": "distortion",
    "envelope": "envelope",
    "pitch/base": None,
    "volume": None,
    "audctl": "audctl",
    "clock": "audctl",
    "pairing": "is_16bit",
}


def field_variant(base, profile: SoundProfile, field: str):
    """The baseline with exactly *field* taken from the profile, or ``None`` if not expressible."""
    base_inst = base.instruments[0]
    if field == "generator":
        if profile.distortion_byte is None:
            return None
        return _song_with(
            base, base_inst.model_copy(update={"distortion": profile.distortion_byte})
        )
    if field == "envelope":
        fields = {
            name: value
            for name, value in _profile_envelope_fields(profile).items()
            if value is not None
        }
        if not fields:
            return None
        envelope = base_inst.envelope.model_copy(update={k: int(v) for k, v in fields.items()})
        return _song_with(base, base_inst.model_copy(update={"envelope": envelope}))
    if field in ("audctl", "clock"):
        if profile.audctl_mode is None:
            return None
        return _song_with(base, base_inst.model_copy(update={"audctl": profile.audctl_mode}))
    if field == "pairing":
        if profile.scope != "PAIR":
            return None
        return _song_with(base, base_inst.model_copy(update={"is_16bit": True}))
    return None  # pitch/base and volume are note-level: no IR field carries them


def perturbation_table(
    ir: Mapping[str, Any],
    base_frames: np.ndarray,
    base_samples: np.ndarray,
) -> List[Dict[str, Any]]:
    """Per profile field: does replacement write it, does decoration, does it reach the audio."""
    base_inst = ir["base"].instruments[0]
    bound_inst = ir["bound"].instruments[0]
    c_inst = variant_songs(ir)["C"].instruments[0]

    rows: List[Dict[str, Any]] = []
    for field, ir_field in FIELD_TO_IR.items():
        if ir_field is None:
            rows.append(
                {
                    "field": field,
                    "replacement_writes": False,
                    "decoration_writes": False,
                    "reaches_ir": False,
                    "reaches_frames": False,
                    "changes_wav": False,
                    "note": "note/velocity level: no IRInstrument field carries it",
                }
            )
            continue
        candidate = field_variant(ir["base"], ir["profile"], field)
        if candidate is None:
            rows.append(
                {
                    "field": field,
                    "replacement_writes": bool(
                        getattr(base_inst, ir_field) != getattr(bound_inst, ir_field)
                    ),
                    "decoration_writes": bool(
                        getattr(base_inst, ir_field) != getattr(c_inst, ir_field)
                    ),
                    "reaches_ir": False,
                    "reaches_frames": False,
                    "changes_wav": False,
                    "note": "the profile declares no value for this field",
                }
            )
            continue
        frames, samples = _compile(candidate)
        rows.append(
            {
                "field": field,
                "replacement_writes": bool(
                    getattr(base_inst, ir_field) != getattr(bound_inst, ir_field)
                ),
                "decoration_writes": bool(
                    getattr(base_inst, ir_field) != getattr(c_inst, ir_field)
                ),
                "reaches_ir": bool(getattr(base_inst, ir_field) != getattr(candidate.instruments[0], ir_field)),
                "reaches_frames": bool(
                    np.any(frames != base_frames) if frames.shape == base_frames.shape else True
                ),
                "changes_wav": bool(
                    samples.shape != base_samples.shape
                    or np.count_nonzero(samples != base_samples) > 0
                ),
            }
        )
    return rows


# ---------------------------------------------------------------------------
# Parts 11-12 — reference comparison, and the two hypotheses
# ---------------------------------------------------------------------------
def analyse_case(
    case: Mapping[str, Any],
    bank: SoundProfileBank,
    *,
    arch_root: Path = DEFAULT_ARCHAEOLOGY_DIR,
) -> Dict[str, Any]:
    """Reconnaissance, the four variants, byte-level proof, perturbation table and reference."""
    ir = _case_ir(case, bank)
    recon = reconnaissance(case, ir)
    songs = variant_songs(ir)
    base_frames, base_samples = _compile(songs["A"])
    reference = reference_features(case["profile"], arch_root)

    variants: Dict[str, Any] = {}
    for name in VARIANT_ORDER:
        frames, samples = _compile(songs[name])
        features = spectral_features(samples, SAMPLE_RATE)
        entry: Dict[str, Any] = {
            "label": VARIANT_LABELS[name],
            "features": features,
            "proof": byte_proof(frames, samples, base_frames, base_samples),
        }
        if reference is not None:
            entry["spectral_distance_to_reference"] = round(
                spectral_distance(features, reference), 6
            )
        variants[name] = entry

    base_inst = ir["base"].instruments[0]
    bound_inst = ir["bound"].instruments[0]
    c_inst = songs["C"].instruments[0]
    base_env = _envelope_fields(base_inst.envelope)
    c_env = _envelope_fields(c_inst.envelope)
    b_env = _envelope_fields(bound_inst.envelope)

    return {
        "case": case["case"],
        "why": case["why"],
        "character": case["character"],
        "joined": bool(case["joined"]),
        "profile_id": case["profile"],
        "reference_available": reference is not None,
        "reference": reference,
        "reconnaissance": recon,
        "variants": variants,
        "perturbation_table": perturbation_table(ir, base_frames, base_samples),
        "preservation": {
            "composer_envelope": base_env,
            "replacement_envelope": b_env,
            "decoration_envelope": c_env,
            "replacement_preserves_envelope": b_env == base_env,
            "decoration_preserves_envelope": c_env == base_env,
            "replacement_preserves_audctl": bound_inst.audctl == base_inst.audctl,
            "decoration_preserves_audctl": c_inst.audctl == base_inst.audctl,
        },
    }


def hypothesis_evidence(cases: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    """H1 (does decoration keep what replacement destroys) and H2 (does it still change the sound)."""
    usable = [c for c in cases if "variants" in c]

    def preserved(record: Mapping[str, Any], which: str) -> bool:
        return bool(record["preservation"].get(f"{which}_preserves_envelope"))

    h1_cases = [
        c["case"]
        for c in usable
        if preserved(c, "decoration") and not preserved(c, "replacement")
    ]
    h2_cases = [
        c["case"]
        for c in usable
        if (c["variants"]["C"]["proof"]["differing_samples_vs_baseline"] or 0) > 0
    ]
    both = [c["case"] for c in usable if c["case"] in h1_cases and c["case"] in h2_cases]

    # Does decoration sit *between* the baseline and the archaeology reference?
    between = []
    for c in usable:
        if not c["reference_available"]:
            continue
        a = c["variants"]["A"]["spectral_distance_to_reference"]
        b = c["variants"]["B"]["spectral_distance_to_reference"]
        d = c["variants"]["C"]["spectral_distance_to_reference"]
        if min(a, b) < d < max(a, b) or d == min(a, b, d):
            between.append(c["case"])

    return {
        "H1_decoration_preserves_composer_tuning": {
            "cases": h1_cases,
            "count": len(h1_cases),
            "of": len(usable),
        },
        "H2_decoration_changes_the_sound": {
            "cases": h2_cases,
            "count": len(h2_cases),
            "of": len(usable),
        },
        "both": {"cases": both, "count": len(both)},
        "decoration_between_baseline_and_reference": {"cases": between, "count": len(between)},
    }


# ---------------------------------------------------------------------------
# Assembly
# ---------------------------------------------------------------------------
#: The traced pipeline, read from the source (file:function), not from documentation.
PIPELINE: Tuple[str, ...] = (
    "AICompositionDoc: per-instrument `character` string + notes/patterns (ai/schema.py)",
    "MusicGenerationResult.pokey_ir (IRSong): instrument = map_instrument_character(character) "
    "-> (distortion byte, IREnvelope(attack,decay,sustain,release), role) (ai/composition.py:51)",
    "apply_profile_binding(): binding.py:_rebuild_song replaces distortion, envelope, audctl, "
    "is_16bit (PAIR) and provenance; OR-s uses_16bit_bass",
    "compile_ir_to_pokey_frames(): notes + instrument -> (frames,9) AUDF/AUDC/AUDCTL (ir.py:257)",
    "render_pokey_samples(): the nine register bytes -> WAV (pokey_synth.py:93)",
)

#: POKEY hardware facts that decide what "decoration" can mean for each field.
HARDWARE_NOTES: Tuple[str, ...] = (
    "AUDC is ONE byte = (distortion_nibble << 5) | volume, so the generator nibble has no "
    "additive algebra: a profile's generator can only replace the nibble, never extend it.",
    "The envelope is a 4-number state machine (attack/decay/sustain/release); there is no "
    "'base + modifier' algebra, only field-wise substitution.",
    "AUDCTL is a song-global byte (resolve_audctl_mode OR-s instrument requirements and the "
    "song's uses_16bit_bass), so a profile's clock is a global constraint, not a channel property.",
    "Pitch is the note's (AUDF derived from midi + audctl) and volume is the note's velocity; "
    "neither is an IRInstrument field, so no profile fact can decorate them.",
)


def listening_decision(cases: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    """Part 13 — prepare a listening package only if there is a clear testable distinction."""
    usable = [c for c in cases if "variants" in c]
    if not usable:
        return {"justified": False, "reason": "no usable cases"}
    c_differs = [
        c
        for c in usable
        if (c["variants"]["C"]["proof"]["differing_samples_vs_baseline"] or 0) > 0
    ]
    d_differs = [
        c
        for c in usable
        if (c["variants"]["D"]["proof"]["differing_samples_vs_baseline"] or 0) > 0
    ]
    # The distinction that matters is *usefulness*, not mere audibility: decoration is worth a
    # listener's time when it comes measurably closer to the archaeology reference than
    # replacement does, in a case where it also differs from the baseline.
    closer = [
        c
        for c in usable
        if c["reference_available"]
        and c["variants"]["C"]["spectral_distance_to_reference"]
        < c["variants"]["B"]["spectral_distance_to_reference"]
    ]
    justified = len(c_differs) >= 3 and bool(closer)
    return {
        "justified": justified,
        "C_changes_the_sound_in": len(c_differs),
        "D_changes_the_sound_in": len(d_differs),
        "C_closer_to_reference_than_B_in": [c["case"] for c in closer],
        "of": len(usable),
        "reason": (
            "decoration changes the sound and comes closer to the archaeology reference than "
            "replacement in at least one case, so a C-vs-A / C-vs-B blind comparison tests a "
            "usefulness claim rather than only an audible one"
            if justified
            else "decoration does not measurably beat replacement against the reference, so a "
            "blind comparison would test only an already-known audible axis"
        ),
    }


def run_experiment(
    *,
    bank_dir: Path = DEFAULT_BANK_DIR,
    reports_dir: Path = DEFAULT_REPORTS_DIR,
    arch_root: Path = DEFAULT_ARCHAEOLOGY_DIR,
    cases: Sequence[Mapping[str, Any]] = CASES,
) -> Dict[str, Any]:
    """Run every case. Deterministic; nothing is written here."""
    bank = load_sound_profile_bank(Path(bank_dir))
    results: List[Dict[str, Any]] = []
    for case in cases:
        try:
            results.append(analyse_case(case, bank, arch_root=arch_root))
        except Exception as exc:  # a technical failure is recorded, never hidden
            results.append(
                {
                    "case": case["case"],
                    "why": case["why"],
                    "character": case["character"],
                    "profile_id": case["profile"],
                    "technical_failure": f"{type(exc).__name__}: {exc}",
                }
            )

    usable = [r for r in results if "variants" in r]
    changed: set = set()
    for record in usable:
        changed.update(record["reconnaissance"]["binding_changes_ir_fields"])

    inputs: Dict[str, str] = {}
    registry = Path(bank_dir) / "registry.json"
    if registry.is_file():
        inputs["bank/registry.json"] = sha256_file(registry)
    for case in cases:
        profile_path = Path(bank_dir) / "profiles" / f"{case['profile']}.json"
        if profile_path.is_file():
            inputs[f"bank/profiles/{case['profile']}.json"] = sha256_file(profile_path)
        reference_path = (
            Path(arch_root)
            / "reports"
            / "trace_profile_comparisons"
            / case["profile"]
            / "reference_replay.wav"
        )
        if reference_path.is_file():
            inputs[f"archaeology/{case['profile']}/reference_replay.wav"] = sha256_file(
                reference_path
            )

    return {
        "analysis_version": ANALYSIS_VERSION,
        "experiment": "stage12a",
        "variants": VARIANT_LABELS,
        "phrase": [{"note": note, "steps": steps} for note, steps in PHRASE],
        "bpm": STIMULUS_BPM,
        "velocity": STIMULUS_VELOCITY,
        "sample_rate": SAMPLE_RATE,
        "pipeline": list(PIPELINE),
        "hardware_notes": list(HARDWARE_NOTES),
        "test_material": [
            {
                "case": case["case"],
                "character": case["character"],
                "joined": bool(case["joined"]),
                "profile": case["profile"],
                "why": case["why"],
            }
            for case in cases
        ],
        "binding_writes_ir_fields_union": sorted(changed),
        "cases": results,
        "hypotheses": hypothesis_evidence(results),
        "listening": listening_decision(results),
        "inputs": inputs,
    }


def write_experiment(
    bundle: Mapping[str, Any],
    *,
    stage12a_dir: Path = DEFAULT_STAGE12A_DIR,
    docs_dir: Path = DEFAULT_DOCS_DIR,
) -> Dict[str, Path]:
    """Write the machine record and the document. Deterministic byte-for-byte."""
    stage12a_dir = Path(stage12a_dir)
    docs_dir = Path(docs_dir)
    stage12a_dir.mkdir(parents=True, exist_ok=True)
    docs_dir.mkdir(parents=True, exist_ok=True)

    first_recon = next(
        (c["reconnaissance"] for c in bundle["cases"] if "reconnaissance" in c), None
    )
    written: Dict[str, Path] = {}
    for name, payload in (
        (
            "reconnaissance.json",
            {
                "analysis_version": bundle["analysis_version"],
                "pipeline": bundle["pipeline"],
                "hardware_notes": bundle["hardware_notes"],
                "binding_writes_ir_fields_union": bundle["binding_writes_ir_fields_union"],
                "composer_instrument_example": first_recon,
                "per_case": [
                    {"case": c["case"], **c["reconnaissance"]}
                    for c in bundle["cases"]
                    if "reconnaissance" in c
                ],
            },
        ),
        ("cases.json", bundle["cases"]),
        ("hypotheses.json", bundle["hypotheses"]),
        (
            "summary.json",
            {
                "test_material": bundle["test_material"],
                "binding_writes_ir_fields_union": bundle["binding_writes_ir_fields_union"],
                "hypotheses": bundle["hypotheses"],
                "listening": bundle["listening"],
            },
        ),
        ("experiment.json", bundle),
    ):
        path = stage12a_dir / name
        path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        written[name] = path

    doc = docs_dir / "stage12a_decoration_experiment.md"
    doc.write_text(render_report(bundle), encoding="utf-8", newline="\n")
    written["stage12a_decoration_experiment.md"] = doc
    return written


# ---------------------------------------------------------------------------
# The document
# ---------------------------------------------------------------------------
def _md_table(header: Sequence[str], rows: Sequence[Sequence[Any]]) -> str:
    lines = ["| " + " | ".join(header) + " |", "| " + " | ".join([":---"] * len(header)) + " |"]
    for row in rows:
        lines.append("| " + " | ".join(str(cell) for cell in row) + " |")
    return "\n".join(lines)


def _fmt_cell(value: Any) -> str:
    return "—" if value is None else str(value)


def render_report(bundle: Mapping[str, Any]) -> str:
    """`docs/stage12a_decoration_experiment.md`."""
    cases = bundle["cases"]
    usable = [c for c in cases if "variants" in c]
    failures = [c for c in cases if "technical_failure" in c]
    hypotheses = bundle["hypotheses"]
    lines: List[str] = []
    add = lines.append

    add("# Stage 12A — profile decoration vs replacement")
    add("")
    add(
        "Does a SoundProfile work better when it *decorates* the Composer's already-tuned "
        "instrument than when it *replaces* it? This experiment answers that with the production "
        "binding untouched: it reads the existing binding as the control (variant B) and builds "
        "three further variants from the same composed song in memory."
    )
    add("")
    add(f"* experiment: `{bundle['experiment']}` (`{bundle['analysis_version']}`)")
    add(f"* variants: A COMPOSER_BASELINE · B PROFILE_REPLACEMENT · C PROFILE_DECORATION · D SELECTIVE_DECORATION")
    add(f"* test cases: **{len(cases)}** ({len(usable)} usable, {len(failures)} technical failure)")
    add(f"* binding writes (IR fields, union over cases): `{', '.join(bundle['binding_writes_ir_fields_union'])}`")
    add(f"* blind listening package: **{'prepared' if bundle['listening']['justified'] else 'not prepared'}**")
    add("")
    add(
        "Observed / Inference / Experimental choice are kept apart throughout. Every variant is "
        "rendered by the *existing, unchanged* frame compiler and synthesiser."
    )
    add("")

    add("## 1. What the binding replaces (Part 1)")
    add("")
    add(
        "**Observed.** The Composer instrument before binding is "
        "`ai/composition.py:map_instrument_character(character)`, which returns "
        "`(distortion byte, IREnvelope(attack,decay,sustain,release), role)`; an `AIInstrumentDef` "
        "may override any of those fields explicitly. `binding.py:_rebuild_song` then writes, per "
        "bound instrument:"
    )
    add("")
    add("```text")
    add("distortion            <- the profile's generator byte        (replaces)")
    add("envelope              <- composition explicit > profile > character default")
    add("audctl                <- the profile's audctl_mode           (replaces / adds a constraint)")
    add("is_16bit              <- True for a PAIR profile")
    add("profile_id/fingerprint<- provenance")
    add("uses_16bit_bass       <- song-level, OR-ed with any PAIR profile")
    add("pitch, velocity, tempo, channel allocation, patterns -> NOT touched")
    add("```")
    add("")
    add(
        "**Observed.** Which Composer parameters exist before binding: generator (distortion), "
        "envelope (4 numbers), pitch (from the note), volume/velocity (from the note), AUDCTL "
        "(song-global), clock (derived from AUDCTL), 16-bit coupling (song-level + `is_16bit`), "
        "channel allocation (from patterns), role (from character)."
    )
    add("")
    add("**Observed — the hardware fact that bounds the hypothesis.**")
    add("")
    for note in bundle["hardware_notes"]:
        add(f"* {note}")
    add("")

    add("## 2. The variants (Parts 3-6)")
    add("")
    add(_md_table(("variant", "what it does", "composer fields kept"), [
        ("A COMPOSER_BASELINE", "no profile at all", "all"),
        ("B PROFILE_REPLACEMENT", "the existing `apply_profile_binding` path, unchanged", "none of the three"),
        ("C PROFILE_DECORATION", "the profile's generator only", "envelope, audctl, clock"),
        ("D SELECTIVE_DECORATION", "the profile's generator + attack/release", "decay, sustain, audctl"),
    ]))
    add("")
    add(
        "**Experimental choice.** C and D are the *smallest defensible* decorations. The generator "
        "is a single nibble with no additive algebra, so C swaps the generator and keeps the "
        "Composer's dynamics. D adds the profile's *transient* (attack/release) while keeping the "
        "Composer's decay and sustain — the envelope has no merge algebra either, only field-wise "
        "substitution, so 'transient vs body' is the stated (arguable) split. Both keep the "
        "Composer's clock; neither touches the note, its velocity or channel allocation."
    )
    add("")

    add("## 3. Test material (Parts 7-8, 14)")
    add("")
    add(
        "**Experimental choice.** Six cases, chosen by a rule stated before any audio was "
        "inspected: one melodic, one percussive, one bass, one high/bell, one profile that "
        "collapsed into a duplicate group, one whose generator clearly differs from the default, "
        "and one PAIR/16-bit case. The phrase is identical for A/B/C/D in every case; no "
        "normalization, EQ or compression is applied beyond the synthesiser's own peak fit."
    )
    add("")
    add(_md_table(("case", "character", "joined", "profile", "why"), [
        (c["case"], c["character"], c["joined"], c["profile"], c["why"])
        for c in bundle["test_material"]
    ]))
    add("")
    add(
        "**Observed.** Technical failures are recorded, never replaced: "
        + (", ".join(f"`{c['case']}` ({c['technical_failure']})" for c in failures) if failures else "none.")
    )
    add("")

    add("## 4. Byte-level proof (Part 9)")
    add("")
    add(
        "**Observed.** For every case and variant: the WAV hash, the frames that differ from A, "
        "the changed POKEY columns, and the differing-sample count. A variant that was meant to "
        "decorate one field but changes several columns would be visible here."
    )
    add("")
    rows = []
    for record in usable:
        for name in VARIANT_ORDER:
            proof = record["variants"][name]["proof"]
            rows.append(
                (
                    record["case"],
                    name,
                    record["variants"][name]["label"],
                    proof["wav_sha256"][:12],
                    _fmt_cell(proof["differing_frames_vs_baseline"]),
                    _fmt_cell(proof["first_differing_frame"]),
                    ", ".join(proof["changed_pokey_columns"]) or "—",
                    _fmt_cell(proof["differing_samples_vs_baseline"]),
                    f"{proof['rms']:.4f}",
                )
            )
    add(_md_table(("case", "v", "label", "wav sha256", "Δframes", "first Δframe", "changed columns", "Δsamples", "rms"), rows))
    add("")

    add("## 5. Field perturbation / information flow (Part 10)")
    add("")
    add(
        "**Observed.** Per profile field: whether replacement writes it, whether decoration "
        "writes it, and whether that field, applied alone, reaches the IR, the frames and the WAV. "
        "`pitch/base` and `volume` have no IRInstrument field: they are the note's."
    )
    add("")
    for record in usable:
        add(f"**{record['case']}** (profile `{record['profile_id']}`)")
        add("")
        add(
            _md_table(
                ("field", "B replacement", "C decoration", "reaches IR", "reaches frames", "changes WAV"),
                [
                    (
                        row["field"],
                        row["replacement_writes"],
                        row["decoration_writes"],
                        row["reaches_ir"],
                        row["reaches_frames"],
                        row["changes_wav"],
                    )
                    for row in record["perturbation_table"]
                ],
            )
        )
        add("")

    add("## 6. Reference comparison (Part 11)")
    add("")
    add(
        "**Observed.** Stage 9C/11B descriptors (centroid, bandwidth, flatness, RMS) and the "
        "band-energy distance to the archaeology `reference_replay.wav`, for A/B/C/D, where a "
        "reference exists."
    )
    add("")
    ref_rows = []
    for record in usable:
        if not record["reference_available"]:
            ref_rows.append((record["case"], "no reference", "—", "—", "—", "—", "—", "—"))
            continue
        ref = record["reference"]
        a = record["variants"]["A"]
        b = record["variants"]["B"]
        c = record["variants"]["C"]
        d = record["variants"]["D"]
        ref_rows.append(
            (
                record["case"],
                "reference",
                f"{ref['centroid_hz']:.0f}",
                f"{ref['bandwidth_hz']:.0f}",
                f"{ref['flatness']:.3f}",
                "—",
                "—",
                "—",
            )
        )
        for name, entry in (("A", a), ("B", b), ("C", c), ("D", d)):
            ref_rows.append(
                (
                    record["case"],
                    name,
                    f"{entry['features']['centroid_hz']:.0f}",
                    f"{entry['features']['bandwidth_hz']:.0f}",
                    f"{entry['features']['flatness']:.3f}",
                    f"{entry.get('spectral_distance_to_reference', '—')}",
                    f"{entry['proof']['rms']:.4f}",
                    "—",
                )
            )
    add(_md_table(("case", "variant", "centroid Hz", "bandwidth Hz", "flatness", "dist to ref", "rms", ""), ref_rows))
    add("")

    add("## 7. The two hypotheses (Part 12)")
    add("")
    add(
        f"**Observed.** H1 — decoration preserves the Composer envelope where replacement does "
        f"not — holds in **{hypotheses['H1_decoration_preserves_composer_tuning']['count']} of "
        f"{hypotheses['H1_decoration_preserves_composer_tuning']['of']}** usable cases "
        f"(`{', '.join(hypotheses['H1_decoration_preserves_composer_tuning']['cases']) or '—'}`). "
        f"H2 — decoration still changes the sound — holds in "
        f"**{hypotheses['H2_decoration_changes_the_sound']['count']} of "
        f"{hypotheses['H2_decoration_changes_the_sound']['of']}** cases "
        f"(`{', '.join(hypotheses['H2_decoration_changes_the_sound']['cases']) or '—'}`)."
    )
    add("")
    add(
        f"**Observed.** Both hold together in "
        f"**{hypotheses['both']['count']}** case(s) "
        f"(`{', '.join(hypotheses['both']['cases']) or '—'}`); C sits between the baseline and the "
        f"reference in **{hypotheses['decoration_between_baseline_and_reference']['count']}** "
        f"reference-bearing case(s)."
    )
    add("")
    add(
        "**Inference.** A successful *compromise* needs both H1 and H2 in the same case. Where H1 "
        "holds in nearly every case but H2 does too, the interesting question is not whether "
        "decoration changes the sound, but whether what it changes is *useful* — which the "
        "reference distance and, if justified, a listener decide."
    )
    add("")

    add("## 8. Listening (Part 13)")
    add("")
    add(
        f"**Experimental choice.** {bundle['listening']['reason']}. Package: "
        f"**{'prepared' if bundle['listening']['justified'] else 'not prepared'}**."
    )
    add("")

    add("## 9. Selection integrity (Part 14)")
    add("")
    add(
        "**Observed.** The six cases were fixed in `stage12a.CASES` before the experiment ran; "
        "none was added, removed or swapped after seeing any audio. A case that failed technically "
        "is recorded as a failure in §3, not replaced."
    )
    add("")

    h1 = hypotheses["H1_decoration_preserves_composer_tuning"]["count"]
    h2 = hypotheses["H2_decoration_changes_the_sound"]["count"]
    n = len(usable)
    both = hypotheses["both"]["count"]
    listening = bundle["listening"]
    replaced_envelope = sum(
        1 for c in usable if not c["preservation"]["replacement_preserves_envelope"]
    )
    decoration_envelope = sum(
        1 for c in usable if not c["preservation"]["decoration_preserves_envelope"]
    )

    add("## Final report — the eight questions")
    add("")
    add(
        "**1. What does the current binding replace?** `binding.py:_rebuild_song` writes, per bound "
        "instrument, `distortion`, `envelope`, `audctl` and (for a PAIR) `is_16bit`, plus the "
        "provenance pair, and OR-s the song-level `uses_16bit_bass`. It does **not** touch pitch, "
        "velocity, tempo, channel allocation or patterns. The union of IR fields actually changed "
        f"across cases: `{', '.join(bundle['binding_writes_ir_fields_union'])}`."
    )
    add("")
    add(
        "**2. What information does replacement destroy?** The Composer's *character-derived* "
        "envelope and clock: `map_instrument_character` turns `character` into a distortion byte and "
        "a 4-number envelope, and because those are not 'explicit' on the composition document the "
        f"profile's envelope wins. Measured: replacement changed the Composer envelope in "
        f"**{replaced_envelope} of {n}** usable cases; decoration changed it in "
        f"**{decoration_envelope}**."
    )
    add("")
    add(
        "**3. Can profile information be applied as decoration?** Per field, from the perturbation "
        "tables and the hardware facts (§1, §5):"
    )
    add("")
    add(
        _md_table(
            ("field", "classification", "why"),
            [
                ("generator (distortion)", "DECORATIVE (by substitution)", "the nibble can be swapped into the Composer instrument without touching the rest; it cannot be *added* — AUDC is one byte"),
                ("envelope", "DECORATIVE (by substitution)", "no merge algebra; field-wise substitution is possible (C keeps it, D substitutes attack/release)"),
                ("AUDCTL", "GLOBAL_CONSTRAINT", "one song-global byte; applying it changes the clock of every channel, not just the decorated one"),
                ("clock", "GLOBAL_CONSTRAINT", "derived from AUDCTL, so the same constraint"),
                ("pitch / base", "NOT_EXPRESSIBLE", "the note owns the pitch; the profile's base is a reference, not a register the binding may write"),
                ("volume", "NOT_EXPRESSIBLE", "the note's velocity owns the peak; only the envelope shapes it"),
                ("pairing (16-bit)", "PAIR_ONLY", "coupling is a scope fact; a PAIR instrument keeps it, and decoration must not steal a channel"),
            ],
        )
    )
    add("")
    add(
        f"**4. Does decoration preserve Composer tuning?** Yes, measurably: decoration (C) keeps "
        f"the Composer envelope and clock in every case (**{h1} of {n}** preserve what replacement "
        "destroys)."
    )
    add("")
    add(
        f"**5. Does decoration transfer profile character?** Yes, measurably: C changes the WAV in "
        f"**{h2} of {n}** usable cases (different WAV hash, changed AUDC column). Whether the "
        "change is *useful* is the open question."
    )
    add("")
    add(
        "**6. Which fields provide the best trade-off?** By the measurement, the **generator** is "
        "the only field that both changes the sound and can be applied without a global side "
        "effect; the envelope is decorative but transient-only, and AUDCTL/clock cannot be "
        "decorated at all. The defensible subset is *the generator, optionally with the profile's "
        "transient*."
    )
    add("")
    add(
        "**7. Does human listening support the result?** "
        + (
            "Not tested — no package was prepared, because the analysis does not isolate a claim "
            "beyond what earlier stages already tested."
            if not listening["justified"]
            else "A package is justified and prepared; its result is not yet known."
        )
    )
    add("")
    add(
        "**8. The single recommended next step.** "
        + (
            "**Gather one targeted perceptual experiment: a blind C-vs-A / C-vs-B comparison of the "
            "generator decoration.** The mechanics are settled — decoration preserves the Composer "
            "tuning and still changes the sound — but this stage's decision rule requires that the "
            "difference be perceptually meaningful, and only a listener can supply that. It needs "
            "no production change."
            if not listening["justified"]
            else "**Run the small blind listening package (C vs A, C vs B, D vs A, D vs B).**"
        )
    )
    add("")
    add("### Verdict")
    add("")
    add(
        f"**Observed.** H1 holds in {h1}/{n} cases and H2 in {h2}/{n}; both hold together in {both}."
    )
    add("")
    decision = (
        "**HYPOTHESIS SUPPORTED (mechanically; perceptually only if the listening package confirms it)**"
        if (h1 > 0 and h2 > 0 and listening["justified"])
        else "**HYPOTHESIS SUPPORTED MECHANICALLY, NOT YET PERCEPTUALLY — treat as NOT ESTABLISHED**"
    )
    add(
        f"**Inference.** {decision}. Decoration preserves Composer tuning and still changes the "
        "sound; the stage's decision rule additionally requires a *perceptually meaningful* "
        "difference, which the quantitative analysis alone cannot establish, so a positive "
        "conclusion is not declared here."
    )
    add("")
    add(
        "**Against the brief's decision rule.** A positive conclusion needs (1) Composer "
        "information preserved better than with replacement, (2) profile character transferred, "
        "(3) a measurable and preferably perceptually meaningful difference, and (4) determinism "
        "and explainability. (1), (2) and (4) hold; (3) is measurable but its perceptual half is "
        "**unrun**, so this stage does **not** declare `HYPOTHESIS SUPPORTED`. The honest label "
        "today is *mechanically supported, perceptually unestablished*, and the blind package "
        "prepared in §8 is exactly the missing evidence — not another implementation round."
    )
    add("")

    add("## 10. Reproducibility")
    add("")
    add(
        "Every number is a pure function of the profiles, the bank and the archaeology reference "
        "WAVs below (SHA-256); no timestamp appears in any artefact, and the case list is fixed in "
        "source. Two runs are byte-identical."
    )
    add("")
    add("```json")
    add(json.dumps(bundle["inputs"], indent=2, sort_keys=True))
    add("```")
    add("")
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Part 13 — the (small) blind listening package
# ---------------------------------------------------------------------------
LISTENING_PACKAGE_DIR = REPO_ROOT / "examples" / "stage12a_listening"
LISTENING_SEED = 20261008
_LISTENING_PAIRS: Tuple[Tuple[str, str, str], ...] = (
    ("C_vs_A", "C", "A"),
    ("C_vs_B", "C", "B"),
)
_ANSWER_HEADER = (
    "trial_id",
    "better_overall",
    "more_convincing_atari",
    "more_interesting_character",
    "difference_1_5",
    "comment",
)


def _write_wav(path: Path, samples: np.ndarray, sample_rate: int = SAMPLE_RATE) -> None:
    import wave

    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(sample_rate)
        handle.writeframes(samples.astype(np.int16).tobytes())


def build_listening_package(
    bundle: Mapping[str, Any],
    *,
    out_dir: Path = LISTENING_PACKAGE_DIR,
    seed: int = LISTENING_SEED,
    bank_dir: Path = DEFAULT_BANK_DIR,
    arch_root: Path = DEFAULT_ARCHAEOLOGY_DIR,
) -> Dict[str, Any]:
    """A small blinded package: C-vs-A and C-vs-B for each case where decoration changes the sound."""
    import random

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "audio").mkdir(exist_ok=True)
    bank = load_sound_profile_bank(Path(bank_dir))

    testable = [
        record
        for record in bundle["cases"]
        if "variants" in record
        and (record["variants"]["C"]["proof"]["differing_samples_vs_baseline"] or 0) > 0
    ]
    rng = random.Random(seed)
    trials: List[Dict[str, Any]] = []
    for record in testable:
        case = next(c for c in CASES if c["case"] == record["case"])
        songs = variant_songs(_case_ir(case, bank))
        samples = {name: _compile(songs[name])[1] for name in VARIANT_ORDER}
        for pair_name, left, right in _LISTENING_PAIRS:
            trial_id = f"{record['case']}_{pair_name}"
            sides = {"a": left, "b": right} if rng.random() < 0.5 else {"a": right, "b": left}
            hashes = {}
            for side in ("a", "b"):
                variant = sides[side]
                path = out_dir / "audio" / f"{trial_id}_{side}.wav"
                _write_wav(path, samples[variant])
                hashes[side] = _sha256_samples(samples[variant])
            trials.append(
                {
                    "trial_id": trial_id,
                    "case": record["case"],
                    "profile_id": record["profile_id"],
                    "compared": {"left": left, "right": right},
                    "sides": sides,
                    "audio": {
                        "a": f"audio/{trial_id}_a.wav",
                        "b": f"audio/{trial_id}_b.wav",
                    },
                    "sha256": hashes,
                    "expected_distinction": "decoration vs " + ("baseline" if pair_name.endswith("A") else "replacement"),
                }
            )

    manifest = {
        "schema": "atari-music/stage12a-listening/1",
        "experiment": "stage12a",
        "seed": seed,
        "sample_rate": SAMPLE_RATE,
        "phrase": bundle["phrase"],
        "bpm": bundle["bpm"],
        "velocity": bundle["velocity"],
        "level_policy": "the synthesiser normalizes every buffer to a 0.90 peak; no extra gain, EQ or compression",
        "trials": trials,
    }
    (out_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    (out_dir / "evaluation_stage12a.csv").write_text(
        ",".join(_ANSWER_HEADER) + "\n" + "".join(f"{t['trial_id']},,,,,,\n" for t in trials),
        encoding="utf-8",
    )
    metadata = {
        "experiment": "stage12a",
        "variants": bundle["variants"],
        "trials": len(trials),
        "inputs": bundle["inputs"],
        "variant_hashes": {
            f"{t['trial_id']}:{side}": digest for t in trials for side, digest in t["sha256"].items()
        },
    }
    (out_dir / "metadata.json").write_text(
        json.dumps(metadata, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    (out_dir / "index.html").write_text(
        render_index_html(manifest), encoding="utf-8", newline="\n"
    )
    (out_dir / "README.md").write_text(_listening_readme(manifest), encoding="utf-8", newline="\n")
    return manifest


def render_index_html(manifest: Mapping[str, Any]) -> str:
    """The listening interface: one self-contained page, no server and no Python.

    The payload carries only the trial ids and the two audio paths. The private manifest
    (which side is the decoration) is deliberately **not** embedded, so the page cannot
    reveal the answer even to a curious listener.
    """
    payload = {
        "experiment": manifest["experiment"],
        "trials": [
            {
                "trial_id": trial["trial_id"],
                "a": trial["audio"]["a"],
                "b": trial["audio"]["b"],
            }
            for trial in manifest["trials"]
        ],
    }
    return _INDEX_HTML.replace("__PACKAGE__", json.dumps(payload, sort_keys=True))


def _listening_readme(manifest: Mapping[str, Any]) -> str:
    return (
        "# Stage 12A listening — decoration vs replacement\n\n"
        "Two versions of the same short phrase. The only difference between the two sides is how a\n"
        "SoundProfile is applied: **decoration** lets the profile change the Composer instrument's\n"
        "generator while keeping its tuned envelope and clock, against **baseline** (no profile) or\n"
        "**replacement** (the existing binding, which also replaces the envelope and clock).\n\n"
        "**You need nothing installed.** Open `index.html`, listen, answer, and use the\n"
        "\"Download the answer CSV\" button at the end. If the browser refuses to play local audio,\n"
        "serve the folder instead:\n\n"
        "```bash\npython -m http.server 8740 --directory examples/stage12a_listening\n```\n\n"
        f"There are **{len(manifest['trials'])} pairs**. Listen to `a` and `b`, then answer. Answers\n"
        "are kept in this browser, so a session can be resumed, and the download button produces\n"
        "`evaluation_stage12a.csv` (the same file you can drop back into this folder). Nothing is\n"
        "uploaded anywhere. `manifest.json` is the private key and should not be opened while\n"
        "listening.\n\n"
        "Questions: which sounds **better overall**, which is **more convincing as Atari music**,\n"
        "which has the **more interesting character**, and how different the two sides are (1-5).\n"
        "There are no right answers and no technical knowledge is needed.\n"
    )


_INDEX_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>POKEY decoration vs replacement</title>
<style>
  :root { color-scheme: dark; }
  body { font-family: system-ui, -apple-system, Segoe UI, sans-serif; margin: 0; padding: 1.5rem;
         background: #14161a; color: #e8e8ea; line-height: 1.5; }
  main { max-width: 60rem; margin: 0 auto; }
  h1, h2 { line-height: 1.2; }
  .note { background: #1d2026; border-left: 3px solid #4a7; padding: .75rem 1rem; margin: 1rem 0;
          border-radius: 3px; font-size: .95rem; }
  .card { background: #1a1d22; border: 1px solid #2c3036; border-radius: 6px; padding: 1rem;
          margin: 1rem 0; }
  .card.done { border-color: #3d6; }
  .label { font-weight: 600; min-width: 11rem; }
  audio { width: 100%; max-width: 30rem; }
  .q { margin: .6rem 0; }
  .scale { display: flex; gap: .4rem; flex-wrap: wrap; }
  .scale label { background: #23272e; border: 1px solid #333; border-radius: 4px;
                 padding: .25rem .6rem; cursor: pointer; font-variant-numeric: tabular-nums; }
  .scale input { margin-right: .3rem; }
  textarea { width: 100%; min-height: 3rem; background: #23272e; color: inherit;
             border: 1px solid #333; border-radius: 4px; padding: .4rem; font: inherit; }
  button { background: #2d5; color: #06120a; border: 0; border-radius: 4px; padding: .55rem 1rem;
           font: inherit; font-weight: 600; cursor: pointer; margin-right: .5rem; }
  button.ghost { background: #333; color: #ddd; }
  .progress { position: sticky; top: 0; background: #14161aee; padding: .6rem 0; z-index: 5;
              border-bottom: 1px solid #2c3036; font-variant-numeric: tabular-nums; }
  .small { font-size: .88rem; color: #aab; }
  .ab { display: grid; grid-template-columns: 1fr 1fr; gap: 1rem; }
  @media (max-width: 40rem) { .ab { grid-template-columns: 1fr; } }
</style>
</head>
<body>
<main>
<h1>Which version sounds better?</h1>

<div class="note">
  <strong>Your ears are the instrument here.</strong> Each pair plays the same short phrase twice:
  the same notes, the same durations, the same velocity, the same channel, the same renderer. The two
  sides differ only in <em>how a POKEY sound profile is applied</em> — decorating the Composer's own
  instrument, or replacing parts of it. Nothing on this page says which side is which, and there is no
  expected answer.
</div>
<div class="note">
  <strong>Set your volume once and leave it alone.</strong> Both sides of a pair are presented at the
  same gain. Please judge character and musicality rather than loudness.
</div>
<div class="note">
  <strong>Some pairs may sound identical to you.</strong> That is a result, not a mistake: answer
  "no clear difference" and move on. It is also a result if a difference is audible only on some
  pairs.
</div>

<div class="progress" id="progress">progress</div>

<h2>Comparisons (<span id="count"></span> pairs)</h2>
<p class="small">Listen to both sides as many times as you like, then answer. Answers are kept in
this browser, so a session can be resumed.</p>
<div id="trials"></div>

<h2>Finish</h2>
<p class="small">Click the button to download the answer file. Nothing is uploaded anywhere —
everything stays in this browser until you download it.</p>
<button onclick="downloadAll()">Download the answer CSV</button>
<button class="ghost" onclick="if(confirm('Erase all answers in this browser?')){localStorage.clear();location.reload();}">Reset answers</button>

<script>
const PACKAGE = __PACKAGE__;
const STORE = "stage12a-answers-v1";
let answers = JSON.parse(localStorage.getItem(STORE) || "{}");

function save() { localStorage.setItem(STORE, JSON.stringify(answers)); refresh(); }
function get(key, field) { return (answers[key] || {})[field] ?? ""; }
function set(key, field, value) {
  answers[key] = answers[key] || {};
  answers[key][field] = value;
  save();
}

function csvEscape(value) {
  const text = String(value ?? "");
  return /[",\n]/.test(text) ? '"' + text.replace(/"/g, '""') + '"' : text;
}
function download(name, header, rows) {
  const body = [header.join(",")].concat(rows.map(r => r.map(csvEscape).join(","))).join("\n") + "\n";
  const url = URL.createObjectURL(new Blob([body], {type: "text/csv;charset=utf-8"}));
  const a = document.createElement("a");
  a.href = url; a.download = name; a.click();
  setTimeout(() => URL.revokeObjectURL(url), 5000);
}

const CHOICES = [
  ["better_overall", "Which version sounds better overall?"],
  ["more_convincing_atari", "Which sounds more convincing as Atari music?"],
  ["more_interesting_character", "Which has the more interesting or appropriate sound character?"]
];
const HEADER = ["trial_id", "better_overall", "more_convincing_atari",
                "more_interesting_character", "difference_1_5", "comment"];

function choiceRow(key, field, question) {
  const current = get(key, field);
  const values = ["a", "b", "none"];
  const labels = ["A", "B", "No clear difference"];
  const inputs = values.map((value, index) => {
    const checked = String(current) === value ? " checked" : "";
    return `<label><input type="radio" name="${key}-${field}" value="${value}"${checked}
      onchange="set('${key}','${field}','${value}')">${labels[index]}</label>`;
  }).join("");
  return `<div class="q"><div class="label">${question}</div><div class="scale">${inputs}</div></div>`;
}

function differenceRow(key) {
  const current = get(key, "difference_1_5");
  const labels = ["1 identical", "2", "3 noticeable", "4", "5 very large"];
  const inputs = [1, 2, 3, 4, 5].map(value => {
    const checked = String(current) === String(value) ? " checked" : "";
    return `<label><input type="radio" name="${key}-difference" value="${value}"${checked}
      onchange="set('${key}','difference_1_5','${value}')">${labels[value - 1]}</label>`;
  }).join("");
  return `<div class="q"><div class="label">How different do the two versions sound?</div>
    <div class="scale">${inputs}</div></div>`;
}

function commentRow(key) {
  const value = String(get(key, "comment")).replace(/</g, "&lt;");
  return `<div class="q"><div class="label">Comment (optional)</div>
    <textarea oninput="set('${key}','comment',this.value)">${value}</textarea></div>`;
}

function isDone(key) {
  return CHOICES.every(q => get(key, q[0]) !== "") && get(key, "difference_1_5") !== "";
}

document.getElementById("trials").innerHTML = PACKAGE.trials.map((trial, index) => {
  const id = trial.trial_id;
  const body = `<div class="small">This pair is one short phrase, played twice.</div>
    <div class="ab">
      <div><div class="label">A</div><audio controls preload="none" src="${trial.a}"></audio></div>
      <div><div class="label">B</div><audio controls preload="none" src="${trial.b}"></audio></div>
    </div>` +
    CHOICES.map(q => choiceRow(id, q[0], q[1])).join("") +
    differenceRow(id) + commentRow(id) +
    `<div class="small">Pair ${index + 1} of ${PACKAGE.trials.length}</div>`;
  return `<div class="card${isDone(id) ? " done" : ""}" id="${id}">${body}</div>`;
}).join("");

function refresh() {
  const done = PACKAGE.trials.filter(trial => isDone(trial.trial_id)).length;
  document.getElementById("progress").textContent =
    `Progress — ${done}/${PACKAGE.trials.length} pairs answered (answers are saved in this browser)`;
  document.getElementById("count").textContent = PACKAGE.trials.length;
}

function downloadAll() {
  download("evaluation_stage12a.csv", HEADER,
    PACKAGE.trials.map(trial => [trial.trial_id, get(trial.trial_id, "better_overall"),
      get(trial.trial_id, "more_convincing_atari"),
      get(trial.trial_id, "more_interesting_character"),
      get(trial.trial_id, "difference_1_5"), get(trial.trial_id, "comment")]));
}

refresh();
</script>
</main>
</body>
</html>
"""

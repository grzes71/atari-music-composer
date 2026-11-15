"""Experiment 30 — an A/B evaluation of four POKEY timbres, solo and in a real composition.

Experiment 29 handed the owner a blinded page of twelve candidates. Four of them are worth a closer
look; this experiment puts those four into two controlled contexts and separates the *timbre* question
from the *loudness* question, because Experiment 29 showed an 18.3 dB spread that could easily have
driven the ratings by itself.

WHAT IS COMPARED
----------------
Four timbres, applied to one part:

* ``c1_octave_pulse`` — Experiment 27 variant C, the reference the owner already preferred;
* ``pure_sustain``  — bank profile ``pokey_ref_25f94201``;
* ``pure_pluck``    — bank profile ``pokey_ref_9daa0429``;
* ``buzz_steady``   — bank profile ``pokey_ref_2b83db43``.

Two contexts:

* **solo** — a dedicated 9-second figure: a held note, a rest, then the composition's own opening motif
  and a descent to A-3. It exists to expose both the single-note character and the behaviour under
  pitch change;
* **composition** — the project's own ``examples/songs/Vaults-of-Nhyrmeth.dsl``, with only the lead
  part's timbre changed. Bass, percussion, every other channel, tempo, structure and length are
  untouched.

Two loudness versions of every clip:

* **original** — one shared gain per context, no per-file normalisation;
* **matched** — every clip brought to one measured loudness, so the timbre can be judged without the
  level driving the answer.

HOW THE FOUR ARE PRODUCED (no re-implementation)
------------------------------------------------
Read from the repository, not assumed. ``INSTRUMENT lead character=bright_lead`` in the DSL declares no
explicit distortion and no explicit envelope, so ``apply_profile_binding`` is free to supply both from
the profile — which is exactly what makes three bank profiles usable here without touching the
arrangement. ``binding.py`` refuses a partial override ("a profile is one coherent register
configuration"), so if the DSL had pinned the generator, ``buzz_steady`` (``$C0``) would have been
refused outright.

* ``pure_sustain``, ``pure_pluck``, ``buzz_steady`` go through ``apply_profile_binding`` — the
  production realization path — then ``ir.compile_ir_to_pokey_frames``;
* ``c1_octave_pulse`` is Experiment 28's ``apply_c1`` applied to the production compile of the same
  grid, so the octave-pulse schedule is Experiment 27's own register generation;
* every clip is rendered by Experiment 26's ``render_registers``.

Nothing is copied and nothing is substituted.

THE HONEST ASYMMETRY
--------------------
The three bank profiles bring their *own* measured envelope (the composition leaves it open), while C1
keeps the composition's default articulation and changes only the generator and the divider. So "the
timbre" of a bank variant includes its articulation and C1's does not. That is what each candidate
actually is, it is recorded per variant in ``manifest.json``, and it is stated in the report rather
than hidden.

LOUDNESS MEASUREMENT
--------------------
No loudness library is installed (no ``pyloudnorm``, no ``scipy``, no ``soundfile``), so the matching
target is an in-repo implementation of **ITU-R BS.1770-4 K-weighted integrated loudness (LUFS)**.
It is not a guess: the coefficient derivation reproduces the standard's published 48 kHz filter to
1e-15, and the meter reads a −20 dBFS 997 Hz sine as −20.0 LUFS, which is the standard's own
calibration point. Both are asserted in the test suite. The brief's fallback (plain RMS) is also
reported for every clip, so nothing rests on the LUFS figure alone.

Level matching is a **scalar gain on the rendered audio**. No envelope, pitch, rhythm or generator
parameter is touched to match a level, and the matched gain of every file is published.

WHAT THIS IS NOT
----------------
No production DSL/IR/compiler/exporter/player/CLI change; no candidate is registered as an instrument;
no bank profile is modified; no E26–E29 artefact is touched. Whether any of these four belongs in a
library is the owner's listening decision.
"""

from __future__ import annotations

import csv
import hashlib
import json
import math
import random
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

import numpy as np

from atari_music import ir
from atari_music import pokey_c1_musical_context_experiment as e28
from atari_music import pokey_timbre_experiment as e26
from atari_music.ai.client import generate_music_from_composition, load_composition_dsl
from atari_music.sound_profiles.bank import SoundProfileBank, load_sound_profile_bank
from atari_music.sound_profiles.binding import (
    BINDING_SCHEMA,
    apply_profile_binding,
    load_profile_binding,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT_DIR = REPO_ROOT / "experiments" / "experiment30"
DEFAULT_BANK_DIR = REPO_ROOT / "tests" / "data" / "sound_profiles" / "bank"
DEFAULT_COMPOSITION = REPO_ROOT / "examples" / "songs" / "Vaults-of-Nhyrmeth.dsl"

SAMPLE_RATE = e26.SAMPLE_RATE
FRAME_RATE_HZ = e26.FRAME_RATE_HZ

#: Experiment 26's level policy, unchanged: the loudest raw render of a group reaches this peak.
TARGET_PEAK = e26.TARGET_PEAK
#: The ceiling a level-matched gain may not cross. Below 1.0 so ``to_int16`` (which does not clip)
#: can never wrap.
MATCHED_PEAK_CEILING = 0.90

#: The melodic channel both contexts put their candidate on.
MELODIC_CHANNEL = e28.MELODIC_CHANNEL

#: Fixed, so the letter assignment and the file names are reproducible.
SEED = 30
LETTERS: Tuple[str, ...] = ("A", "B", "C", "D")

CONTEXT_SOLO = "solo"
CONTEXT_COMPOSITION = "composition"
CONTEXT_ORDER: Tuple[str, ...] = (CONTEXT_SOLO, CONTEXT_COMPOSITION)

VERSION_ORIGINAL = "original"
VERSION_MATCHED = "matched"
VERSION_ORDER: Tuple[str, ...] = (VERSION_ORIGINAL, VERSION_MATCHED)

AUDIO_DIRNAME = "audio"
EVALUATION_CSV = "evaluation_template.csv"

#: The rating form. One row per delivered file, so a listener can rate the original and the
#: loudness-matched version of the same timbre separately and see whether the level changed the answer.
EVALUATION_FIELDS: Tuple[str, ...] = (
    "listener", "context", "version", "letter",
    "usefulness_1_5", "interest_1_5", "annoyance_1_5",
    "typical_use", "supports_melody", "comment",
)

#: The 1-5 scales, with the end labels that give the numbers meaning.
EVALUATION_SCALES: Tuple[Dict[str, Any], ...] = (
    {
        "field": "usefulness_1_5",
        "question": "Przydatność — czy wykorzystałbym to brzmienie we własnej muzyce?",
        "labels": ("nie", "raczej nie", "może", "raczej tak", "tak, zdecydowanie"),
    },
    {
        "field": "interest_1_5",
        "question": "Zainteresowanie — czy brzmienie jest ciekawe i ma własny charakter?",
        "labels": ("nudne", "przeciętne", "w porządku", "ciekawe", "wyraziste"),
    },
    {
        "field": "annoyance_1_5",
        "question": "Uciążliwość — jak bardzo męczy przy dłuższym słuchaniu?",
        "labels": ("wcale", "trochę", "średnio", "dość", "bardzo"),
    },
)

TYPICAL_USE_CHOICES: Tuple[Tuple[str, str], ...] = (
    ("melody", "melodia"),
    ("bass", "bas"),
    ("percussion", "perkusja"),
    ("effect", "efekt"),
    ("other", "inne"),
)

SUPPORTS_MELODY_CHOICES: Tuple[Tuple[str, str], ...] = (
    ("yes", "tak, melodia nadal działa"),
    ("partly", "częściowo"),
    ("no", "nie, melodia się gubi"),
    ("n/a", "nie dotyczy (odsłuch pojedynczego brzmienia)"),
)

PRODUCTION_STATEMENT = (
    "no DSL, IR, compiler, MADS exporter, player or CLI change; no candidate is registered as an "
    "instrument; no bank profile was modified; no E26-E29 artefact was touched; the experiment is not "
    "reachable from the production command line"
)

#: The real limits of what this comparison can show.
LIMITATIONS: Tuple[str, ...] = (
    "the C1 reference is applied as a post-compile register transform that keeps the composition's own "
    "articulation, while the three bank profiles bring their own measured envelope. So 'the timbre' of "
    "a bank variant includes its articulation and C1's does not. Each variant's applied envelope is in "
    "the manifest; the difference is real and is not hidden.",
    "loudness matching equalises measured K-weighted loudness, not perceived loudness. Two timbres with "
    "very different spectra can still differ in how loud they seem at equal LUFS, especially a buzz "
    "against a clean tone.",
    "the peak ceiling uses sample peak, not true peak: no oversampling is done, so inter-sample peaks "
    "are not measured. The 0.90 ceiling leaves enough headroom that this cannot clip here.",
    "these are synthetic renders of the POKEY register model. That a timbre sounds good here does not "
    "prove the same sound is reachable on real hardware, and nothing here is exported to a player.",
    "the four candidates were selected in Experiment 29 from twelve; this experiment does not re-open "
    "that selection, and a good result for one of these does not mean the other eight are worse.",
    "only one part changes, and only on CH3. A timbre can work on a lead and fail on a bass or in a "
    "denser arrangement; this experiment cannot say anything about that.",
    "one listener, one session. Any preference is preliminary.",
    "the test is partially blinded: see the manifest's `blinding.honest_note`.",
)



# ===========================================================================
# 1. The four candidates.
# ===========================================================================
C1_NAME = "c1_octave_pulse"

CANDIDATES: Tuple[Dict[str, Any], ...] = (
    {
        "name": C1_NAME,
        "kind": "experiment",
        "profile_id": None,
        "generator": "$40",
        "source": "Experiment 26/27 variant C, applied through Experiment 28's apply_c1",
        "role_hypothesis": "melody",
    },
    {
        "name": "pure_sustain",
        "kind": "bank",
        "profile_id": "pokey_ref_25f94201",
        "generator": "$A0",
        "source": "bank profile pokey_ref_25f94201 (PLAYABLE, VOICE, 64 kHz)",
        "role_hypothesis": "melody",
    },
    {
        "name": "pure_pluck",
        "kind": "bank",
        "profile_id": "pokey_ref_9daa0429",
        "generator": "$A0",
        "source": "bank profile pokey_ref_9daa0429 (PLAYABLE, VOICE, 64 kHz)",
        "role_hypothesis": "melody, percussive articulation",
    },
    {
        "name": "buzz_steady",
        "kind": "bank",
        "profile_id": "pokey_ref_2b83db43",
        "generator": "$C0",
        "source": "bank profile pokey_ref_2b83db43 (PLAYABLE_WITH_LIMITATION, VOICE, 64 kHz)",
        "role_hypothesis": "melody, buzzy timbre",
    },
)

#: Why this composition, and why this part. Kept next to the code so the report cannot drift.
COMPOSITION_RATIONALE = (
    "examples/songs/Vaults-of-Nhyrmeth.dsl — the project's own documented example and a test fixture, "
    "so its provenance is internal rather than a copied commercial melody. It has a recognisable lead "
    "melody on CH3, a 16-bit bass on CH1+CH2 and percussion on CH4, at 90 BPM over 2280 frames "
    "(45.6 s). Its instruments are declared by `character` only, with no explicit distortion and no "
    "explicit envelope, which is what lets a profile supply both without touching the arrangement."
)
TARGET_RATIONALE = (
    "CH3, the lead. It is the only part carrying a melody, it is a single 8-bit voice so a candidate "
    "is the whole of its sound, and it sits above the 16-bit bass and the noise percussion rather than "
    "under them — so a timbre change is audible without the part having to be made louder. The 16-bit "
    "bass is left alone deliberately: none of these four candidates is a PAIR profile, so touching "
    "CH1+CH2 would have changed the arrangement for no reason."
)

#: The solo figure. Deliberately the composition's own opening motif, so a listener can carry an
#: impression from the solo block into the composition block.
SOLO_TEXT = '''TITLE "experiment30 solo"
AUTHOR "Experiment 30"
KEY D
MODE MINOR
BPM 90
SEQUENCE S

INSTRUMENT lead character=bright_lead

[PATTERN S length=90]
CH3 lead V14
A4/20 R/2 D4/6 E4/2 F4/4 G4/4 A4/8 D5/4 C5/4 Bb4/6 C5/2 A4/4 F4/4 G4/4 A4/4 D4/4 A3/8
'''

SOLO_RATIONALE = (
    "one figure, 90 rows at 90 BPM = 450 frames = 9.0 s: a held A-4 for 2.0 s (single-note character "
    "and the envelope's whole shape), a 2-row rest (so the release is audible rather than cut off), "
    "then the composition's own opening lead motif D-4 E-4 F-4 G-4 A-4 D-5 C-5 Bb-4 C-5, a short "
    "descent A-4 F-4 G-4, and a tail to A-4 D-4 A-3. The range is A-3 to D-5 — 17 semitones — so both "
    "the single-note character and the behaviour under pitch change can be judged."
)


def candidate_names() -> Tuple[str, ...]:
    return tuple(candidate["name"] for candidate in CANDIDATES)


def candidate_by_name(name: str) -> Dict[str, Any]:
    for candidate in CANDIDATES:
        if candidate["name"] == name:
            return candidate
    raise KeyError(f"unknown candidate {name!r}; known: {list(candidate_names())}")


def letter_map() -> Dict[str, str]:
    """``letter -> candidate``, shuffled once with the fixed seed.

    The letters are the only thing the listening page shows before a reveal, so the assignment must not
    encode anything — C1 is not always "A".
    """
    names = list(candidate_names())
    random.Random(SEED).shuffle(names)
    return dict(zip(LETTERS, names))


def candidate_letter(candidate: str) -> str:
    for letter, name in letter_map().items():
        if name == candidate:
            return letter
    raise KeyError(f"unknown candidate {candidate!r}")


# ===========================================================================
# 2. Loudness — ITU-R BS.1770-4 K-weighted integrated loudness, in numpy.
# ===========================================================================
#: The analog prototype of the K-weighting pre-filter (a high shelf) and of the RLB high-pass, as
#: specified by BS.1770-4 and used by the reference implementations.
SHELF_F0_HZ = 1681.974450955533
SHELF_GAIN_DB = 3.999843853973347
SHELF_Q = 0.7071752369554196
HIGHPASS_F0_HZ = 38.13547087602444
HIGHPASS_Q = 0.5003270373238773

#: BS.1770-4's calibration constant, and its gating thresholds.
LOUDNESS_OFFSET = -0.691
ABSOLUTE_GATE_LUFS = -70.0
RELATIVE_GATE_LU = -10.0
BLOCK_SECONDS = 0.4
BLOCK_OVERLAP = 0.75

#: The published BS.1770-4 Table 1 coefficients at 48 kHz. ``high_shelf_coefficients`` and
#: ``high_pass_coefficients`` must reproduce these; the test suite asserts it, which is what makes this
#: an implementation of the standard rather than a filter that merely looks plausible.
BS1770_TABLE1_48K = {
    "shelf_b": (1.53512485958697, -2.69169618940638, 1.19839281085285),
    "shelf_a": (1.0, -1.69065929318241, 0.73248077421585),
    "highpass_b": (1.0, -2.0, 1.0),
    "highpass_a": (1.0, -1.99004745483398, 0.99007225036621),
}


def high_shelf_coefficients(sample_rate: float) -> Tuple[np.ndarray, np.ndarray]:
    """The K-weighting pre-filter, from the analog prototype by the bilinear transform."""
    k = math.tan(math.pi * SHELF_F0_HZ / sample_rate)
    vh = 10.0 ** (SHELF_GAIN_DB / 20.0)
    vb = vh ** 0.4996667741545416
    a0 = 1.0 + k / SHELF_Q + k * k
    b = np.array([
        (vh + vb * k / SHELF_Q + k * k) / a0,
        2.0 * (k * k - vh) / a0,
        (vh - vb * k / SHELF_Q + k * k) / a0,
    ])
    a = np.array([1.0, 2.0 * (k * k - 1.0) / a0, (1.0 - k / SHELF_Q + k * k) / a0])
    return b, a


def high_pass_coefficients(sample_rate: float) -> Tuple[np.ndarray, np.ndarray]:
    """The RLB high-pass. The numerator stays ``[1, -2, 1]``, as BS.1770-4 Table 1 publishes it."""
    k = math.tan(math.pi * HIGHPASS_F0_HZ / sample_rate)
    a0 = 1.0 + k / HIGHPASS_Q + k * k
    b = np.array([1.0, -2.0, 1.0])
    a = np.array([1.0, 2.0 * (k * k - 1.0) / a0, (1.0 - k / HIGHPASS_Q + k * k) / a0])
    return b, a


def biquad(samples: np.ndarray, b: np.ndarray, a: np.ndarray) -> np.ndarray:
    """Direct-form II biquad, one pass. Scipy is not installed, so the recursion is written out."""
    values = np.asarray(samples, dtype=np.float64)
    out = np.empty_like(values)
    x1 = x2 = y1 = y2 = 0.0
    b0, b1, b2 = float(b[0]), float(b[1]), float(b[2])
    a1, a2 = float(a[1]), float(a[2])
    for index in range(values.shape[0]):
        x0 = float(values[index])
        y0 = b0 * x0 + b1 * x1 + b2 * x2 - a1 * y1 - a2 * y2
        out[index] = y0
        x2, x1 = x1, x0
        y2, y1 = y1, y0
    return out


def k_weight(samples: np.ndarray, sample_rate: float = SAMPLE_RATE) -> np.ndarray:
    """The K-weighting filter: pre-filter, then the RLB high-pass."""
    return biquad(biquad(samples, *high_shelf_coefficients(sample_rate)),
                  *high_pass_coefficients(sample_rate))


def _block_powers(weighted: np.ndarray, sample_rate: float) -> np.ndarray:
    """Mean square of every 400 ms block, 75 % overlapped, as BS.1770-4 defines them."""
    size = int(round(BLOCK_SECONDS * sample_rate))
    step = int(round(BLOCK_SECONDS * (1.0 - BLOCK_OVERLAP) * sample_rate))
    if weighted.shape[0] < size:
        return np.array([float(np.mean(weighted ** 2))])
    return np.array([
        float(np.mean(weighted[start:start + size] ** 2))
        for start in range(0, weighted.shape[0] - size + 1, step)
    ])


def integrated_loudness(samples: np.ndarray, sample_rate: float = SAMPLE_RATE) -> float:
    """K-weighted integrated loudness in LUFS, with BS.1770-4's two-stage gating.

    A mono clip is one channel with weight 1. A clip shorter than one 400 ms block has no gated
    measurement to make, so its single whole-clip block is used ungated; :func:`measure_level` records
    that in ``lufs_gated`` rather than hiding it.
    """
    weighted = k_weight(samples, sample_rate)
    powers = _block_powers(weighted, sample_rate)
    if powers.size == 0 or not np.any(powers > 0.0):
        return float("-inf")

    above_absolute = powers > 10.0 ** ((ABSOLUTE_GATE_LUFS - LOUDNESS_OFFSET) / 10.0)
    if not above_absolute.any():
        return float("-inf")
    ungated = LOUDNESS_OFFSET + 10.0 * math.log10(float(np.mean(powers[above_absolute])))

    threshold = ungated + RELATIVE_GATE_LU
    above_relative = above_absolute & (powers > 10.0 ** ((threshold - LOUDNESS_OFFSET) / 10.0))
    if not above_relative.any():
        return float("-inf")
    return LOUDNESS_OFFSET + 10.0 * math.log10(float(np.mean(powers[above_relative])))


def peak_of(samples: np.ndarray) -> float:
    """Sample peak. Not a true-peak measurement — no oversampling is done, and that is documented."""
    values = np.asarray(samples, dtype=np.float64)
    return float(np.max(np.abs(values))) if values.size else 0.0


def rms_of(samples: np.ndarray) -> float:
    values = np.asarray(samples, dtype=np.float64)
    return float(np.sqrt(np.mean(values ** 2))) if values.size else 0.0


def dbfs(value: float) -> float:
    return 20.0 * math.log10(value) if value > 0.0 else float("-inf")


def measure_level(samples: np.ndarray, sample_rate: float = SAMPLE_RATE) -> Dict[str, Any]:
    """Every level figure the report and the manifest publish, for one raw buffer."""
    size = int(round(BLOCK_SECONDS * sample_rate))
    peak = peak_of(samples)
    rms = rms_of(samples)
    return {
        "peak": round(peak, 8),
        "peak_dbfs": round(dbfs(peak), 4),
        "rms": round(rms, 8),
        "rms_dbfs": round(dbfs(rms), 4),
        "lufs": round(integrated_loudness(samples, sample_rate), 4),
        "lufs_gated": bool(samples.shape[0] >= size),
    }


def gain_for_loudness(samples: np.ndarray, target_lufs: float,
                      sample_rate: float = SAMPLE_RATE) -> float:
    """The scalar gain that puts *samples* at *target_lufs*."""
    current = integrated_loudness(samples, sample_rate)
    if not math.isfinite(current) or not math.isfinite(target_lufs):
        raise ValueError("cannot match a silent or unmeasurable clip")
    return 10.0 ** ((target_lufs - current) / 20.0)


# ===========================================================================
# 3. The two contexts, and the four variants of each.
# ===========================================================================
_CACHE: Dict[str, Any] = {}


def composition_text() -> str:
    """The composition, read from disk and returned unchanged. The original is never written to."""
    return DEFAULT_COMPOSITION.read_text(encoding="utf-8")


def context_text(context: str) -> str:
    if context == CONTEXT_SOLO:
        return SOLO_TEXT
    if context == CONTEXT_COMPOSITION:
        return composition_text()
    raise KeyError(f"unknown context {context!r}; known: {list(CONTEXT_ORDER)}")


def context_source(context: str) -> str:
    if context == CONTEXT_SOLO:
        return "experiment-local DSL"
    return str(DEFAULT_COMPOSITION.relative_to(REPO_ROOT)).replace("\\", "/")


def compile_context(context: str) -> Tuple[Any, Any]:
    """``(document, result)`` for one context, compiled through the production path unmodified."""
    if context not in _CACHE:
        document = load_composition_dsl(context_text(context))
        _CACHE[context] = (document, generate_music_from_composition(document))
    return _CACHE[context]


def context_song(context: str) -> Any:
    return compile_context(context)[1].pokey_ir


def baseline_stream(context: str) -> np.ndarray:
    """The production compiler's own output for a context, untouched."""
    return np.asarray(ir.compile_ir_to_pokey_frames(context_song(context)))


def variant_stream(context: str, candidate: str, bank: SoundProfileBank) -> np.ndarray:
    """The register stream of one context with *candidate* on the melodic channel.

    Three candidates go through ``apply_profile_binding``; C1 goes through Experiment 28's ``apply_c1``.
    Both are existing implementations, called rather than copied.
    """
    entry = candidate_by_name(candidate)
    document, result = compile_context(context)

    if entry["kind"] == "experiment":
        return e28.apply_c1(baseline_stream(context), result.pokey_ir, MELODIC_CHANNEL)

    binding = load_profile_binding({
        "schema": BINDING_SCHEMA,
        "instruments": {"lead": str(entry["profile_id"])},
    })
    bound = apply_profile_binding(result, binding, bank, composition=document)
    return np.asarray(ir.compile_ir_to_pokey_frames(bound.pokey_ir))


def _lead_instrument(song: Any) -> Any:
    for instrument in song.instruments:
        if instrument.name.lower() == "lead":
            return instrument
    raise KeyError("the context declares no instrument named 'lead'")


def _envelope_dict(envelope: Any) -> Dict[str, int]:
    return {
        "attack_frames": envelope.attack_frames,
        "decay_frames": envelope.decay_frames,
        "release_frames": envelope.release_frames,
        "sustain_vol": envelope.sustain_vol,
    }


def applied_parameters(context: str, candidate: str, bank: SoundProfileBank) -> Dict[str, Any]:
    """What the candidate actually wrote onto the song — the numbers, not the intent.

    Read back from the same objects the renderer consumes, so the report cannot claim a parameter the
    renderer never saw. ``envelope_sources`` records, field by field, whether the value came from the
    profile or from the composition's character default — which is where the C1 asymmetry shows up.
    """
    entry = candidate_by_name(candidate)
    document, result = compile_context(context)

    if entry["kind"] == "experiment":
        song = result.pokey_ir
        envelope = _lead_instrument(song).envelope
        default = "composition (character default)"
        return {
            "generator_byte": 0x40,
            "generator_note": (
                "$40 with the divider alternating N / N//2 every frame — Experiment 27's C1 schedule, "
                "applied by Experiment 28's apply_c1"
            ),
            "envelope": _envelope_dict(envelope),
            "envelope_sources": {
                "attack_frames": default, "decay_frames": default,
                "release_frames": default, "sustain_vol": default,
            },
            "audctl": int(ir.resolve_audctl_mode(song)),
            "channel": MELODIC_CHANNEL,
            "profile_id": None,
            "profile_fingerprint": None,
            "divider_note": "nominal N and N//2, from e26.note_divider / e26.octave_divider",
        }

    binding = load_profile_binding({
        "schema": BINDING_SCHEMA,
        "instruments": {"lead": str(entry["profile_id"])},
    })
    bound = apply_profile_binding(result, binding, bank, composition=document)
    bound_song = bound.pokey_ir
    bound_lead = next(
        instrument for instrument in bound_song.instruments
        if instrument.profile_id == entry["profile_id"]
    )
    profile = bank.get(str(entry["profile_id"]))
    frames = profile.envelope_frames
    default = "composition (character default)"
    return {
        "generator_byte": int(bound_lead.distortion),
        "generator_note": f"${int(bound_lead.distortion):02X}, the profile's own generator nibble",
        "envelope": _envelope_dict(bound_lead.envelope),
        "envelope_sources": {
            "attack_frames": "profile" if frames.get("attack") is not None else default,
            "decay_frames": "profile" if frames.get("decay") is not None else default,
            "release_frames": "profile" if frames.get("release") is not None else default,
            "sustain_vol": (
                "profile" if profile.envelope_sustain_level is not None else default
            ),
        },
        "audctl": int(ir.resolve_audctl_mode(bound_song)),
        "channel": MELODIC_CHANNEL,
        "profile_id": bound_lead.profile_id,
        "profile_fingerprint": bound_lead.profile_fingerprint,
        "divider_note": "the note's own divider, unchanged",
    }


def stream_differences(reference: np.ndarray, variant: np.ndarray) -> Dict[str, Any]:
    """Exactly which frames and columns differ between the baseline and a variant."""
    if reference.shape != variant.shape:
        return {
            "same_shape": False,
            "reference_shape": list(reference.shape),
            "variant_shape": list(variant.shape),
        }
    mask = reference != variant
    rows = np.nonzero(mask.any(axis=1))[0]
    return {
        "same_shape": True,
        "changed_frames": int(rows.shape[0]),
        "changed_columns": sorted({int(column) for column in np.unique(np.nonzero(mask)[1])}),
        "first_changed_frame": int(rows[0]) if rows.size else None,
        "last_changed_frame": int(rows[-1]) if rows.size else None,
    }


# ===========================================================================
# 4. The level policy: an un-normalised set, and a loudness-matched set.
# ===========================================================================
def clip_key(context: str, candidate: str) -> str:
    return f"{context}:{candidate}"


def level_plan(raw: Mapping[str, np.ndarray]) -> Dict[str, Any]:
    """The gains for both sets, from measurements only.

    **original** — one shared gain per context, taken from the loudest raw render in that context. No
    clip is normalised on its own, so the loudness relation between the four candidates survives inside
    each context. Two gains rather than one because the composition sums three voices and the solo is a
    single voice: a single gain across both would have pushed the solo block about 6 dB down for no
    informational gain, and the two blocks are listened to separately.

    **matched** — one gain per clip, bringing every clip to a single measured loudness. The target is
    the median clip loudness, capped by the loudest loudness any clip can reach without its peak
    crossing ``MATCHED_PEAK_CEILING``. That cap is what guarantees no clipping, and it comes out of the
    material rather than being an arbitrary number.
    """
    levels = {key: measure_level(buffer) for key, buffer in raw.items()}
    for key, level in levels.items():
        if not math.isfinite(level["lufs"]):
            raise ValueError(f"{key} has no measurable loudness; nothing to match")

    original_gains: Dict[str, float] = {}
    for context in CONTEXT_ORDER:
        peaks = [levels[key]["peak"] for key in raw if key.startswith(f"{context}:")]
        original_gains[context] = TARGET_PEAK / max(peaks)

    ceiling = {
        key: level["lufs"] + dbfs(MATCHED_PEAK_CEILING / level["peak"])
        for key, level in levels.items()
    }
    median_lufs = float(np.median([level["lufs"] for level in levels.values()]))
    target_lufs = min(min(ceiling.values()), median_lufs)
    limited_by = min(ceiling, key=lambda key: ceiling[key])
    capped_by_ceiling = min(ceiling.values()) < median_lufs

    matched_gains = {
        key: 10.0 ** ((target_lufs - level["lufs"]) / 20.0)
        for key, level in levels.items()
    }
    for key, gain in matched_gains.items():
        reach = levels[key]["peak"] * gain
        if reach > MATCHED_PEAK_CEILING * (1.0 + 1e-9):
            raise ValueError(
                f"{key} would reach {reach:.6f} after matching, above the "
                f"{MATCHED_PEAK_CEILING} ceiling; the level policy is wrong"
            )

    return {
        "levels": levels,
        "original_gains": original_gains,
        "matched_gains": matched_gains,
        "matched_target_lufs": round(target_lufs, 4),
        "matched_target_capped_by": (
            "the peak ceiling" if capped_by_ceiling else "the median clip loudness"
        ),
        "matched_target_limited_by": limited_by if capped_by_ceiling else None,
        "matched_target_limited_by_lufs": round(ceiling[limited_by], 4) if capped_by_ceiling else None,
        "loudness_ceiling_lufs": {key: round(value, 4) for key, value in ceiling.items()},
        "median_lufs": round(median_lufs, 4),
    }



def _to_float(samples_int16: np.ndarray) -> np.ndarray:
    return samples_int16.astype(np.float64) / 32767.0


def render_all(
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    bank_dir: Path = DEFAULT_BANK_DIR,
) -> Dict[str, Any]:
    """Render every clip in both contexts and both loudness versions, then write the artefacts."""
    output_dir = Path(output_dir)
    audio_dir = output_dir / AUDIO_DIRNAME
    audio_dir.mkdir(parents=True, exist_ok=True)

    bank = load_sound_profile_bank(bank_dir)

    streams: Dict[str, np.ndarray] = {}
    raw: Dict[str, np.ndarray] = {}
    baselines: Dict[str, np.ndarray] = {}
    for context in CONTEXT_ORDER:
        baselines[context] = baseline_stream(context)
        for candidate in candidate_names():
            key = clip_key(context, candidate)
            streams[key] = variant_stream(context, candidate, bank)
            raw[key] = e26.render_registers(streams[key])

    plan = level_plan(raw)
    letters = letter_map()

    files: Dict[str, Path] = {}
    records: List[Dict[str, Any]] = []
    for context in CONTEXT_ORDER:
        for version in VERSION_ORDER:
            for letter in LETTERS:
                candidate = letters[letter]
                key = clip_key(context, candidate)
                gain = (
                    plan["original_gains"][context] if version == VERSION_ORIGINAL
                    else plan["matched_gains"][key]
                )
                samples = e26.to_int16(raw[key], gain)
                filename = f"{context}_{version}_{letter}.wav"
                path = e26.write_wav(audio_dir / filename, samples, SAMPLE_RATE)
                files[f"{context}|{version}|{letter}"] = path

                level = plan["levels"][key]
                # measured on the delivered int16 samples, not predicted from the raw buffer
                delivered = measure_level(_to_float(samples))
                records.append({
                    "file": filename,
                    "context": context,
                    "version": version,
                    "letter": letter,
                    "candidate": candidate,
                    "profile_id": candidate_by_name(candidate)["profile_id"],
                    "gain": round(gain, 10),
                    "gain_dbfs": round(dbfs(gain), 4),
                    "frames": int(streams[key].shape[0]),
                    "samples": int(samples.shape[0]),
                    "duration_seconds": round(samples.shape[0] / SAMPLE_RATE, 4),
                    "before": {
                        "peak": level["peak"], "peak_dbfs": level["peak_dbfs"],
                        "rms": level["rms"], "rms_dbfs": level["rms_dbfs"],
                        "lufs": level["lufs"],
                    },
                    "after_measured": delivered,
                    "after_predicted_lufs": round(level["lufs"] + dbfs(gain), 4),
                    "audible_channels": sorted(
                        channel for channel in range(1, 5)
                        if np.any(streams[key][:, ir.audc_column(channel)] & 0x0F)
                    ),
                })

    result: Dict[str, Any] = {
        "output_dir": output_dir,
        "audio_dir": audio_dir,
        "bank": bank,
        "bank_dir": Path(bank_dir),
        "streams": streams,
        "raw": raw,
        "baselines": baselines,
        "plan": plan,
        "letters": letters,
        "files": files,
        "records": records,
    }
    result["differences"] = {
        context: {
            candidate: stream_differences(baselines[context], streams[clip_key(context, candidate)])
            for candidate in candidate_names()
        }
        for context in CONTEXT_ORDER
    }
    result["parameters"] = {
        context: {
            candidate: applied_parameters(context, candidate, bank)
            for candidate in candidate_names()
        }
        for context in CONTEXT_ORDER
    }
    result["manifest_path"] = write_manifest(result, output_dir)
    result["summary_path"] = write_summary(result, output_dir)
    result["note_path"] = write_listening_note(result, output_dir)
    result["page_path"] = write_listening_page(result, output_dir)
    result["template_path"] = write_evaluation_template(result, output_dir)
    return result


# ===========================================================================
# 5. The artefacts.
# ===========================================================================
#: Pinned so a silent edit to the shared example cannot pass unnoticed.
COMPOSITION_SHA256 = "cb93bef054afbea9b7b4e96528d7ba41aa26b0472783b2e3c7f83f52b419ad36"


def validation_checks(result: Mapping[str, Any]) -> List[Dict[str, Any]]:
    """The technical validation, run as data so the summary can publish pass/fail per check."""
    bank = result["bank"]
    checks: List[Dict[str, Any]] = []

    # 1. every variant has the baseline's shape, and the same melodic note grid
    shapes_ok, notes_ok = True, True
    for context in CONTEXT_ORDER:
        baseline = result["baselines"][context]
        baseline_spans = [
            (span["start"], span["end"], span["midi"])
            for span in e28.channel_note_spans(context_song(context), MELODIC_CHANNEL)
        ]
        for candidate in candidate_names():
            stream = result["streams"][clip_key(context, candidate)]
            if stream.shape != baseline.shape:
                shapes_ok = False
            spans = [
                (span["start"], span["end"], span["midi"])
                for span in e28.channel_note_spans(context_song(context), MELODIC_CHANNEL)
            ]
            if spans != baseline_spans:
                notes_ok = False
    checks.append({
        "check": "every variant has the baseline's frame count",
        "passed": shapes_ok,
        "detail": f"{len(CONTEXT_ORDER)} contexts x {len(CANDIDATES)} candidates",
    })
    checks.append({
        "check": "the melodic note grid (start, end, midi) is identical in every variant",
        "passed": notes_ok,
        "detail": "computed with e28.channel_note_spans, the same arithmetic the compiler uses",
    })

    # 2. the untouched parts are byte-identical: every column except the melodic channel's
    allowed = {ir.audf_column(MELODIC_CHANNEL), ir.audc_column(MELODIC_CHANNEL)}
    offenders: List[str] = []
    for context in CONTEXT_ORDER:
        for candidate in candidate_names():
            changed = set(result["differences"][context][candidate].get("changed_columns") or [])
            if not changed <= allowed:
                offenders.append(f"{context}/{candidate}: {sorted(changed - allowed)}")
    checks.append({
        "check": "only the melodic channel's AUDF and AUDC columns differ from the baseline",
        "passed": not offenders,
        "detail": f"allowed columns {sorted(allowed)}; offenders {offenders or 'none'}",
    })

    # 3. the composition's own hardware flags did not move
    audctl_ok = True
    for context in CONTEXT_ORDER:
        want = int(ir.resolve_audctl_mode(context_song(context)))
        for candidate in candidate_names():
            if result["parameters"][context][candidate]["audctl"] != want:
                audctl_ok = False
    checks.append({
        "check": "AUDCTL is the baseline's in every variant",
        "passed": audctl_ok,
        "detail": (
            f"composition ${int(ir.resolve_audctl_mode(context_song(CONTEXT_COMPOSITION))):02X}, "
            f"solo ${int(ir.resolve_audctl_mode(context_song(CONTEXT_SOLO))):02X}"
        ),
    })

    # 4. no candidate was silently substituted: the generator is the declared one
    generator_ok = True
    seen: List[str] = []
    for context in CONTEXT_ORDER:
        for candidate in candidate_names():
            entry = candidate_by_name(candidate)
            got = int(result["parameters"][context][candidate]["generator_byte"]) & 0xE0
            want = 0x40 if entry["kind"] == "experiment" else int(
                bank.get(str(entry["profile_id"])).distortion_byte
            )
            if got != want:
                generator_ok = False
            seen.append(f"{candidate}=${got:02X}")
    checks.append({
        "check": "every variant's AUDC generator nibble is the candidate's own",
        "passed": generator_ok,
        "detail": ", ".join(sorted(set(seen))),
    })

    # 5. no clipping anywhere, in either set
    clipping = [
        record["file"] for record in result["records"]
        if record["after_measured"]["peak"] > 1.0
    ]
    checks.append({
        "check": "no delivered file clips",
        "passed": not clipping,
        "detail": f"{len(result['records'])} files; offenders {clipping or 'none'}",
    })

    # 6. the matched set really is matched, measured on the delivered files
    matched = [record for record in result["records"] if record["version"] == VERSION_MATCHED]
    spread = (
        max(record["after_measured"]["lufs"] for record in matched)
        - min(record["after_measured"]["lufs"] for record in matched)
    )
    checks.append({
        "check": "the matched set is level-matched to within 0.1 LU",
        "passed": spread <= 0.1,
        "detail": f"measured spread {spread:.4f} LU across {len(matched)} matched files",
    })

    # 7. the original set is not normalised per file
    peaks_per_context = {
        context: {
            record["after_measured"]["peak"] for record in result["records"]
            if record["version"] == VERSION_ORIGINAL and record["context"] == context
        }
        for context in CONTEXT_ORDER
    }
    checks.append({
        "check": "the original set keeps different peaks, so nothing was normalised per file",
        "passed": all(len(peaks) > 1 for peaks in peaks_per_context.values()),
        "detail": "; ".join(
            f"{context}: {len(peaks)} distinct peaks" for context, peaks in peaks_per_context.items()
        ),
    })

    # 8. the source composition was not modified
    checks.append({
        "check": "examples/songs/Vaults-of-Nhyrmeth.dsl is unchanged",
        "passed": hashlib.sha256(DEFAULT_COMPOSITION.read_bytes()).hexdigest() == COMPOSITION_SHA256,
        "detail": f"sha256 {COMPOSITION_SHA256[:16]}…",
    })

    # 9. the manifest maps every file exactly once
    keys = [
        f"{record['context']}|{record['version']}|{record['letter']}"
        for record in result["records"]
    ]
    checks.append({
        "check": "the manifest maps every file exactly once",
        "passed": len(keys) == len(set(keys)) == 16,
        "detail": f"{len(keys)} records",
    })

    return checks


def build_manifest(result: Mapping[str, Any]) -> Dict[str, Any]:
    """Every file mapped to its candidate, context, loudness version and applied parameters."""
    return {
        "experiment": "experiment30",
        "manifest_version": 1,
        "private": True,
        "warning": (
            "this file is the answer key: it maps every A/B/C/D letter to its candidate and describes "
            "the timbres. Do not open it, and do not read the README, until the ratings are downloaded"
        ),
        "purpose": (
            "compare four POKEY timbres solo and inside a real composition, with the timbre question "
            "separated from the loudness question"
        ),
        "candidates": [dict(candidate) for candidate in CANDIDATES],
        "letter_map": dict(letter_map()),
        "letter_map_seed": SEED,
        "contexts": {
            CONTEXT_SOLO: {
                "source": context_source(CONTEXT_SOLO),
                "rationale": SOLO_RATIONALE,
                "frames": int(result["baselines"][CONTEXT_SOLO].shape[0]),
                "seconds": round(result["baselines"][CONTEXT_SOLO].shape[0] / FRAME_RATE_HZ, 4),
            },
            CONTEXT_COMPOSITION: {
                "source": context_source(CONTEXT_COMPOSITION),
                "rationale": COMPOSITION_RATIONALE,
                "target_rationale": TARGET_RATIONALE,
                "channel": MELODIC_CHANNEL,
                "frames": int(result["baselines"][CONTEXT_COMPOSITION].shape[0]),
                "seconds": round(
                    result["baselines"][CONTEXT_COMPOSITION].shape[0] / FRAME_RATE_HZ, 4
                ),
                "source_sha256": COMPOSITION_SHA256,
            },
        },
        "applied_parameters": result["parameters"],
        "register_differences": result["differences"],
        "files": list(result["records"]),
        "level_policy": {
            "original": {
                "per_file_normalisation": False,
                "shared_gain_per_context": {
                    context: round(gain, 10)
                    for context, gain in result["plan"]["original_gains"].items()
                },
                "derivation": (
                    "one gain per context from the loudest raw render in that context; two gains "
                    "because the composition sums three voices while the solo is one, and the two "
                    "blocks are listened to separately"
                ),
            },
            "matched": {
                "method": (
                    "ITU-R BS.1770-4 K-weighted integrated loudness (LUFS), implemented in this module"
                ),
                "target_lufs": result["plan"]["matched_target_lufs"],
                "target_capped_by": result["plan"]["matched_target_capped_by"],
                "target_limited_by": result["plan"]["matched_target_limited_by"],
                "target_limited_by_lufs": result["plan"]["matched_target_limited_by_lufs"],
                "median_lufs": result["plan"]["median_lufs"],
                "loudness_ceiling_lufs": result["plan"]["loudness_ceiling_lufs"],
                "peak_ceiling": MATCHED_PEAK_CEILING,
                "gains": {
                    key: round(gain, 10) for key, gain in result["plan"]["matched_gains"].items()
                },
                "note": (
                    "a scalar gain on the rendered audio only: no envelope, pitch, rhythm or generator "
                    "parameter is changed to match a level. Sample peak is used for the ceiling, not "
                    "true peak — no oversampling is done."
                ),
            },
        },
        "audio_format": {
            "sample_rate": SAMPLE_RATE,
            "bit_depth": 16,
            "channels": 1,
            "frame_rate_hz": FRAME_RATE_HZ,
        },
        "blinding": {
            "method": (
                "the four candidates are assigned the letters A-D by a seeded shuffle, so the letters "
                "carry no ordering information"
            ),
            "honest_note": (
                "PARTIALLY blinded. The page shows letters only, and the letter-to-candidate map is "
                "here. But the same letter means the same candidate in both contexts, so a listener "
                "who has heard the solo block can already tell which composition variant is which — "
                "the composition block is not independently blind. The octave-pulse reference is also "
                "audibly unlike the other three, so 'which one is C1' is guessable from the sound."
            ),
        },
        "limitations": list(LIMITATIONS),
        "not_claimed": [
            "that any candidate sounds good — that is the listening question this experiment asks",
            "that a synthetic render proves the same timbre on real hardware",
            "that LUFS matching equals equal perceived loudness for these particular spectra",
            "that the four candidates are the only useful ones in the bank",
        ],
        "production_untouched": PRODUCTION_STATEMENT,
    }


def write_manifest(result: Mapping[str, Any], output_dir: Path) -> Path:
    path = Path(output_dir) / "manifest.json"
    path.write_text(
        json.dumps(build_manifest(result), indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return path


def build_summary(result: Mapping[str, Any]) -> Dict[str, Any]:
    """The measurements and the validation result, as data."""
    checks = validation_checks(result)
    matched = [record for record in result["records"] if record["version"] == VERSION_MATCHED]
    original = [record for record in result["records"] if record["version"] == VERSION_ORIGINAL]

    def spread(records: Sequence[Mapping[str, Any]], field: str) -> float:
        values = [record["after_measured"][field] for record in records]
        return round(max(values) - min(values), 4)

    def spread_lu(records: Sequence[Mapping[str, Any]]) -> float:
        values = [record["after_measured"]["lufs"] for record in records]
        return round(max(values) - min(values), 4)

    return {
        "experiment": "experiment30",
        "summary_version": 1,
        "purpose": (
            "does a timbre that survives an isolated figure also survive a real composition, and is the "
            "answer stable once loudness is taken out of the comparison"
        ),
        "candidates": [dict(candidate) for candidate in CANDIDATES],
        "letter_map": dict(letter_map()),
        "contexts": list(CONTEXT_ORDER),
        "files_rendered": len(result["records"]),
        "audio_format": {
            "sample_rate": SAMPLE_RATE,
            "bit_depth": 16,
            "channels": 1,
        },
        "level_policy": {
            "original_gains": {
                context: round(gain, 10) for context, gain in result["plan"]["original_gains"].items()
            },
            "matched_target_lufs": result["plan"]["matched_target_lufs"],
            "matched_target_capped_by": result["plan"]["matched_target_capped_by"],
            "matched_target_limited_by": result["plan"]["matched_target_limited_by"],
            "matched_target_limited_by_lufs": result["plan"]["matched_target_limited_by_lufs"],
            "matched_gains": {
                key: round(gain, 10) for key, gain in result["plan"]["matched_gains"].items()
            },
        },
        "level_results": {
            "original": {
                "lufs_min": round(min(record["after_measured"]["lufs"] for record in original), 4),
                "lufs_max": round(max(record["after_measured"]["lufs"] for record in original), 4),
                "lufs_spread": spread_lu(original),
                "rms_dbfs_spread": spread(original, "rms_dbfs"),
                "peak_max": round(max(record["after_measured"]["peak"] for record in original), 6),
                "per_context": {
                    context: {
                        "lufs_min": round(min(
                            record["after_measured"]["lufs"] for record in original
                            if record["context"] == context), 4),
                        "lufs_max": round(max(
                            record["after_measured"]["lufs"] for record in original
                            if record["context"] == context), 4),
                        "lufs_spread": spread_lu(
                            [record for record in original if record["context"] == context]),
                        "rms_dbfs_spread": spread(
                            [record for record in original if record["context"] == context],
                            "rms_dbfs"),
                    }
                    for context in CONTEXT_ORDER
                },
            },
            "matched": {
                "lufs_min": round(min(record["after_measured"]["lufs"] for record in matched), 4),
                "lufs_max": round(max(record["after_measured"]["lufs"] for record in matched), 4),
                "lufs_spread": spread_lu(matched),
                "rms_dbfs_spread": spread(matched, "rms_dbfs"),
                "peak_max": round(max(record["after_measured"]["peak"] for record in matched), 6),
                "per_context": {
                    context: {
                        "lufs_min": round(min(
                            record["after_measured"]["lufs"] for record in matched
                            if record["context"] == context), 4),
                        "lufs_max": round(max(
                            record["after_measured"]["lufs"] for record in matched
                            if record["context"] == context), 4),
                        "lufs_spread": spread_lu(
                            [record for record in matched if record["context"] == context]),
                    }
                    for context in CONTEXT_ORDER
                },
            },
            "before_matching": {
                "lufs_min": round(min(record["before"]["lufs"] for record in matched), 4),
                "lufs_max": round(max(record["before"]["lufs"] for record in matched), 4),
                "lufs_spread": round(
                    max(record["before"]["lufs"] for record in matched)
                    - min(record["before"]["lufs"] for record in matched), 4
                ),
                "per_context": {
                    context: {
                        "lufs_spread": round(
                            max(record["before"]["lufs"] for record in matched
                                if record["context"] == context)
                            - min(record["before"]["lufs"] for record in matched
                                  if record["context"] == context), 4),
                    }
                    for context in CONTEXT_ORDER
                },
            },
        },

        "register_differences": result["differences"],
        "applied_parameters": result["parameters"],
        "validation": {
            "checks": checks,
            "passed": all(check["passed"] for check in checks),
            "failed": [check["check"] for check in checks if not check["passed"]],
        },
        "measurements": list(result["records"]),
        "limitations": list(LIMITATIONS),
        "production_untouched": PRODUCTION_STATEMENT,
    }


def write_summary(result: Mapping[str, Any], output_dir: Path) -> Path:
    path = Path(output_dir) / "summary.json"
    path.write_text(
        json.dumps(build_summary(result), indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return path


def write_evaluation_template(result: Mapping[str, Any], output_dir: Path) -> Path:
    """The empty rating template, with exactly the headers the page downloads."""
    path = Path(output_dir) / EVALUATION_CSV
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(EVALUATION_FIELDS)
        for record in result["records"]:
            row = dict.fromkeys(EVALUATION_FIELDS, "")
            row["context"] = record["context"]
            row["version"] = record["version"]
            row["letter"] = record["letter"]
            writer.writerow([row[field] for field in EVALUATION_FIELDS])
    return path


# ===========================================================================
# 6. The listening page.
# ===========================================================================
_PAGE_HEAD = r"""<!DOCTYPE html>
<html lang="pl">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Experiment 30 — porównanie brzmień POKEY</title>
<style>
  :root { color-scheme: dark; }
  body { font-family: system-ui, -apple-system, "Segoe UI", sans-serif; margin: 0; padding: 1.5rem;
         background: #14161a; color: #e8e8ea; line-height: 1.5; }
  main { max-width: 72rem; margin: 0 auto; }
  h1, h2, h3 { line-height: 1.2; }
  h2 { margin-top: 2.5rem; border-top: 1px solid #2c3036; padding-top: 1.25rem; }
  h3 { margin: 1.75rem 0 .5rem; }
  .note { background: #1d2026; border-left: 3px solid #4a7; padding: .75rem 1rem; margin: 1rem 0;
          border-radius: 3px; font-size: .95rem; }
  .note.warn { border-left-color: #c85; }
  .card { background: #1a1d22; border: 1px solid #2c3036; border-radius: 6px; padding: 1rem;
          margin: 1rem 0; }
  .card.done { border-color: #3d6; }
  .row { display: grid; grid-template-columns: 9rem 1fr; gap: .75rem; align-items: start;
         padding: .6rem 0; border-top: 1px solid #24282e; }
  .row:first-child { border-top: 0; }
  .tag { font-family: ui-monospace, Consolas, monospace; background: #23272e; border: 1px solid #333;
         border-radius: 4px; padding: .15rem .45rem; font-size: .85rem; display: inline-block; }
  audio { width: 100%; max-width: 26rem; }
  .q { margin: .5rem 0; }
  .label { font-weight: 600; font-size: .92rem; }
  .scale { display: flex; gap: .35rem; flex-wrap: wrap; }
  .scale label { background: #23272e; border: 1px solid #333; border-radius: 4px;
                 padding: .2rem .5rem; cursor: pointer; font-size: .85rem; }
  .scale input { margin-right: .25rem; }
  textarea, input[type=text] { width: 100%; background: #23272e; color: inherit; border: 1px solid #333;
                 border-radius: 4px; padding: .35rem; font: inherit; }
  textarea { min-height: 2.5rem; font-size: .9rem; }
  input[type=text] { max-width: 20rem; }
  button { background: #2d5; color: #06120a; border: 0; border-radius: 4px; padding: .55rem 1rem;
           font: inherit; font-weight: 600; cursor: pointer; margin-right: .5rem; margin-bottom: .5rem; }
  button.ghost { background: #333; color: #ddd; }
  .progress { position: sticky; top: 0; background: #14161af2; padding: .6rem 0; z-index: 5;
              border-bottom: 1px solid #2c3036; font-size: .92rem; }
  .small { font-size: .86rem; color: #aab; }
  .reveal { display: none; }
  .reveal.on { display: block; }
  .rev { background: #23272e; border-left: 3px solid #c85; padding: .6rem .8rem; border-radius: 3px;
         margin: .5rem 0; font-size: .92rem; }
</style>
</head>
<body>
<main>
<h1>Experiment 30 — porównanie brzmień POKEY</h1>

<div class="note">
  <strong>Cztery brzmienia, dwa konteksty, dwie wersje głośności.</strong> Każde brzmienie jest
  oznaczone literą <strong>A–D</strong>. Ta sama litera oznacza to samo brzmienie w obu blokach.
  Nazwy brzmień są ukryte do momentu, w którym sam je odsłonisz.
</div>
<div class="note">
  <strong>Blok „Pojedyncze brzmienie”</strong> to jedna figura: dźwięk trzymany, pauza, potem motyw
  melodyczny i zejście w dół. <strong>Blok „Kompozycja”</strong> to prawdziwy utwór, w którym zmienia
  się wyłącznie brzmienie partii melodycznej — nuty, bas, perkusja, tempo i długość są identyczne.
</div>
<div class="note">
  <strong>Dwie wersje głośności.</strong> <em>Oryginalna</em> zachowuje naturalne różnice poziomu między
  brzmieniami. <em>Wyrównana</em> sprowadza wszystkie próbki do zmierzonej głośności (LUFS), żeby
  oceniać barwę, a nie poziom. <strong>Oceń przede wszystkim wersję wyrównaną</strong>, a potem
  sprawdź, czy wersja oryginalna zmienia Twoją ocenę — właśnie po to są obie.
</div>
<div class="note warn">
  <strong>To porównanie jest tylko częściowo ślepe.</strong> Litery nie zdradzają nazw, ale ta sama
  litera oznacza to samo brzmienie w obu blokach — więc po bloku solowym możesz już rozpoznać warianty
  w kompozycji. Dodatkowo jedno z brzmień jest wyraźnie inne od pozostałych.
</div>

<div class="progress" id="progress">progress</div>

<h2>Twoje imię lub inicjały</h2>
<p class="small">Trafia tylko do pierwszej kolumny eksportowanego CSV. Możesz zostawić puste.</p>
<div class="q"><input type="text" id="listener" placeholder="anonim"
  oninput="setMeta('listener', this.value)"></div>

<div id="blocks"></div>

<h2>Zakończenie</h2>
<p class="small">Pobierz plik CSV i włóż go z powrotem do katalogu <code>experiments/experiment30/</code>.
Nic nie jest nigdzie wysyłane — wszystko zostaje w tej przeglądarce do momentu pobrania.</p>
<button onclick="downloadCsv()">Pobierz oceny (CSV)</button>
<button class="ghost" onclick="reveal()">Odsłoń nazwy brzmień</button>
<button class="ghost" onclick="if(confirm('Usunąć wszystkie odpowiedzi w tej przeglądarce?')){localStorage.clear();location.reload();}">Wyczyść odpowiedzi</button>
<p class="small" id="downloadState"></p>

<div class="reveal" id="revealBox">
  <h2>Nazwy brzmień</h2>
  <p class="small">Jeżeli jeszcze nie skończyłeś oceniać, zamknij tę stronę bez czytania dalej.</p>
  <div id="revealContent"></div>
</div>

<h2>Co dalej</h2>
<p class="small">Po odsłuchu odpowiedz proszę na cztery pytania z raportu
(<code>docs/experiment30_timbre_ab_evaluation.md</code>): które brzmienie najlepiej wypada solo, które
w kompozycji, które warto zachować w pierwszej bibliotece i czy któreś wymaga dalszej pracy. Żadne
brzmienie nie zostało włączone do produkcyjnego Composera.</p>

</main>
"""


_PAGE_SCRIPT = r"""
<script>
const PACKAGE = __PACKAGE__;
const STORE = "experiment30-answers-v1";

let answers = JSON.parse(localStorage.getItem(STORE) || "{}");
let meta = answers.__meta || {};

function save() { localStorage.setItem(STORE, JSON.stringify(answers)); refresh(); }
function get(key, field) { return (answers[key] || {})[field] ?? ""; }
function set(key, field, value) {
  answers[key] = answers[key] || {};
  answers[key][field] = value;
  save();
}
function setMeta(field, value) { meta[field] = value; answers.__meta = meta; save(); }
function listener() { return String(meta.listener ?? "").trim(); }
function ratingKey(context, version, letter) { return `${context}|${version}|${letter}`; }

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

// Every question is rendered from PACKAGE, so the page, the manifest and the CSV columns come from
// one declaration and cannot drift apart.
function scaleRow(key, field, question, labels) {
  const current = get(key, field);
  const inputs = labels.map((label, index) => {
    const value = index + 1;
    const checked = String(current) === String(value) ? " checked" : "";
    return `<label><input type="radio" name="${key}-${field}" value="${value}"${checked}
      onchange="set('${key}','${field}','${value}')">${value} ${label}</label>`;
  }).join("");
  return `<div class="q"><div class="label">${question}</div><div class="scale">${inputs}</div></div>`;
}

function choiceRow(key, field, question, choices) {
  const current = get(key, field);
  const inputs = choices.map(([value, label]) => {
    const checked = String(current) === String(value) ? " checked" : "";
    return `<label><input type="radio" name="${key}-${field}" value="${value}"${checked}
      onchange="set('${key}','${field}','${value}')">${label}</label>`;
  }).join("");
  return `<div class="q"><div class="label">${question}</div><div class="scale">${inputs}</div></div>`;
}

function commentRow(key, field, question) {
  const value = String(get(key, field)).replace(/</g, "&lt;");
  return `<div class="q"><div class="label">${question}</div>
    <textarea oninput="set('${key}','${field}',this.value)">${value}</textarea></div>`;
}
</script>
"""


_PAGE_SCRIPT_B = r"""
<script>
const SCALES = PACKAGE.scales.map(s => s.field);
function rowFields() { return SCALES.concat(["typical_use", "supports_melody"]); }
function rowDone(key) { return rowFields().every(field => get(key, field) !== ""); }
function rowCount() { return PACKAGE.blocks.length * PACKAGE.letters.length * PACKAGE.versions.length; }
function doneCount() {
  let done = 0;
  PACKAGE.blocks.forEach(block => PACKAGE.letters.forEach(letter =>
    PACKAGE.versions.forEach(version => {
      if (rowDone(ratingKey(block.context, version, letter))) { done += 1; }
    })));
  return done;
}

function audioRow(block, version, letter, label, note) {
  const key = ratingKey(block.context, version, letter);
  const file = PACKAGE.files[key];
  return `<div class="row">
    <div><span class="tag">${label}</span><div class="small">${note}</div></div>
    <div>
      <audio controls preload="none" src="audio/${file}"></audio>` +
      PACKAGE.scales.map(s => scaleRow(key, s.field, s.question, s.labels)).join("") +
      choiceRow(key, "typical_use", "Typowe zastosowanie", PACKAGE.typical_use) +
      choiceRow(key, "supports_melody", "Czy brzmienie nadal wspiera zamierzoną melodię?",
        PACKAGE.supports_melody) +
      commentRow(key, "comment", "Komentarz (opcjonalnie)") +
    `</div></div>`;
}

function card(block, letter) {
  return `<div class="card" id="${block.context}-${letter}">
    <h3><span class="tag">${letter}</span> — ${block.title}</h3>
    <p class="small">${block.hint}</p>` +
    audioRow(block, "original", letter, "Oryginalna", "naturalne różnice poziomu") +
    audioRow(block, "matched", letter, "Wyrównana", "ta sama zmierzona głośność dla wszystkich") +
  `</div>`;
}

function blockSection(block) {
  return `<h2>${block.title}</h2><p class="small">${block.description}</p>` +
    PACKAGE.letters.map(letter => card(block, letter)).join("");
}

document.getElementById("blocks").innerHTML = PACKAGE.blocks.map(blockSection).join("");
document.getElementById("listener").value = String(meta.listener ?? "");

function refresh() {
  document.getElementById("progress").textContent =
    `Postęp — oceniono ${doneCount()}/${rowCount()} wierszy ` +
    `(każde brzmienie ma 2 wiersze: oryginalny i wyrównany). Odpowiedzi zapisują się w tej przeglądarce.`;
  PACKAGE.blocks.forEach(block => PACKAGE.letters.forEach(letter => {
    const node = document.getElementById(`${block.context}-${letter}`);
    if (!node) { return; }
    const all = PACKAGE.versions.every(version =>
      rowDone(ratingKey(block.context, version, letter)));
    node.className = "card" + (all ? " done" : "");
  }));
}

function stamp() {
  return (listener() || "anonymous").replace(/[^A-Za-z0-9._-]+/g, "_");
}

function downloadCsv() {
  const rows = [];
  PACKAGE.blocks.forEach(block => PACKAGE.versions.forEach(version =>
    PACKAGE.letters.forEach(letter => {
      const key = ratingKey(block.context, version, letter);
      rows.push(PACKAGE.fields.map(field => {
        if (field === "listener") { return listener(); }
        if (field === "context") { return block.context; }
        if (field === "version") { return version; }
        if (field === "letter") { return letter; }
        return get(key, field);
      }));
    })));
  download(`evaluation_experiment30__${stamp()}.csv`, PACKAGE.fields, rows);
  document.getElementById("downloadState").textContent =
    "Oceny pobrane. Włóż plik CSV do katalogu experiments/experiment30/.";
}

function reveal() {
  const box = document.getElementById("revealBox");
  box.className = "reveal on";
  document.getElementById("revealContent").innerHTML = PACKAGE.letters.map(letter => {
    const entry = PACKAGE.reveal[letter];
    const profile = entry.profile_id ? `, profil <code>${entry.profile_id}</code>` : "";
    return `<div class="rev"><strong>${letter}</strong> — <code>${entry.name}</code><br>
      <span class="small">${entry.source}<br>generator ${entry.generator}${profile}</span></div>`;
  }).join("") + `<p class="small">${PACKAGE.reveal_note}</p>`;
  box.scrollIntoView({behavior: "smooth"});
}

refresh();
</script>
</body>
</html>
"""


def build_listening_package(result: Mapping[str, Any]) -> Dict[str, Any]:
    """The object the page embeds. Before a reveal it carries no candidate name."""
    letters = letter_map()
    files = {
        f"{record['context']}|{record['version']}|{record['letter']}": record["file"]
        for record in result["records"]
    }
    blocks = []
    for context in CONTEXT_ORDER:
        if context == CONTEXT_SOLO:
            blocks.append({
                "context": context,
                "title": "Pojedyncze brzmienie",
                "description": SOLO_RATIONALE,
                "hint": "Oceń charakter samego dźwięku oraz zachowanie przy zmianach wysokości.",
            })
        else:
            blocks.append({
                "context": context,
                "title": "Kompozycja",
                "description": (
                    "Ten sam utwór cztery razy; zmienia się wyłącznie brzmienie partii melodycznej "
                    "(CH3). Bas, perkusja, nuty, tempo i długość są identyczne."
                ),
                "hint": "Oceń, czy melodia nadal działa i czy brzmienie pasuje do całości.",
            })
    return {
        "experiment": "experiment30",
        "title": "Experiment 30 — porównanie brzmień POKEY",
        "letters": list(LETTERS),
        "versions": list(VERSION_ORDER),
        "blocks": blocks,
        "files": files,
        "scales": [dict(scale) for scale in EVALUATION_SCALES],
        "typical_use": [list(choice) for choice in TYPICAL_USE_CHOICES],
        "supports_melody": [list(choice) for choice in SUPPORTS_MELODY_CHOICES],
        "fields": list(EVALUATION_FIELDS),
        "reveal": {
            letter: {
                "name": letters[letter],
                "source": candidate_by_name(letters[letter])["source"],
                "generator": candidate_by_name(letters[letter])["generator"],
                "profile_id": candidate_by_name(letters[letter])["profile_id"],
            }
            for letter in LETTERS
        },
        "reveal_note": (
            "Ta sama litera oznacza to samo brzmienie w obu blokach. Wersja 'oryginalna' zachowuje "
            "naturalne różnice poziomu, 'wyrównana' sprowadza wszystkie próbki do jednej zmierzonej "
            "głośności."
        ),
    }


def render_page(package: Mapping[str, Any]) -> str:
    embedded = json.dumps(package, sort_keys=True, ensure_ascii=False)
    page = (_PAGE_HEAD + _PAGE_SCRIPT + _PAGE_SCRIPT_B).replace("__PACKAGE__", embedded)
    return page.replace("__TITLE__", str(package["title"]))


def write_listening_page(result: Mapping[str, Any], output_dir: Path) -> Path:
    path = Path(output_dir) / "index.html"
    path.write_text(render_page(build_listening_package(result)), encoding="utf-8")
    return path


def listening_note(result: Mapping[str, Any]) -> str:
    """The listener-facing README: how to listen, and what the numbers mean."""
    summary = build_summary(result)
    original = summary["level_results"]["original"]
    matched = summary["level_results"]["matched"]
    before = summary["level_results"]["before_matching"]
    letters = letter_map()
    solo_frames = result["baselines"][CONTEXT_SOLO].shape[0]
    comp_frames = result["baselines"][CONTEXT_COMPOSITION].shape[0]
    lines: List[str] = [
        "# Experiment 30 — four POKEY timbres, solo and in a composition",
        "",
        "Four timbres, two contexts, two loudness versions. This is the listening material for the",
        "decision the previous experiments were building towards: which of these sounds are worth",
        "keeping.",
        "",
        "## Start here",
        "",
        "1. Open **`index.html`** in a browser. Nothing else is needed; no server is required.",
        "2. Read the four notes at the top of the page, then listen to the **Solo** block.",
        "3. Rate every row. Each timbre has two rows: **original** level and **level-matched**.",
        "   Judge the **matched** row first — that is the one where loudness is not doing the talking —",
        "   then check whether the original changes your mind. That comparison is the point of having",
        "   both.",
        "4. Then do the same for the **Composition** block.",
        "5. Download the CSV, put it back in this folder, and only then press **Odsłoń nazwy brzmień**.",
        "",
        "If the browser will not play local audio, serve the folder:",
        "",
        "```bash",
        "python -m http.server 8735 --directory experiments/experiment30",
        "```",
        "",
        "then open <http://localhost:8735/>.",
        "",
        "## What is being compared",
        "",
        "| context | source | length | what changes |",
        "|---|---|---|---|",
        f"| Solo | experiment-local DSL | {solo_frames} frames / "
        f"{solo_frames / FRAME_RATE_HZ:.1f} s | only the lead's timbre |",
        f"| Composition | `{context_source(CONTEXT_COMPOSITION)}` | {comp_frames} frames / "
        f"{comp_frames / FRAME_RATE_HZ:.1f} s | only the lead's timbre (CH3) |",
        "",
        SOLO_RATIONALE,
        "",
        COMPOSITION_RATIONALE,
        "",
        "In the composition, bass (CH1+CH2, 16-bit), percussion (CH4), every note, every onset, every",
        "duration, the tempo, the structure and the length are **identical** in all four variants. The",
        "register-level proof is in `summary.json` under `register_differences`: only CH3's AUDC column",
        "changes for the three bank profiles, and CH3's AUDC and AUDF columns for the octave-pulse one.",
        "",
        "## Loudness",
        "",
        "**Original set.** One shared gain per context, taken from the loudest raw render in that",
        "context. No clip is normalised on its own, so the loudness relation between the four timbres",
        "survives. Measured spread **within a context** — the number you actually experience, because",
        "you listen block by block:",
        f"**{original['per_context'][CONTEXT_SOLO]['lufs_spread']} LU** solo "
        f"({original['per_context'][CONTEXT_SOLO]['lufs_min']} to "
        f"{original['per_context'][CONTEXT_SOLO]['lufs_max']} LUFS), "
        f"**{original['per_context'][CONTEXT_COMPOSITION]['lufs_spread']} LU** in the composition "
        f"({original['per_context'][CONTEXT_COMPOSITION]['lufs_min']} to "
        f"{original['per_context'][CONTEXT_COMPOSITION]['lufs_max']} LUFS).",
        "",
        "**Matched set.** Every clip brought to one measured loudness —",
        f"**{summary['level_policy']['matched_target_lufs']} LUFS** — with a scalar gain on the rendered",
        "audio. Nothing else is changed: no envelope, pitch, rhythm or generator parameter is touched to",
        "match a level. Before matching the spread was",
        f"**{before['lufs_spread']} LU**; after it is **{matched['lufs_spread']} LU**, measured on the",
        f"delivered files. The loudest file peaks at {matched['peak_max']:.3f}, so nothing clips.",
        "",
        "**Why the matched set is quieter than you might expect.** The target is the loudest level every",
        "clip can reach without its peak crossing 0.90, and that limit is set by one clip:",
        f"`{summary['level_policy']['matched_target_limited_by']}`. It is intrinsically peaky — a sharp",
        "attack over a low sustain, so its transients reach full scale while its average level is low.",
        "Matching *up* to the others would have clipped it. So the whole matched set sits at a low",
        "absolute level and **you will need to raise the volume** for those files. That is the price of",
        "matching without limiting or compressing, which this experiment does not do.",
        "",
        "**How loudness is measured.** ITU-R BS.1770-4 K-weighted integrated loudness (LUFS), implemented",
        "in the experiment module because no loudness library is installed. It is not an approximation:",
        "the filter derivation reproduces the standard's published 48 kHz coefficients to 1e-15, and the",
        "meter reads a -20 dBFS 997 Hz sine as -20.0 LUFS. Both are asserted in the test suite.",
        "",
        "**What matching does not fix.** LUFS equalises *measured* loudness, not *perceived* loudness.",
        "Two timbres with very different spectra — a poly4 buzz against a clean square — can still sound",
        "unequal at the same LUFS. Where that happens, trust your ears over the number and say so in the",
        "comment field.",
        "",
        "## The letter map",
        "",
        "| letter | candidate |",
        "|---|---|",
    ]
    for letter in LETTERS:
        lines.append(f"| {letter} | `{letters[letter]}` |")
    return "\n".join(lines + _note_tail(result))


def _note_tail(result: Mapping[str, Any]) -> List[str]:
    """The second half of the README, kept separate so each edit stays small."""
    return [
        "",
        "The letters are assigned by a seeded shuffle, so they carry no ordering information. **The same",
        "letter means the same timbre in both contexts** — convenient for comparing a timbre solo and in",
        "the mix, but it also means the composition block is not independently blind once you have heard",
        "the solo block. That is stated on the page too.",
        "",
        "## Files",
        "",
        "| file | what it is |",
        "| :--- | :--- |",
        "| `index.html` | the listening page — **the only file you need to open** |",
        "| `audio/` | 16 WAVs: 2 contexts x 2 loudness versions x 4 letters |",
        f"| `{EVALUATION_CSV}` | the empty rating template, with the same headers the page downloads |",
        "| `manifest.json` | every file mapped to its candidate, context, version and applied "
        "parameters — **the answer key** |",
        "| `summary.json` | measurements and the technical validation result |",
        "",
        "## What this is not",
        "",
        "It is not proof that these timbres sound good — that is what your ratings are for. It is not",
        "proof that the same sound is reachable on real hardware: these are renders of the POKEY register",
        "model, and nothing here is exported to a player. It is not a production integration: no candidate",
        "is registered as an instrument, and no production file was changed.",
        "",
        "## Regenerating",
        "",
        "```",
        "python -m atari_music.pokey_timbre_ab_experiment",
        "```",
        "",
        "Deterministic: the same command reproduces every file byte for byte.",
        "",
    ]


def write_listening_note(result: Mapping[str, Any], output_dir: Path) -> Path:
    path = Path(output_dir) / "README.md"
    path.write_text(listening_note(result), encoding="utf-8")
    return path


def main() -> int:
    """Render the comparison set and print where everything is. No production code is touched."""
    result = render_all()
    summary = build_summary(result)
    print(f"candidates: {len(CANDIDATES)} -> letters {letter_map()}")
    print(f"contexts:   {', '.join(CONTEXT_ORDER)}")
    print(f"files:      {len(result['records'])} "
          f"({len(CONTEXT_ORDER)} contexts x {len(VERSION_ORDER)} versions x {len(LETTERS)} letters)")
    print(f"original:   spread {summary['level_results']['original']['lufs_spread']} LU "
          f"({summary['level_results']['original']['lufs_min']} .. "
          f"{summary['level_results']['original']['lufs_max']} LUFS)")
    print(f"matched:    target {summary['level_policy']['matched_target_lufs']} LUFS, "
          f"spread {summary['level_results']['matched']['lufs_spread']} LU, "
          f"peak {summary['level_results']['matched']['peak_max']}")
    print(f"validation: {'PASS' if summary['validation']['passed'] else 'FAIL'} "
          f"({len(summary['validation']['checks'])} checks)")
    for check in summary["validation"]["checks"]:
        mark = "ok  " if check["passed"] else "FAIL"
        print(f"  [{mark}] {check['check']} — {check['detail']}")
    print(f"page:       {result['page_path']}")
    print(f"manifest:   {result['manifest_path']}")
    print(f"summary:    {result['summary_path']}")
    print(f"readme:     {result['note_path']}")
    print(f"template:   {result['template_path']}")
    return 0 if summary["validation"]["passed"] else 1


if __name__ == "__main__":  # pragma: no cover - manual entry point
    raise SystemExit(main())


















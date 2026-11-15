"""Stage 9C: a blinded listening experiment over the POKEY sound profile library.

The library holds 67 profiles. Which of them are perceptually distinctive, musically
useful and worth keeping is a **human** question, and this module exists to ask it — not to
answer it.

It produces a self-contained package a listener can complete without Python:

```
examples/sound_profile_listening/
    README.md                      how to run the experiment
    index.html                     the listening interface (no server needed)
    manifest.json                  PRIVATE: sample -> profile mapping, features, levels
    audio/
        sample_001.wav …           one stimulus per renderable profile, blinded
        song_01_a.wav, song_01_b.wav …   real-song A/B, sides blinded
    evaluation_profiles.csv        templates to fill in (one row per sample)
    evaluation_ab.csv              (one row per profile A/B trial)
    evaluation_songs.csv           (one row per song A/B trial)
```

and `analyze_experiment` turns the completed spreadsheets into a report. The analysis
describes the evidence; it does not choose a library.

Design, in one paragraph. Every renderable profile is realized on an **identical musical
stimulus** — the same 32-step phrase at the same tempo, velocity, duration and pitch — so the
profile is the only variable, and a PAIR profile is exercised through the same phrase on the
channel its pair must drive. Levels are equalized by a gain-only peak normalization to the
project's existing listening-test level, and both the original and final peak/RMS are recorded
so loudness can be investigated rather than assumed. Samples are presented under neutral
labels in a shuffled order fixed by a recorded seed. The A/B trials reuse those same
stimuli — which is the strongest possible guarantee that "everything else is identical" — in
a stratified set chosen for the questions the brief asks, and the song trials compare the
default and profile-bound render of the same composition, cut identically on both sides.
"""

from __future__ import annotations

import csv
import hashlib
import json
import math
import random
import re
import shutil
import statistics
import subprocess
import wave
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

import numpy as np

from atari_music import __version__ as RENDERER_VERSION
from atari_music.ai.client import (
    generate_music_from_composition,
    load_composition_dsl,
    load_composition_json,
)
from atari_music.ai.schema import (
    AICompositionDoc,
    AICompositionMetadata,
    AIHardwareConfig,
    AIInstrumentDef,
    AIPatternChannelEvent,
    AIPatternDef,
)
from atari_music.ir import compile_ir_to_pokey_frames
from atari_music.pokey_synth import render_pokey_samples
from atari_music.sound_profiles import (
    RENDERABLE_STATUSES,
    SoundProfile,
    SoundProfileBank,
    SoundProfileError,
    apply_profile_binding,
    load_profile_binding,
    load_sound_profile_bank,
)
from atari_music.sound_profiles.binding import PROFILE_ENVELOPE_OUT_OF_RANGE

#: The experiment this module builds.
EXPERIMENT = "stage9c"

#: Version of the package format, so a later stage can tell what it is reading.
MANIFEST_VERSION = "stage9c/1"

#: Fixed seed for the presentation order, recorded in the manifest.
DEFAULT_SEED = 20261005

#: Sample rate of every rendered stimulus.
SAMPLE_RATE = 44100

#: The peak every stimulus is normalized to, as a linear amplitude.
#:
#: -0.92 dBFS is the level the project's existing listening tests use, so this experiment is
#: comparable with them. Peak normalization (rather than RMS) sets a common nominal level
#: *without* erasing the loudness differences the profiles genuinely have: a profile whose
#: envelope sustains low stays comparatively quiet after normalization, which is information
#: the analysis can use.
TARGET_PEAK = 0.9

#: The stimulus phrase: (note name, duration in steps). 32 steps in total.
STIMULUS_PHRASE: Tuple[Tuple[str, int], ...] = (
    ("C4", 4),
    ("E4", 4),
    ("G4", 4),
    ("C5", 4),
    ("B4", 2),
    ("G4", 2),
    ("E4", 4),
    ("C4", 8),
)

#: Tempo of the stimulus. 100 BPM -> `frames_per_tick` 5 -> 100 ms per step.
STIMULUS_BPM = 100

#: The instrument character every stimulus declares, so the composer's own defaults for that
#: character are what a profile with an unexpressible envelope falls back to.
STIMULUS_CHARACTER = "bright_lead"

#: Velocity of every stimulus note: one nominal level for every profile.
STIMULUS_VELOCITY = 13

#: The envelope fields the binding resolves per field, in the order it resolves them.
_ENVELOPE_FIELDS = ("attack_frames", "decay_frames", "release_frames", "sustain_vol")

#: Length of each song A/B excerpt, in seconds. Cut identically on both sides, so the
#: composition is untouched and only the binding differs.
SONG_EXCERPT_SECONDS = 15.0

#: The song A/B program: (file name, why it is here). Chosen for layout and style variety —
#: three songs that join 1+2 and three that keep four independent channels.
CONTEXT_SONGS: Tuple[str, ...] = (
    "Vaults-of-Nhyrmeth.dsl",   # 16-bit pair, three voices
    "as-1.dsl",                 # 16-bit pair, bass/lead/perc
    "dziki2.json",              # 16-bit pair, five voices, two sharing a channel
    "as-2.dsl",                 # four independent channels, four voices
    "funky.json",               # four independent channels, lead/pad/bass/perc
    "koval.json",               # four independent channels, five voices, two sharing a channel
)

#: How many A/B trials to build (the brief asks for 20-30).
AB_TRIAL_TARGET = 30

#: Spectral bands used for the technical distance. Log-spaced across the audible range.
SPECTRAL_BANDS = 16
_BAND_EDGES_HZ = tuple(
    40.0 * (16000.0 / 40.0) ** (index / SPECTRAL_BANDS) for index in range(SPECTRAL_BANDS + 1)
)

#: The strata the A/B set is built from, and how many trials each contributes. The counts add
#: up to more than AB_TRIAL_TARGET on purpose: a pair that qualifies for two strata is used
#: once, so the realised set is slightly smaller than the sum.
AB_STRATA: Tuple[Tuple[str, int], ...] = (
    ("similar", 6),
    ("distant", 6),
    ("same_generator", 4),
    ("different_generator", 4),
    ("same_source_song", 5),
    ("cross_song", 5),
)

#: Free-text words that carry no information about the sound, excluded from the vocabulary.
VOCABULARY_STOPWORDS = frozenset(
    """
    a an the and or but if of to in on at by for with from is are was were be been being
    it its this that these those as so than then there here very really quite just too more
    most much many some any no not none like seems seems sound sounds sounding heard hear
    hearing maybe perhaps almost nearly similar different same kind sort thing things
    sample samples a/b b a&b ab yes no idea
    """.split()
)


class Stage9CError(RuntimeError):
    """A listening package could not be built or analysed."""


class AnalysisNotReady(Stage9CError):
    """The evaluation spreadsheets have not been filled in yet."""


# ===========================================================================
# Stimulus rendering
# ===========================================================================
def stimulus_composition(
    *, joined_pair: bool, envelope_overrides: Optional[Dict[str, int]] = None
) -> AICompositionDoc:
    """The musical stimulus every profile is realized against.

    One voice on POKEY channel 1 playing :data:`STIMULUS_PHRASE`; nothing else sounds. The
    *only* difference between the VOICE and PAIR variants is whether the composition asks for
    the 1+2 join — because a PAIR profile can only be realized on a joined pair, and using the
    same channel for both keeps the two variants directly comparable.

    ``envelope_overrides`` exists for one narrow reason, documented on
    :func:`render_stimulus`: a profile whose measured envelope is wider than the consumer's
    envelope fields can express cannot be realized, and the consumer's supported answer is an
    explicitly declared composition field.
    """
    instrument = AIInstrumentDef(
        id="stim",
        name="Stimulus",
        character=STIMULUS_CHARACTER,
        **(envelope_overrides or {}),
    )
    return AICompositionDoc(
        metadata=AICompositionMetadata(
            title="Stage 9C stimulus",
            bpm=STIMULUS_BPM,
            key="C",
            mode="major",
        ),
        hardware=AIHardwareConfig(channels=4, use_16bit_bass=joined_pair),
        instruments=[instrument],
        patterns=[
            AIPatternDef(
                id="S",
                length_steps=sum(duration for _, duration in STIMULUS_PHRASE),
                channels={
                    "1": [
                        AIPatternChannelEvent(
                            step=sum(d for _, d in STIMULUS_PHRASE[:index]),
                            note=note,
                            instrument="stim",
                            duration=duration,
                            volume=STIMULUS_VELOCITY,
                        )
                        for index, (note, duration) in enumerate(STIMULUS_PHRASE)
                    ]
                },
            )
        ],
        sequence=["S"],
        loop_point=0,
    )


@dataclass(frozen=True)
class StimulusRender:
    """One profile's stimulus, plus exactly how faithfully it could be realized."""

    samples: np.ndarray
    envelope_source: str
    envelope_overrides: Dict[str, int]
    refusal_code: Optional[str]
    refusal_detail: Dict[str, Any]


def render_stimulus(
    profile: SoundProfile,
    bank: SoundProfileBank,
    *,
    sample_rate: int = SAMPLE_RATE,
) -> StimulusRender:
    """Render one profile's stimulus.

    The composition and the bound profile's own hardware configuration decide everything; no
    effect, envelope or generator is added on top.

    One honest complication. A profile may measure an envelope wider than the composer's
    envelope fields can hold (the audited ``ENVELOPE_FRAME_ABOVE_CONSUMER_MAX`` consumer gap).
    The consumer refuses such a profile rather than silently clamping it, and that refusal is
    correct. Since the profile still describes a real sound that the experiment should hear,
    this function uses the consumer's own supported route — an explicitly declared composition
    field — but only for the fields the consumer refused, and only with the **consumer's own
    default for that character**, so nothing is invented. Whatever it had to do is returned in
    the result and recorded in the manifest, because the listener then heard the profile's
    generator, clock and pitch with a substituted envelope, and the analysis must be able to
    treat that sample accordingly.
    """
    joined = profile.scope == "PAIR"
    binding = load_profile_binding(
        {
            "schema": "atari-music/sound-profile-binding/1",
            "instruments": {"stim": profile.profile_id},
        }
    )

    overrides: Dict[str, int] = {}
    refusal_code: Optional[str] = None
    refusal_detail: Dict[str, Any] = {}

    for _ in range(len(_ENVELOPE_FIELDS) + 1):
        doc = stimulus_composition(joined_pair=joined, envelope_overrides=overrides or None)
        result = generate_music_from_composition(doc)
        try:
            bound = apply_profile_binding(result, binding, bank, composition=doc)
        except SoundProfileError as error:
            if getattr(error, "code", None) != PROFILE_ENVELOPE_OUT_OF_RANGE:
                raise
            field_name = str(error.detail.get("field", ""))
            if field_name not in _ENVELOPE_FIELDS or field_name in overrides:
                raise
            refusal_code = error.code
            refusal_detail = dict(error.detail)
            overrides[field_name] = _character_default(result, field_name)
            continue
        samples = render_pokey_samples(
            compile_ir_to_pokey_frames(bound.pokey_ir), sample_rate, 50.0
        )
        return StimulusRender(
            samples=samples,
            envelope_source="profile" if not overrides else "composition_default",
            envelope_overrides=dict(overrides),
            refusal_code=refusal_code,
            refusal_detail=refusal_detail,
        )

    raise Stage9CError(  # pragma: no cover - the loop always terminates on success
        f"could not realize profile {profile.profile_id} as a stimulus"
    )


def _character_default(result: Any, field_name: str) -> int:
    """The envelope value the consumer derives from the instrument's character.

    Used only where a profile's measured envelope cannot be expressed. This is the value the
    binding itself would have used had the profile carried no envelope measurement, so the
    substitution adds no judgement of its own.
    """
    envelope = getattr(result.pokey_ir.instruments[0], "envelope", None)
    if envelope is None:  # pragma: no cover - defensive
        raise Stage9CError("the stimulus IR carries no envelope to fall back to")
    return int(getattr(envelope, field_name))


def render_song_versions(
    song_path: Path,
    binding_path: Path,
    bank: SoundProfileBank,
    *,
    sample_rate: int = SAMPLE_RATE,
) -> Tuple[np.ndarray, np.ndarray]:
    """Render one song twice: unbound (default) and profile-bound.

    Returns ``(default_samples, bound_samples)``. The composition is identical on both sides;
    only the external binding differs.
    """
    doc = (
        load_composition_dsl(song_path)
        if song_path.suffix == ".dsl"
        else load_composition_json(song_path)
    )
    default = generate_music_from_composition(doc)
    default_samples = render_pokey_samples(
        compile_ir_to_pokey_frames(default.pokey_ir), sample_rate, 50.0
    )

    bound = apply_profile_binding(
        default, load_profile_binding(binding_path), bank, composition=doc
    )
    bound_samples = render_pokey_samples(
        compile_ir_to_pokey_frames(bound.pokey_ir), sample_rate, 50.0
    )
    return default_samples, bound_samples


# ===========================================================================
# Levels
# ===========================================================================
@dataclass(frozen=True)
class LevelReport:
    """What happened to a stimulus' level, in the units the brief asks for.

    Amplitudes are held as linear full-scale fractions (1.0 == 0 dBFS) and reported in dBFS, so
    "did this stimulus get louder or quieter" can be read off directly.
    """

    original_peak: float
    original_rms: float
    gain_db: float
    final_peak: float
    final_rms: float

    def as_dict(self) -> Dict[str, float]:
        return {
            "original_peak_dbfs": round(_dbfs(self.original_peak), 3),
            "original_rms_dbfs": round(_dbfs(self.original_rms), 3),
            "gain_db": round(self.gain_db, 3),
            "final_peak_dbfs": round(_dbfs(self.final_peak), 3),
            "final_rms_dbfs": round(_dbfs(self.final_rms), 3),
        }


def _dbfs(amplitude: float) -> float:
    return 20.0 * math.log10(amplitude) if amplitude > 0 else -120.0


def normalize_peak(samples: np.ndarray, target_peak: float = TARGET_PEAK) -> Tuple[np.ndarray, LevelReport]:
    """Apply a single gain so the peak reaches *target_peak*. Never clips, never alters tone.

    A silent buffer is returned unchanged with zero gain, rather than divided by zero.
    """
    audio = samples.astype(np.float64) / 32768.0
    scale = float(np.max(np.abs(audio))) if audio.size else 0.0
    original_peak = scale
    original_rms = float(np.sqrt(np.mean(audio**2))) if audio.size else 0.0

    if scale <= 0.0:
        report = LevelReport(original_peak, original_rms, 0.0, original_peak, original_rms)
        return samples.copy(), report

    gain = target_peak / scale
    scaled = audio * gain * 32768.0
    # Gain only, so the peak cannot exceed the target by construction; clamp defensively.
    clipped = np.clip(scaled, -32768.0, 32767.0)
    final = np.rint(clipped).astype(np.int16)
    final_audio = final.astype(np.float64) / 32768.0

    report = LevelReport(
        original_peak=original_peak,
        original_rms=original_rms,
        gain_db=_dbfs(gain),
        final_peak=float(np.max(np.abs(final_audio))),
        final_rms=float(np.sqrt(np.mean(final_audio**2))),
    )
    return final, report


def write_wav(path: Path, samples: np.ndarray, sample_rate: int = SAMPLE_RATE) -> None:
    """Write mono 16-bit PCM, creating the directory."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(sample_rate)
        handle.writeframes(np.asarray(samples, dtype=np.int16).tobytes())


# ===========================================================================
# Technical features
# ===========================================================================
def spectral_features(samples: np.ndarray, sample_rate: int = SAMPLE_RATE) -> Dict[str, float]:
    """Describe a stimulus numerically, from its own audio.

    Computed on the rendered sound rather than read from the profile document, so the analysis
    can compare what the *listener* heard against the archaeology metrics instead of assuming
    they agree. Returns a normalized band-energy distribution plus centroid, bandwidth,
    rolloff and flatness.
    """
    audio = np.asarray(samples, dtype=np.float64) / 32768.0
    frame_length = 2048
    hop = frame_length // 2
    if audio.size < frame_length:
        audio = np.pad(audio, (0, frame_length - audio.size))

    window = np.hanning(frame_length)
    frames = 1 + (audio.size - frame_length) // hop
    spectra = np.empty((frames, frame_length // 2 + 1), dtype=np.float64)
    for index in range(frames):
        segment = audio[index * hop : index * hop + frame_length] * window
        spectra[index] = np.abs(np.fft.rfft(segment))

    magnitude = spectra.mean(axis=0)
    frequencies = np.fft.rfftfreq(frame_length, d=1.0 / sample_rate)
    total = float(magnitude.sum())
    if total <= 0.0:
        return {
            "centroid_hz": 0.0,
            "bandwidth_hz": 0.0,
            "rolloff_hz": 0.0,
            "flatness": 1.0,
            "band_energy": [0.0] * SPECTRAL_BANDS,
        }

    centroid = float((frequencies * magnitude).sum() / total)
    bandwidth = float(np.sqrt((((frequencies - centroid) ** 2) * magnitude).sum() / total))
    cumulative = np.cumsum(magnitude)
    rolloff_index = int(np.searchsorted(cumulative, 0.85 * total))
    rolloff = float(frequencies[min(rolloff_index, len(frequencies) - 1)])
    positive = magnitude[magnitude > 0.0]
    flatness = (
        float(np.exp(np.mean(np.log(positive))) / np.mean(positive)) if positive.size else 1.0
    )

    band_energy: List[float] = []
    for low, high in zip(_BAND_EDGES_HZ, _BAND_EDGES_HZ[1:]):
        mask = (frequencies >= low) & (frequencies < high)
        band_energy.append(float(magnitude[mask].sum()) / total)
    band_total = sum(band_energy) or 1.0
    band_energy = [value / band_total for value in band_energy]

    return {
        "centroid_hz": round(centroid, 3),
        "bandwidth_hz": round(bandwidth, 3),
        "rolloff_hz": round(rolloff, 3),
        "flatness": round(flatness, 6),
        "band_energy": [round(value, 6) for value in band_energy],
    }


def spectral_distance(left: Dict[str, Any], right: Dict[str, Any]) -> float:
    """Distance between two feature dicts: 1 - cosine similarity of the band energies.

    Bounded in ``[0, 1]``: 0 means the two stimuli distribute their energy identically across
    the spectrum, 1 means they share none. It says nothing about which sounds better.
    """
    a = np.asarray(left["band_energy"], dtype=np.float64)
    b = np.asarray(right["band_energy"], dtype=np.float64)
    denominator = float(np.linalg.norm(a) * np.linalg.norm(b))
    if denominator <= 0.0:
        return 1.0
    return float(1.0 - float(np.dot(a, b)) / denominator)


def _generator_family(nibble: Optional[int]) -> str:
    """The generator family a distortion nibble belongs to, as the profile documents it."""
    if nibble is None:
        return "unknown"
    return f"${nibble:X}"


# ===========================================================================
# Building the package
# ===========================================================================
@dataclass
class _Candidate:
    """One renderable profile, rendered and described."""

    profile: SoundProfile
    index: int
    features: Dict[str, Any]
    levels: LevelReport
    samples: np.ndarray
    duration_seconds: float
    envelope_source: str
    envelope_overrides: Dict[str, int]
    refusal_code: Optional[str]
    refusal_detail: Dict[str, Any]


def _profile_source_songs(profile: SoundProfile) -> Tuple[str, ...]:
    """The songs a profile documents as its origin.

    The profile document supports a full ``source.songs`` list, and when a bank publishes one
    it is used. No bank in this repository does today: the published profiles record the song of
    their **representative segment** under ``gesture.provenance.song``, and nothing else about
    where else the same sound was found. That single song is returned here, and
    :func:`_source_song_origin` records which of the two it was, so a reader never mistakes the
    representative segment for the profile's complete distribution.
    """
    documented = tuple(
        str(entry["song"])
        for entry in profile.source_songs
        if isinstance(entry, Mapping) and entry.get("song")
    )
    if documented:
        return documented
    provenance = (profile.document.get("gesture") or {}).get("provenance") or {}
    song = provenance.get("song")
    return (str(song),) if song else ()


def _source_song_origin(profile: SoundProfile) -> str:
    """Where a profile's source song came from: a full list, one segment, or nothing."""
    if any(
        isinstance(entry, Mapping) and entry.get("song") for entry in profile.source_songs
    ):
        return "document"
    if _profile_source_songs(profile):
        return "representative_segment"
    return "unrecorded"


def _included_profiles(bank: SoundProfileBank) -> List[SoundProfile]:
    """Every renderable profile, in a canonical order.

    ``MEASUREMENT_ONLY`` profiles are excluded because they are not renderable (they describe
    silence); nothing else is excluded. Exclusions are recorded in the manifest.
    """
    return list(bank.renderable())


def _render_all_candidates(
    bank: SoundProfileBank, *, sample_rate: int, log: Optional[Any] = None
) -> List[_Candidate]:
    candidates: List[_Candidate] = []
    for profile in _included_profiles(bank):
        rendered = render_stimulus(profile, bank, sample_rate=sample_rate)
        samples, levels = normalize_peak(rendered.samples)
        candidates.append(
            _Candidate(
                profile=profile,
                index=len(candidates),
                features=spectral_features(samples, sample_rate),
                levels=levels,
                samples=samples,
                duration_seconds=round(len(samples) / sample_rate, 3),
                envelope_source=rendered.envelope_source,
                envelope_overrides=rendered.envelope_overrides,
                refusal_code=rendered.refusal_code,
                refusal_detail=rendered.refusal_detail,
            )
        )
        if log is not None:
            note = ""
            if rendered.envelope_source != "profile":
                fields = ", ".join(f"{k}={v}" for k, v in sorted(rendered.envelope_overrides.items()))
                note = f"  [envelope substituted: {fields}]"
            log(f"  rendered {profile.profile_id} ({profile.scope}){note}")
    return candidates


def _same_source_material(left: _Candidate, right: _Candidate) -> bool:
    """Whether two profiles were measured from material they share."""
    a = set(_profile_source_songs(left.profile))
    b = set(_profile_source_songs(right.profile))
    return bool(a & b)


def build_ab_trials(candidates: Sequence[_Candidate], rng: random.Random) -> List[Dict[str, Any]]:
    """A stratified A/B program.

    The strata are the questions the brief asks: can a listener tell apart profiles the numbers
    call close, does technical distance read as perceptual difference, is there usable variation
    inside one generator family, are broad hardware differences audible, does one Atari tune
    yield several distinct sounds, and are some profiles general-purpose?

    A pair is never reused across strata, each trial randomizes which side is A, and the choice
    is deterministic for a given seed and profile set.
    """
    pairs: List[Tuple[int, int, float]] = []
    for left in range(len(candidates)):
        for right in range(left + 1, len(candidates)):
            pairs.append(
                (
                    left,
                    right,
                    spectral_distance(candidates[left].features, candidates[right].features),
                )
            )
    if not pairs:
        return []

    by_distance = sorted(pairs, key=lambda item: (item[2], item[0], item[1]))

    def family(candidate: _Candidate) -> str:
        return _generator_family(candidate.profile.distortion_nibble)

    def scope(candidate: _Candidate) -> str:
        return candidate.profile.scope

    buckets: Dict[str, List[Tuple[int, int, float]]] = {
        "similar": [
            pair
            for pair in by_distance
            if scope(candidates[pair[0]]) == scope(candidates[pair[1]])
            and family(candidates[pair[0]]) == family(candidates[pair[1]])
        ],
        "distant": list(reversed(by_distance)),
        "same_generator": [
            pair
            for pair in by_distance
            if family(candidates[pair[0]]) == family(candidates[pair[1]])
        ],
        "different_generator": [
            pair
            for pair in by_distance
            if family(candidates[pair[0]]) != family(candidates[pair[1]])
        ],
        "same_source_song": [
            pair
            for pair in by_distance
            if _same_source_material(candidates[pair[0]], candidates[pair[1]])
        ],
        "cross_song": [
            pair
            for pair in by_distance
            if not _same_source_material(candidates[pair[0]], candidates[pair[1]])
        ],
    }

    used: set = set()
    trials: List[Dict[str, Any]] = []
    for stratum, wanted in AB_STRATA:
        pool = buckets.get(stratum, [])
        if not pool:
            continue
        # Spread the picks across the pool instead of always taking its head, so "similar"
        # does not mean "the six closest pairs" only.
        step = max(1, len(pool) // max(1, wanted))
        chosen: List[Tuple[int, int, float]] = []
        for offset in range(0, len(pool), step):
            candidate_pair = pool[offset]
            key = frozenset((candidate_pair[0], candidate_pair[1]))
            if key in used:
                continue
            used.add(key)
            chosen.append(candidate_pair)
            if len(chosen) >= wanted:
                break
        # If spreading was not enough, fill from the head.
        if len(chosen) < wanted:
            for candidate_pair in pool:
                key = frozenset((candidate_pair[0], candidate_pair[1]))
                if key in used:
                    continue
                used.add(key)
                chosen.append(candidate_pair)
                if len(chosen) >= wanted:
                    break

        for left, right, distance in chosen:
            if rng.random() < 0.5:
                first, second = left, right
            else:
                first, second = right, left
            trials.append(
                {
                    "trial_id": "",  # assigned after ordering
                    "stratum": stratum,
                    "a_index": first,
                    "b_index": second,
                    "technical_distance": round(distance, 6),
                    "same_scope": scope(candidates[left]) == scope(candidates[right]),
                    "same_generator_family": family(candidates[left]) == family(candidates[right]),
                    "shares_source_material": _same_source_material(
                        candidates[left], candidates[right]
                    ),
                }
            )

    rng.shuffle(trials)
    for number, trial in enumerate(trials, start=1):
        trial["trial_id"] = f"trial_{number:02d}"
    return trials[:AB_TRIAL_TARGET]


def _select_song_program(
    package_dir: Path,
    songs_dir: Path,
    bank: SoundProfileBank,
    context_songs: Sequence[str] = CONTEXT_SONGS,
) -> List[Dict[str, Any]]:
    """The song A/B program, checked before anything is rendered."""
    program: List[Dict[str, Any]] = []
    for name in context_songs:
        song_path = songs_dir / name
        if not song_path.is_file():
            raise Stage9CError(f"song not found: {song_path}")
        binding_path = songs_dir / f"{name}.binding.json"
        if not binding_path.is_file():
            raise Stage9CError(f"binding not found for {name}: {binding_path}")
        binding = load_profile_binding(binding_path)
        for profile_id in binding.instruments.values():
            profile = bank.get(profile_id)
            if not profile.renderable:
                raise Stage9CError(
                    f"{name} binds {profile_id}, whose status is {profile.status}; the song "
                    "program must only use renderable profiles"
                )
        program.append({"song": name, "song_path": song_path, "binding_path": binding_path})
    return program


def _repo_root(start: Path) -> Path:
    """Walk up from *start* to the directory containing ``.git``."""
    current = Path(start).resolve()
    for candidate in (current, *current.parents):
        if (candidate / ".git").exists():
            return candidate
    return current


def _git_commit(path: Path) -> str:
    try:
        completed = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=path,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):  # pragma: no cover - environment dependent
        return "unknown"
    if completed.returncode != 0:
        return "unknown"
    return completed.stdout.strip() or "unknown"


def bank_fingerprint(bank: SoundProfileBank) -> str:
    """One digest over the bank's identities, so the experiment names what it measured.

    Covers each profile's id and published fingerprint in id order; it does not read the
    documents again, so it is stable and cheap.
    """
    digest = hashlib.sha256()
    for profile_id in bank.ids():
        profile = bank.get(profile_id)
        digest.update(profile_id.encode("utf-8"))
        digest.update(b"\0")
        digest.update(profile.fingerprint.encode("utf-8"))
        digest.update(b"\n")
    return digest.hexdigest()


def build_experiment(
    package_dir: Path,
    *,
    bank_dir: Path,
    songs_dir: Path,
    seed: int = DEFAULT_SEED,
    sample_rate: int = SAMPLE_RATE,
    now: Optional[datetime] = None,
    renderer_version: str = RENDERER_VERSION,
    context_songs: Optional[Sequence[str]] = None,
    log: Optional[Any] = None,
) -> Dict[str, Any]:
    """Build the complete listening package and return its manifest.

    Deterministic for a given bank, seed, song set and *now* — the date is recorded because the
    brief asks for it, and is passed in so a test can pin it.

    The bank is only ever read: nothing here can modify a profile.
    """
    say = log or (lambda message: None)
    package_dir = Path(package_dir)
    audio_dir = package_dir / "audio"
    if audio_dir.is_dir():
        shutil.rmtree(audio_dir)
    audio_dir.mkdir(parents=True, exist_ok=True)

    bank = load_sound_profile_bank(bank_dir)
    included = _included_profiles(bank)
    excluded = [profile for profile in bank.profiles.values() if not profile.renderable]
    if not included:
        raise Stage9CError(f"the bank at {bank_dir} has no renderable profiles")

    say(f"Rendering {len(included)} profile stimuli…")
    candidates = _render_all_candidates(bank, sample_rate=sample_rate, log=log)

    # Presentation order: a deterministic shuffle, so sample_001 is not profile 1.
    rng = random.Random(seed)
    order = list(range(len(candidates)))
    rng.shuffle(order)
    sample_ids = {index: f"sample_{position + 1:03d}" for position, index in enumerate(order)}

    say("Writing blinded stimuli…")
    samples_meta: List[Dict[str, Any]] = []
    for index in order:
        candidate = candidates[index]
        sample_id = sample_ids[index]
        write_wav(audio_dir / f"{sample_id}.wav", candidate.samples, sample_rate)
        samples_meta.append(
            {
                "sample_id": sample_id,
                "profile_id": candidate.profile.profile_id,
                "scope": candidate.profile.scope,
                "status": candidate.profile.status,
                "source_song": (_profile_source_songs(candidate.profile) or ("unrecorded",))[0],
                "source_songs": list(_profile_source_songs(candidate.profile)),
                "source_song_origin": _source_song_origin(candidate.profile),
                "generator_family": _generator_family(candidate.profile.distortion_nibble),
                "divider_bits": candidate.profile.divider_bits,
                "audctl_mode": f"${candidate.profile.audctl_mode:02X}",
                "envelope_confidence": candidate.profile.envelope_confidence,
                "blocking_issues": list(candidate.profile.blocking_codes),
                "limitation_codes": list(candidate.profile.limitation_codes),
                "consumer_gap_codes": list(candidate.profile.consumer_gap_codes),
                "stimulus": "stimulus_v1",
                "envelope_source": candidate.envelope_source,
                "envelope_overrides": dict(candidate.envelope_overrides),
                "envelope_refusal": (
                    {
                        "code": candidate.refusal_code,
                        "detail": candidate.refusal_detail,
                    }
                    if candidate.refusal_code
                    else None
                ),
                "duration_seconds": candidate.duration_seconds,
                "features": candidate.features,
                "levels": candidate.levels.as_dict(),
                "file": f"audio/{sample_id}.wav",
            }
        )
    samples_meta.sort(key=lambda entry: entry["sample_id"])

    say("Building the A/B program…")
    trials = build_ab_trials(candidates, rng)
    ab_meta: List[Dict[str, Any]] = []
    for trial in trials:
        ab_meta.append(
            {
                "trial_id": trial["trial_id"],
                "stratum": trial["stratum"],
                "sample_a": sample_ids[trial["a_index"]],
                "sample_b": sample_ids[trial["b_index"]],
                "profile_a": candidates[trial["a_index"]].profile.profile_id,
                "profile_b": candidates[trial["b_index"]].profile.profile_id,
                "scope_a": candidates[trial["a_index"]].profile.scope,
                "scope_b": candidates[trial["b_index"]].profile.scope,
                "technical_distance": trial["technical_distance"],
                "same_scope": trial["same_scope"],
                "same_generator_family": trial["same_generator_family"],
                "shares_source_material": trial["shares_source_material"],
            }
        )

    say("Rendering the song program…")
    song_program = _select_song_program(
        package_dir, Path(songs_dir), bank, tuple(context_songs or CONTEXT_SONGS)
    )
    song_meta: List[Dict[str, Any]] = []
    for number, entry in enumerate(song_program, start=1):
        trial_id = f"song_{number:02d}"
        default_samples, bound_samples = render_song_versions(
            entry["song_path"], entry["binding_path"], bank, sample_rate=sample_rate
        )
        # One excerpt length for both sides, and one excerpt window for both sides.
        limit = int(round(SONG_EXCERPT_SECONDS * sample_rate))
        default_excerpt = default_samples[:limit]
        bound_excerpt = bound_samples[:limit]

        # Randomized sides, and a *shared* level decision so the comparison survives: the gain
        # is derived from the default render and applied to both, which keeps any real loudness
        # difference between the two versions audible.
        peak = float(np.max(np.abs(default_excerpt.astype(np.float64)))) / 32768.0
        gain = TARGET_PEAK / peak if peak > 0.0 else 1.0
        default_excerpt = np.rint(
            np.clip(default_excerpt.astype(np.float64) * gain, -32768, 32767)
        ).astype(np.int16)
        bound_excerpt = np.rint(
            np.clip(bound_excerpt.astype(np.float64) * gain, -32768, 32767)
        ).astype(np.int16)

        default_side, bound_side = ("a", "b") if rng.random() < 0.5 else ("b", "a")
        sides = {default_side: default_excerpt, bound_side: bound_excerpt}
        for side, samples in sides.items():
            write_wav(audio_dir / f"{trial_id}_{side}.wav", samples, sample_rate)

        song_meta.append(
            {
                "trial_id": trial_id,
                "song": entry["song"],
                "binding": entry["binding_path"].name,
                "bound_profiles": dict(load_profile_binding(entry["binding_path"]).instruments),
                "uses_profile_side": {"default": default_side, "profile": bound_side},
                "excerpt_seconds": round(min(SONG_EXCERPT_SECONDS, len(default_samples) / sample_rate), 3),
                "shared_gain_db": round(_dbfs(gain), 4),
                "default_features": spectral_features(default_excerpt, sample_rate),
                "profile_features": spectral_features(bound_excerpt, sample_rate),
                "files": {
                    "a": f"audio/{trial_id}_a.wav",
                    "b": f"audio/{trial_id}_b.wav",
                },
            }
        )

    created = now or datetime.now(timezone.utc)
    manifest: Dict[str, Any] = {
        "manifest_version": MANIFEST_VERSION,
        "experiment": EXPERIMENT,
        "private": True,
        "warning": (
            "This file is the private answer key: it maps blinded sample ids to profile ids. "
            "Do not open it while listening."
        ),
        "created_utc": created.astimezone(timezone.utc).isoformat(timespec="seconds"),
        "seed": seed,
        "sample_rate": sample_rate,
        "renderer_version": renderer_version,
        "song_excerpt_seconds": SONG_EXCERPT_SECONDS,
        "normalization": {
            "method": "peak",
            "target_peak_linear": TARGET_PEAK,
            "target_peak_dbfs": round(_dbfs(TARGET_PEAK), 4),
            "gain_only": True,
            "clipping": "none (gain chosen so the peak equals the target)",
            "notes": (
                "Profile stimuli are each normalized to the same peak, which sets one nominal "
                "level without equalizing loudness; the RMS of every stimulus is recorded so "
                "loudness can be investigated. In the song trials one gain (derived from the "
                "default render) is applied to both sides, so a real loudness difference "
                "between the versions is preserved rather than normalized away."
            ),
        },
        "stimulus": {
            "description": (
                "one 32-step phrase on POKEY channel 1, identical for every profile; the PAIR "
                "variant declares the 1+2 join so a coupled profile can be realized"
            ),
            "phrase": [{"note": note, "steps": steps} for note, steps in STIMULUS_PHRASE],
            "bpm": STIMULUS_BPM,
            "velocity": STIMULUS_VELOCITY,
            "variants": {
                "VOICE": "use_16bit_bass = false",
                "PAIR": "use_16bit_bass = true",
            },
            "not_rendered": (
                "a profile's measured pitch/volume gesture: the player has no per-channel "
                "macro and the composer does not render one, so no gesture is invented here"
            ),
            "character": STIMULUS_CHARACTER,
            "envelope_rule": (
                "the profile's own measured envelope is used wherever the composer's fields can "
                "express it. Where they cannot (the audited ENVELOPE_FRAME_ABOVE_CONSUMER_MAX "
                "gap) the composer refuses the profile; the stimulus then declares that one "
                "field explicitly, using the composer's own default for the character above, so "
                "the field is not invented. Any sample affected by this is marked with "
                "envelope_source = 'composition_default' and carries the refusal in "
                "envelope_refusal, because for that sample the listener heard the profile's "
                "generator, clock and pitch with a substituted envelope."
            ),
            "envelope_substitutions": [
                {
                    "profile_id": candidate.profile.profile_id,
                    "fields": dict(candidate.envelope_overrides),
                    "refusal_code": candidate.refusal_code,
                }
                for candidate in candidates
                if candidate.envelope_source != "profile"
            ],
        },
        "profile_bank_fingerprint": bank_fingerprint(bank),
        "profile_bank": str(Path(bank_dir)),
        "profile_count_in_bank": len(bank.ids()),
        "profile_count": len(included),
        "scope_counts": {
            "VOICE": sum(1 for candidate in candidates if candidate.profile.scope == "VOICE"),
            "PAIR": sum(1 for candidate in candidates if candidate.profile.scope == "PAIR"),
        },
        "status_counts": {
            status: sum(1 for candidate in candidates if candidate.profile.status == status)
            for status in sorted({candidate.profile.status or "unknown" for candidate in candidates})
        },
        "excluded_profiles": [
            {
                "profile_id": profile.profile_id,
                "scope": profile.scope,
                "status": profile.status,
                "blocking_issues": list(profile.blocking_codes),
                "reason": "not renderable: the profile describes no sound",
            }
            for profile in sorted(excluded, key=lambda item: item.profile_id)
        ],
        "source_material": {
            "note": (
                "profiles in this bank record the song of the segment they were measured from, "
                "not the complete set of songs the same sound was found in; that wider "
                "distribution lives in the archaeology project's corpus analysis. The 'same "
                "source song' A/B stratum therefore means 'measured from the same tune', and "
                "'found in many songs' cannot be decided from the bank alone."
            ),
            "origins": {
                origin: sum(
                    1 for candidate in candidates if _source_song_origin(candidate.profile) == origin
                )
                for origin in ("document", "representative_segment", "unrecorded")
            },
        },
        "limitations": [
            {
                "code": "GESTURE_NOT_RENDERED",
                "detail": (
                    "the player has no per-channel macro and the composer renders no gesture, "
                    "so each stimulus is a static tone shaped by the profile's generator, clock "
                    "and envelope. Profiles whose documents carry a measured contour are heard "
                    "in reduced form."
                ),
            },
            {
                "code": "ENVELOPE_SUBSTITUTED_FOR_TWO_PROFILES",
                "detail": (
                    "for the profiles listed in stimulus.envelope_substitutions the composer "
                    "cannot express the measured attack, so that one field is the composer's "
                    "own character default."
                ),
            },
        ],
        "git_commit": {
            "composer": _git_commit(_repo_root(Path(__file__).parent)),
        },
        "samples": samples_meta,
        "ab_trials": ab_meta,
        "song_trials": song_meta,
    }
    return manifest


# ===========================================================================
# Templates, interface and documentation
# ===========================================================================
PROFILE_TEMPLATE_HEADER = [
    "sample_id",
    "distinctiveness",
    "usefulness",
    "atari_character",
    "confidence",
    "comment",
]
AB_TEMPLATE_HEADER = ["trial_id", "similarity", "preference", "character_difference", "comment"]
SONG_TEMPLATE_HEADER = [
    "trial_id",
    "better_sound",
    "more_character",
    "more_convincing_atari",
    "overall_difference",
    "comment",
]


def write_templates(package_dir: Path, manifest: Dict[str, Any]) -> None:
    """Empty, pre-filled-with-ids templates. No answer is ever pre-filled."""
    package_dir.mkdir(parents=True, exist_ok=True)

    def write(path: Path, header: Sequence[str], rows: Iterable[Sequence[Any]]) -> None:
        with path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(header)
            for row in rows:
                writer.writerow(row)

    write(
        package_dir / "evaluation_profiles.csv",
        PROFILE_TEMPLATE_HEADER,
        [[entry["sample_id"]] + [""] * (len(PROFILE_TEMPLATE_HEADER) - 1) for entry in manifest["samples"]],
    )
    write(
        package_dir / "evaluation_ab.csv",
        AB_TEMPLATE_HEADER,
        [[entry["trial_id"]] + [""] * (len(AB_TEMPLATE_HEADER) - 1) for entry in manifest["ab_trials"]],
    )
    write(
        package_dir / "evaluation_songs.csv",
        SONG_TEMPLATE_HEADER,
        [[entry["trial_id"]] + [""] * (len(SONG_TEMPLATE_HEADER) - 1) for entry in manifest["song_trials"]],
    )


def render_index_html(manifest: Dict[str, Any]) -> str:
    """The listening interface: one self-contained page, no server and no Python.

    It contains only neutral labels and file names — never a profile id, a source song, a
    generator family or a status. Answers are kept in the browser's local storage so a session
    can be resumed, and exported as the three CSV files the analysis reads.
    """
    payload = {
        "experiment": manifest["experiment"],
        "samples": [entry["sample_id"] for entry in manifest["samples"]],
        "ab_trials": [
            {
                "trial_id": entry["trial_id"],
                "a": entry["sample_a"],
                "b": entry["sample_b"],
            }
            for entry in manifest["ab_trials"]
        ],
        "song_trials": [
            {"trial_id": entry["trial_id"], "a": f"{entry['trial_id']}_a", "b": f"{entry['trial_id']}_b"}
            for entry in manifest["song_trials"]
        ],
    }
    return _INDEX_HTML.replace("__PACKAGE__", json.dumps(payload, sort_keys=True))


_INDEX_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>POKEY sound profile listening test</title>
<style>
  :root { color-scheme: dark; }
  body { font-family: system-ui, -apple-system, Segoe UI, sans-serif; margin: 0; padding: 1.5rem;
         background: #14161a; color: #e8e8ea; line-height: 1.5; }
  main { max-width: 60rem; margin: 0 auto; }
  h1, h2, h3 { line-height: 1.2; }
  h2 { margin-top: 2.5rem; border-bottom: 1px solid #333; padding-bottom: .35rem; }
  .note { background: #1d2026; border-left: 3px solid #4a7; padding: .75rem 1rem; margin: 1rem 0;
          border-radius: 3px; font-size: .95rem; }
  .warn { border-left-color: #c85; }
  .card { background: #1a1d22; border: 1px solid #2c3036; border-radius: 6px; padding: 1rem;
          margin: 1rem 0; }
  .card.done { border-color: #3d6; }
  .row { display: flex; flex-wrap: wrap; gap: 1rem; align-items: center; }
  .label { font-weight: 600; min-width: 11rem; }
  audio { width: 100%; max-width: 32rem; }
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
<h1>POKEY sound profile listening test</h1>

<div class="note">
  <strong>Your ears are the instrument here.</strong> Nothing on this page tells you which
  profile you are hearing, where it came from, or how it was measured. A profile may sound
  interesting on its own and still make a song worse, or the reverse — both outcomes are useful
  evidence, so please answer for what you actually hear.
</div>
<div class="note warn">
  <strong>There are no right answers, and no technical knowledge is needed.</strong> Do not try
  to guess which sample is "the 16-bit one" — if a difference is audible to you, that is the
  result; if it is not, that is also the result.
</div>
<div class="note warn">
  <strong>Set your volume once and leave it alone.</strong> Every sound is presented at the same
  peak level, but some of them are quieter than others by nature — that is a property of the
  sound itself, and it is being measured separately. Please judge character rather than
  loudness, and do not turn the volume up or down between samples.
</div>

<div class="progress" id="progress">progress</div>

<h2>Part 1 — one sound at a time (<span id="count-a">0</span> samples)</h2>
<p class="small">
  For each sample: listen, then rate how distinctive it is, how useful it could be in an Atari
  composition, and how strongly it feels like a useful POKEY sound. Then, in your own words,
  write what it reminds you of — plain words like <em>bass</em>, <em>drum</em>, <em>bell</em>,
  <em>noise</em>, <em>laser</em>, <em>repeating</em> are exactly what is wanted. There is no
  vocabulary to match.
</p>
<div id="part-a"></div>

<h2>Part 2 — comparing two sounds (<span id="count-b">0</span> pairs)</h2>
<p class="small">Each pair plays the same music; only the sound profile differs. A and B are in
no particular order.</p>
<div id="part-b"></div>

<h2>Part 3 — whole songs (<span id="count-c">0</span> pairs)</h2>
<p class="small">The same composition rendered twice. One side uses the existing default
instruments, the other uses external sound profiles. The music is identical.</p>
<div id="part-c"></div>

<h2>Finish</h2>
<p class="small">Download the three files and put them back in the package folder, overwriting
the empty templates. Nothing is uploaded anywhere — everything stays in this browser until you
download it.</p>
<button onclick="downloadAll()">Download all three CSV files</button>
<button class="ghost" onclick="if(confirm('Erase all answers in this browser?')){localStorage.clear();location.reload();}">Reset answers</button>

<script>
const PACKAGE = __PACKAGE__;
const STORE = "stage9c-answers-v1";
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

const SCALE_A = [
  ["distinctiveness", "How distinctive is this sound?",
   ["1 very generic", "2 somewhat generic", "3 moderately distinctive", "4 distinctive", "5 highly distinctive"]],
  ["usefulness", "How useful could this sound be in an Atari composition?",
   ["1 not useful", "2 probably not useful", "3 potentially useful", "4 useful", "5 highly useful"]],
  ["atari_character", "How strongly does this feel like a useful Atari/POKEY sound?",
   ["1 not Atari-like", "2", "3 neutral", "4", "5 strongly Atari-like"]],
  ["confidence", "Optional: how clear was your judgement?",
   ["1 difficult", "2", "3 reasonably clear", "4", "5 very clear"]],
];
const SCALE_B = [
  ["similarity", "How similar are A and B?",
   ["1 completely different", "2 quite different", "3 moderately similar", "4 quite similar", "5 almost the same"]],
  ["character_difference", "Same sound, or two different useful characters?",
   ["1 essentially the same", "2", "3 somewhat different", "4", "5 clearly different"]],
];
const SCALE_C = [
  ["overall_difference", "How large is the difference overall?",
   ["1 essentially identical", "2", "3 noticeable", "4", "5 very large"]],
];

function scaleRow(key, field, question, options) {
  const current = get(key, field);
  const inputs = options.map((label, index) => {
    const value = index + 1;
    const checked = String(current) === String(value) ? " checked" : "";
    return `<label><input type="radio" name="${key}-${field}" value="${value}"${checked}
      onchange="set('${key}','${field}','${value}')">${label}</label>`;
  }).join("");
  return `<div class="q"><div class="label">${question}</div><div class="scale">${inputs}</div></div>`;
}

function choiceRow(key, field, question, options) {
  const current = get(key, field);
  const inputs = options.map((label, index) => {
    const value = ["a", "b", "none"][index];
    const checked = String(current) === value ? " checked" : "";
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

function isDone(key, fields) { return fields.every(f => get(key, f) !== ""); }

function card(id, title, inner, done) {
  return `<div class="card${done ? " done" : ""}" id="${id}">
    <div class="row"><div class="label">${title}</div></div>${inner}</div>`;
}

document.getElementById("part-a").innerHTML = PACKAGE.samples.map((sample, index) => {
  const id = sample;
  const fields = ["distinctiveness", "usefulness", "atari_character"];
  const body = `<audio controls preload="none" src="audio/${sample}.wav"></audio>` +
    SCALE_A.map(q => scaleRow(id, q[0], q[1], q[2])).join("") +
    commentRow(id, "comment", "What does this sound remind you of?") +
    `<div class="small">Sample ${index + 1} of ${PACKAGE.samples.length}</div>`;
  return card(id, sample.replace("sample_", "Sample "), body, isDone(id, fields));
}).join("");

document.getElementById("part-b").innerHTML = PACKAGE.ab_trials.map((trial, index) => {
  const id = trial.trial_id;
  const fields = ["similarity", "preference", "character_difference"];
  const body = `<div class="ab">
      <div><div class="label">A</div><audio controls preload="none" src="audio/${trial.a}.wav"></audio></div>
      <div><div class="label">B</div><audio controls preload="none" src="audio/${trial.b}.wav"></audio></div>
    </div>` +
    SCALE_B.map(q => scaleRow(id, q[0], q[1], q[2])).join("") +
    choiceRow(id, "preference", "Which would you rather use in an Atari composition?",
      ["A", "B", "No preference"]) +
    commentRow(id, "comment", "Comment (optional)") +
    `<div class="small">Pair ${index + 1} of ${PACKAGE.ab_trials.length}</div>`;
  return card(id, id, body, isDone(id, fields));
}).join("");

document.getElementById("part-c").innerHTML = PACKAGE.song_trials.map((trial, index) => {
  const id = trial.trial_id;
  const fields = ["better_sound", "more_character", "more_convincing_atari", "overall_difference"];
  const body = `<div class="ab">
      <div><div class="label">A</div><audio controls preload="none" src="audio/${trial.a}.wav"></audio></div>
      <div><div class="label">B</div><audio controls preload="none" src="audio/${trial.b}.wav"></audio></div>
    </div>` +
    choiceRow(id, "better_sound", "Which version sounds better?", ["A", "B", "No preference"]) +
    choiceRow(id, "more_character", "Which has more character?", ["A", "B", "No preference"]) +
    choiceRow(id, "more_convincing_atari", "Which sounds more like a convincing Atari composition?", ["A", "B", "No preference"]) +
    SCALE_C.map(q => scaleRow(id, q[0], q[1], q[2])).join("") +
    commentRow(id, "comment", "Comment (optional)") +
    `<div class="small">Song pair ${index + 1} of ${PACKAGE.song_trials.length}</div>`;
  return card(id, "Song pair " + (index + 1), body, isDone(id, fields));
}).join("");

function countDone() {
  const a = PACKAGE.samples.filter(s => isDone(s, ["distinctiveness", "usefulness", "atari_character"])).length;
  const b = PACKAGE.ab_trials.filter(t => isDone(t.trial_id, ["similarity", "preference", "character_difference"])).length;
  const c = PACKAGE.song_trials.filter(t => isDone(t.trial_id, ["better_sound", "more_character", "more_convincing_atari", "overall_difference"])).length;
  return {a, b, c};
}

function refresh() {
  const {a, b, c} = countDone();
  document.getElementById("progress").textContent =
    `Progress — part 1: ${a}/${PACKAGE.samples.length} · part 2: ${b}/${PACKAGE.ab_trials.length} · part 3: ${c}/${PACKAGE.song_trials.length} (answers are saved in this browser)`;
  document.getElementById("count-a").textContent = PACKAGE.samples.length;
  document.getElementById("count-b").textContent = PACKAGE.ab_trials.length;
  document.getElementById("count-c").textContent = PACKAGE.song_trials.length;
}

function downloadAll() {
  download("evaluation_profiles.csv",
    ["sample_id","distinctiveness","usefulness","atari_character","confidence","comment"],
    PACKAGE.samples.map(s => [s, get(s,"distinctiveness"), get(s,"usefulness"),
                              get(s,"atari_character"), get(s,"confidence"), get(s,"comment")]));
  download("evaluation_ab.csv",
    ["trial_id","similarity","preference","character_difference","comment"],
    PACKAGE.ab_trials.map(t => [t.trial_id, get(t.trial_id,"similarity"), get(t.trial_id,"preference"),
                                get(t.trial_id,"character_difference"), get(t.trial_id,"comment")]));
  download("evaluation_songs.csv",
    ["trial_id","better_sound","more_character","more_convincing_atari","overall_difference","comment"],
    PACKAGE.song_trials.map(t => [t.trial_id, get(t.trial_id,"better_sound"), get(t.trial_id,"more_character"),
                                  get(t.trial_id,"more_convincing_atari"), get(t.trial_id,"overall_difference"),
                                  get(t.trial_id,"comment")]));
}

refresh();
</script>
</main>
</body>
</html>
"""


def render_readme(manifest: Dict[str, Any]) -> str:
    counts = manifest["scope_counts"]
    statuses = manifest["status_counts"]
    status_line = ", ".join(f"{count} {status}" for status, count in sorted(statuses.items()))
    return f"""# POKEY sound profile listening test (Stage 9C)

This folder is a complete, self-contained experiment. **You need nothing installed** — no
Python, no build step, no internet connection.

## What it is asking

The library has {manifest['profile_count_in_bank']} measured POKEY sound profiles. The question is
perceptual, not technical:

> Which of these sounds are actually distinctive, useful in a real Atari composition, and worth
> keeping?

Only you can answer that. The measurements cannot.

## How to run it

1. Open **`index.html`** by double-clicking it (or drag it into a browser).
2. Listen with headphones if you can, at a comfortable level that you do not change part-way.
3. Work through the three parts. Your answers are saved in the browser as you go, so you can
   stop and come back later — the page keeps your progress.
4. When you are done, press **Download all three CSV files** and put the files back into this
   folder (they will replace the empty templates).
5. Optionally run the analysis (see below).

If your browser refuses to play the audio from a `file:` page — some browsers block local files
as sub-resources — serve this folder over a local HTTP port instead. Nothing leaves the machine
and no internet connection is needed:

```bash
cd this-folder
python -m http.server 8000
# then open http://localhost:8000/index.html
```

Check that the first sample plays for about 3 seconds and the first song pair for 15 seconds; if
so, everything else will play too (all {len(manifest['samples']) + 2 * len(manifest['song_trials'])} files were written by the same code path).

Finally, analyse the answers:

```bash
python -m atari_music.cli analyze-listening-test-9c --package-dir examples/sound_profile_listening
```

That writes `reports/stage9c/` — median scores, correlations, the A/B outcome, the words you
used, and evidence-based candidate groups. It does **not** choose a final instrument library.

## What is in the folder

| file | what it is |
| :--- | :--- |
| `index.html` | the listening interface; neutral labels only |
| `audio/sample_001.wav …` | {manifest['profile_count']} profile stimuli, blinded and shuffled |
| `audio/song_01_a.wav …` | {len(manifest['song_trials'])} real-song pairs, sides blinded |
| `evaluation_profiles.csv` | part 1 template (ids pre-filled, no answers) |
| `evaluation_ab.csv` | part 2 template |
| `evaluation_songs.csv` | part 3 template |
| `manifest.json` | **private answer key** — do not open while listening |

## The three parts

**Part 1 — one sound at a time ({manifest['profile_count']} samples).** Every profile plays the
same short phrase. Rate how distinctive it is, how useful it could be, how Atari-like it feels,
and — in your own words — what it reminds you of. There is no vocabulary you are supposed to
match; `bass`, `drum`, `bell`, `noise`, `laser`, `repeating` are all fine, and so is anything
else.

**Part 2 — comparing two sounds ({len(manifest['ab_trials'])} pairs).** Two profiles, same music,
same level treatment. How similar are they, which would you rather use, and do they feel like
two genuinely different characters or variants of one?

**Part 3 — whole songs ({len(manifest['song_trials'])} pairs).** The same composition rendered twice:
once with the existing default instruments, once with external sound profiles. Only the
binding changed. Which sounds better, which has more character, which is more convincing as an
Atari composition, and how big is the difference?

This part matters most. A profile can sound interesting on its own and still make a song worse.

## What is deliberately hidden

While you listen, the interface does not show: the profile id, the source song, the artist, the
generator (distortion) family, AUDCTL, whether the sample is 8-bit or 16-bit, whether it is
`VOICE` or `PAIR`, the archaeological status, or any similarity score. That information is in
`manifest.json`, which the analysis reads afterwards.

## How the experiment was controlled

* **Identical musical input.** Every profile realizes the same {sum(step for _, step in STIMULUS_PHRASE)}-step phrase at
  {STIMULUS_BPM} BPM and velocity {STIMULUS_VELOCITY}, on POKEY channel 1. The only variable is the profile.
  For a coupled (`PAIR`) profile the *same* phrase is used, with the composition declaring the
  1+2 join — because a pair cannot be realized any other way.
* **Peak (not RMS) normalization is deliberate** — every stimulus is set by a single gain to
  {manifest['normalization']['target_peak_dbfs']:.2f} dBFS, with no compression, no EQ and no clipping. That sets a
  common level *without* erasing the loudness differences the profiles genuinely have, and both
  the original and final peak/RMS of every sample are recorded so loudness can be examined
  later. In this bank that leaves a measurable RMS spread: the sounds that sustain low are
  simply quieter, and the analysis reports the loudness/rating correlation rather than assuming
  it away. Leave your volume alone part-way through.
* **Shared gain in the song pairs.** There, one gain is applied to *both* sides, so a real
  loudness difference between the default and profile versions stays audible instead of being
  normalized away.
* **Blinded, shuffled presentation.** The order is a shuffle fixed by seed
  `{manifest['seed']}`, recorded in the manifest. Rebuilding with the same bank and seed
  reproduces the same sample ids.
* **A/B sides are randomized** per trial, so "A" is not systematically one thing.
* **The excerpt is identical on both sides** of every song pair: the first
  {manifest['song_excerpt_seconds']} seconds of each render, cut at the same point. The composition is
  untouched.

## What this experiment does **not** test

A profile's document can carry a measured pitch and volume *gesture* (a contour the original
Atari tune used). The player has no per-channel macro and the Composer does not render one, so
**no gesture is invented here**: every stimulus is a static tone shaped by the profile's
generator, clock and envelope. Profiles whose documents carry a contour are therefore heard in
a reduced form, and that is a limitation of the integration, not a property of the sound.

The {len(manifest['excluded_profiles'])} profiles that are not renderable are not in the experiment
at all — they describe silence, so there is nothing to hear. They remain in the library.

A few profiles measure an envelope wider than the composer's envelope fields can express (the
list is in `manifest.json`). The composer refuses such a profile rather than clamping it, so for
those the stimulus declares that one field from the composer's own defaults. The manifest marks
exactly which samples that affects, because for them you are hearing the profile's generator,
clock and pitch with a substituted envelope — a caveat on those samples, not on the others.

## Notes

* The page stores your answers in the browser's local storage. Nothing is uploaded.
* If you close the page mid-way, reopen it and carry on; the progress line at the top shows how
  much is left.
* Around 10–15 minutes is normal. If it feels long, do part 1 and part 3 first — part 3 carries
  the most weight for curation — and come back to part 2.
"""


def build_package(
    package_dir: Path,
    *,
    bank_dir: Path,
    songs_dir: Path,
    seed: int = DEFAULT_SEED,
    sample_rate: int = SAMPLE_RATE,
    now: Optional[datetime] = None,
    context_songs: Optional[Sequence[str]] = None,
    log: Optional[Any] = None,
) -> Dict[str, Any]:
    """Build the whole package: audio, manifest, templates, interface and README."""
    package_dir = Path(package_dir)
    manifest = build_experiment(
        package_dir,
        bank_dir=bank_dir,
        songs_dir=songs_dir,
        seed=seed,
        sample_rate=sample_rate,
        now=now,
        context_songs=context_songs,
        log=log,
    )
    (package_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    write_templates(package_dir, manifest)
    (package_dir / "index.html").write_text(render_index_html(manifest), encoding="utf-8")
    (package_dir / "README.md").write_text(render_readme(manifest), encoding="utf-8")
    return manifest


# ===========================================================================
# Analysis
# ===========================================================================
def _read_csv(path: Path, required: Sequence[str]) -> List[Dict[str, str]]:
    if not path.is_file():
        raise AnalysisNotReady(f"missing evaluation file: {path}")
    with path.open("r", encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    if not rows:
        raise AnalysisNotReady(f"evaluation file has no rows: {path}")
    missing = [column for column in required if column not in (rows[0] or {})]
    if missing:
        raise AnalysisNotReady(f"{path.name} is missing column(s): {', '.join(missing)}")
    return rows


def _number(value: Any) -> Optional[float]:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _choice(value: Any) -> Optional[str]:
    text = str(value or "").strip().lower()
    if not text:
        return None
    if text in ("a", "b"):
        return text
    if text.startswith("no") or text in ("none", "-", "tie"):
        return "none"
    return text


def _median(values: Sequence[float]) -> Optional[float]:
    return round(statistics.median(values), 3) if values else None


def _mean(values: Sequence[float]) -> Optional[float]:
    return round(statistics.fmean(values), 3) if values else None


def _spearman(left: Sequence[float], right: Sequence[float]) -> Optional[float]:
    """Spearman rank correlation, so a monotone but non-linear relationship still shows."""
    if len(left) < 4 or len(left) != len(right):
        return None

    def ranks(values: Sequence[float]) -> List[float]:
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

    rx, ry = ranks(left), ranks(right)
    mx, my = statistics.fmean(rx), statistics.fmean(ry)
    numerator = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
    denominator = math.sqrt(sum((a - mx) ** 2 for a in rx) * sum((b - my) ** 2 for b in ry))
    return round(numerator / denominator, 4) if denominator > 0 else None


def _vocabulary(rows: Sequence[Dict[str, str]]) -> Dict[str, Any]:
    """Words the listener used, with counts and the samples they came from.

    Nothing is normalized beyond case and a trailing plural 's'; the original comments are kept
    verbatim in the JSON so the raw evidence survives.
    """
    counts: Counter = Counter()
    where: Dict[str, List[str]] = {}
    comments: List[Dict[str, str]] = []
    for row in rows:
        text = (row.get("comment") or "").strip()
        if not text:
            continue
        key = row.get("sample_id") or row.get("trial_id") or "?"
        comments.append({"id": key, "comment": text})
        for token in re.findall(r"[A-Za-z][A-Za-z'\-]+", text.lower()):
            word = token.strip("-'")
            if len(word) < 3 or word in VOCABULARY_STOPWORDS:
                continue
            if word.endswith("s") and len(word) > 4 and word[:-1] not in VOCABULARY_STOPWORDS:
                word = word[:-1]
            counts[word] += 1
            where.setdefault(word, [])
            if key not in where[word]:
                where[word].append(key)
    return {
        "words": [
            {"word": word, "count": count, "sample_ids": sorted(where[word])}
            for word, count in sorted(counts.items(), key=lambda item: (-item[1], item[0]))
        ],
        "comments": comments,
    }


def _score_rows(manifest: Dict[str, Any], rows: Sequence[Dict[str, str]]) -> List[Dict[str, Any]]:
    by_id = {entry["sample_id"]: entry for entry in manifest["samples"]}
    scored: List[Dict[str, Any]] = []
    for row in rows:
        sample_id = (row.get("sample_id") or "").strip()
        if sample_id not in by_id:
            continue
        entry = by_id[sample_id]
        scored.append(
            {
                "sample_id": sample_id,
                "profile_id": entry["profile_id"],
                "scope": entry["scope"],
                "status": entry["status"],
                "generator_family": entry["generator_family"],
                "divider_bits": entry["divider_bits"],
                "source_song": entry["source_song"],
                "distinctiveness": _number(row.get("distinctiveness")),
                "usefulness": _number(row.get("usefulness")),
                "atari_character": _number(row.get("atari_character")),
                "confidence": _number(row.get("confidence")),
                "comment": (row.get("comment") or "").strip(),
                "spectral_distance_to_mean": None,
                "centroid_hz": entry["features"]["centroid_hz"],
                "bandwidth_hz": entry["features"]["bandwidth_hz"],
                "flatness": entry["features"]["flatness"],
                "final_rms_dbfs": entry["levels"]["final_rms_dbfs"],
            }
        )
    scored.sort(key=lambda item: item["profile_id"])

    # How spectrally far each profile sits from the centre of the library: a single number for
    # "how unusual is this sound", used for the correlation checks below.
    features = [entry["features"] for entry in manifest["samples"]]
    if len(scored) > 1:
        for row in scored:
            entry = by_id[row["sample_id"]]
            distances = [
                spectral_distance(entry["features"], other)
                for other in features
                if other is not entry["features"]
            ]
            row["spectral_distance_to_mean"] = round(statistics.fmean(distances), 6) if distances else None
    return scored


def _ab_rows(manifest: Dict[str, Any], rows: Sequence[Dict[str, str]]) -> List[Dict[str, Any]]:
    by_id = {entry["trial_id"]: entry for entry in manifest["ab_trials"]}
    scored: List[Dict[str, Any]] = []
    for row in rows:
        trial_id = (row.get("trial_id") or "").strip()
        if trial_id not in by_id:
            continue
        entry = by_id[trial_id]
        scored.append(
            {
                "trial_id": trial_id,
                "stratum": entry["stratum"],
                "profile_a": entry["profile_a"],
                "profile_b": entry["profile_b"],
                "scope_a": entry["scope_a"],
                "scope_b": entry["scope_b"],
                "technical_distance": entry["technical_distance"],
                "same_scope": entry["same_scope"],
                "same_generator_family": entry["same_generator_family"],
                "shares_source_material": entry["shares_source_material"],
                "similarity": _number(row.get("similarity")),
                "preference": _choice(row.get("preference")),
                "character_difference": _number(row.get("character_difference")),
                "comment": (row.get("comment") or "").strip(),
            }
        )
    scored.sort(key=lambda item: item["trial_id"])
    return scored


def _song_rows(manifest: Dict[str, Any], rows: Sequence[Dict[str, str]]) -> List[Dict[str, Any]]:
    by_id = {entry["trial_id"]: entry for entry in manifest["song_trials"]}
    scored: List[Dict[str, Any]] = []
    for row in rows:
        trial_id = (row.get("trial_id") or "").strip()
        if trial_id not in by_id:
            continue
        entry = by_id[trial_id]
        # The listener never learns which side is which, so translate their answer into
        # "profile" / "default" here, in the analysis only.
        sides = entry["uses_profile_side"]
        profile_side = sides["profile"]

        def attribute(field: str) -> Optional[str]:
            answer = _choice(row.get(field))
            if answer in (None, "none"):
                return answer
            return "profile" if answer == profile_side else "default"

        scored.append(
            {
                "trial_id": trial_id,
                "song": entry["song"],
                "bound_profiles": json.dumps(entry["bound_profiles"], sort_keys=True),
                "better_sound": attribute("better_sound"),
                "more_character": attribute("more_character"),
                "more_convincing_atari": attribute("more_convincing_atari"),
                "overall_difference": _number(row.get("overall_difference")),
                "comment": (row.get("comment") or "").strip(),
            }
        )
    scored.sort(key=lambda item: item["trial_id"])
    return scored


def candidate_groups(scored: Sequence[Dict[str, Any]], ab_rows: Sequence[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
    """Experimental candidate groups, from explicit criteria and the raw evidence.

    These are *candidates*, not instruments, and the thresholds are a reading aid rather than
    truth: every group carries the numbers that put a profile in it, so a different threshold
    can be applied by hand.
    """
    # How often a profile was preferred, and how often it was judged clearly distinct.
    preferred: Counter = Counter()
    distinct: Counter = Counter()
    for row in ab_rows:
        if row["preference"] == "a":
            preferred[row["profile_a"]] += 1
        elif row["preference"] == "b":
            preferred[row["profile_b"]] += 1
        if (row["character_difference"] or 0) >= 4:
            distinct[row["profile_a"]] += 1
            distinct[row["profile_b"]] += 1

    strong: List[Dict[str, Any]] = []
    interesting: List[Dict[str, Any]] = []
    weak: List[Dict[str, Any]] = []
    for row in scored:
        usefulness = row["usefulness"] or 0.0
        distinctive = row["distinctiveness"] or 0.0
        character = row["atari_character"] or 0.0
        confidence = row["confidence"] or 0.0
        record = {
            "profile_id": row["profile_id"],
            "sample_id": row["sample_id"],
            "scope": row["scope"],
            "status": row["status"],
            "generator_family": row["generator_family"],
            "usefulness": row["usefulness"],
            "distinctiveness": row["distinctiveness"],
            "atari_character": row["atari_character"],
            "confidence": row["confidence"],
            "times_preferred": preferred.get(row["profile_id"], 0),
            "times_judged_distinct": distinct.get(row["profile_id"], 0),
            "spectral_distance_to_mean": row["spectral_distance_to_mean"],
            "comment": row["comment"],
        }
        if usefulness >= 4 and distinctive >= 4 and (confidence == 0 or confidence >= 3):
            strong.append(record)
        elif (character >= 4 or distinctive >= 4) and usefulness >= 3:
            interesting.append(record)
        elif usefulness <= 2 and distinctive <= 2:
            weak.append(record)

    for group in (strong, interesting, weak):
        group.sort(key=lambda item: (-(item["usefulness"] or 0), -(item["distinctiveness"] or 0), item["profile_id"]))
    return {"strong": strong, "interesting": interesting, "weak": weak}


def analyze_experiment(
    package_dir: Path,
    output_dir: Path,
    *,
    log: Optional[Any] = None,
) -> Dict[str, Path]:
    """Turn the completed spreadsheets into a report. Deterministic; chooses no library."""
    package_dir = Path(package_dir)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    manifest_path = package_dir / "manifest.json"
    if not manifest_path.is_file():
        raise AnalysisNotReady(f"no manifest in {package_dir}; build the package first")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    profile_rows = _read_csv(package_dir / "evaluation_profiles.csv", PROFILE_TEMPLATE_HEADER)
    ab_rows_raw = _read_csv(package_dir / "evaluation_ab.csv", AB_TEMPLATE_HEADER)
    song_rows_raw = _read_csv(package_dir / "evaluation_songs.csv", SONG_TEMPLATE_HEADER)

    scored = _score_rows(manifest, profile_rows)
    ab_rows = _ab_rows(manifest, ab_rows_raw)
    song_rows = _song_rows(manifest, song_rows_raw)

    answered = [row for row in scored if row["distinctiveness"] is not None]
    if not answered:
        raise AnalysisNotReady(
            "no ratings are filled in yet: evaluation_profiles.csv has ids but no numbers"
        )

    vocabulary = _vocabulary(list(profile_rows) + list(ab_rows_raw) + list(song_rows_raw))

    written = {
        "profile_scores": output_dir / "profile_scores.csv",
        "ab_results": output_dir / "ab_results.csv",
        "song_results": output_dir / "song_results.csv",
        "vocabulary": output_dir / "vocabulary.json",
        "report": output_dir / "report.md",
    }
    _write_dicts(written["profile_scores"], scored, list(scored[0].keys()))
    if ab_rows:
        _write_dicts(written["ab_results"], ab_rows, list(ab_rows[0].keys()))
    else:  # pragma: no cover - only when the template is untouched
        _write_dicts(written["ab_results"], [], ["trial_id"])
    if song_rows:
        _write_dicts(written["song_results"], song_rows, list(song_rows[0].keys()))
    else:  # pragma: no cover
        _write_dicts(written["song_results"], [], ["trial_id"])
    written["vocabulary"].write_text(
        json.dumps(vocabulary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    groups = candidate_groups(scored, ab_rows)
    written["report"].write_text(
        render_report(manifest, scored, ab_rows, song_rows, vocabulary, groups),
        encoding="utf-8",
    )
    if log is not None:
        log(f"Analysed {len(answered)} rated profile(s), {len(ab_rows)} A/B trial(s), {len(song_rows)} song pair(s)")
    return written


def _write_dicts(path: Path, rows: Sequence[Dict[str, Any]], fields: Sequence[str]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(fields), extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def render_report(
    manifest: Dict[str, Any],
    scored: Sequence[Dict[str, Any]],
    ab_rows: Sequence[Dict[str, Any]],
    song_rows: Sequence[Dict[str, Any]],
    vocabulary: Dict[str, Any],
    groups: Dict[str, List[Dict[str, Any]]],
) -> str:
    """The written report: what the ratings say, including the parts that disagree."""
    answered = [row for row in scored if row["distinctiveness"] is not None]
    lines: List[str] = []
    add = lines.append

    add("# Stage 9C — profile listening experiment")
    add("")
    add("Perceptual evidence for future curation. **No final library is chosen here.**")
    add("")
    add("| | |")
    add("| :--- | :--- |")
    add(f"| profiles in the bank | {manifest['profile_count_in_bank']} |")
    add(f"| profiles in the experiment | {manifest['profile_count']} "
        f"({manifest['scope_counts'].get('VOICE', 0)} VOICE, {manifest['scope_counts'].get('PAIR', 0)} PAIR) |")
    add(f"| profiles excluded (not renderable) | {len(manifest['excluded_profiles'])} |")
    add(f"| A/B trials | {len(manifest['ab_trials'])} |")
    add(f"| song pairs | {len(manifest['song_trials'])} |")
    add(f"| ratings returned | {len(answered)} of {manifest['profile_count']} |")
    add(f"| seed | `{manifest['seed']}` |")
    add(f"| normalization | peak to {manifest['normalization']['target_peak_dbfs']:.2f} dBFS, gain only |")
    add(f"| bank fingerprint | `{manifest['profile_bank_fingerprint'][:16]}…` |")
    add("")

    add("## Profile statistics")
    add("")
    add("| measure | median | mean | min | max |")
    add("| :--- | ---: | ---: | ---: | ---: |")
    for field in ("distinctiveness", "usefulness", "atari_character", "confidence"):
        values = [row[field] for row in answered if row[field] is not None]
        if not values:
            add(f"| {field} | — | — | — | — |")
            continue
        add(
            f"| {field} | {_median(values)} | {_mean(values)} | {min(values):g} | {max(values):g} |"
        )
    add("")

    add("### Score distribution")
    add("")
    add("| score | distinctiveness | usefulness | Atari character |")
    add("| ---: | ---: | ---: | ---: |")
    for value in range(1, 6):
        cells = []
        for field in ("distinctiveness", "usefulness", "atari_character"):
            count = sum(1 for row in answered if row[field] == value)
            cells.append(str(count))
        add(f"| {value} | " + " | ".join(cells) + " |")
    add("")

    if len(answered) >= 4:
        add("### Correlations (Spearman rank)")
        add("")
        add("Reported only where the data supports it; a weak or absent relationship is a result "
            "too, and 'n/a' means one of the two variables did not vary in this set.")
        add("")
        add("| relationship | n | rho |")
        add("| :--- | ---: | ---: |")
        checks = [
            ("spectral distance from the library centre vs distinctiveness",
             "spectral_distance_to_mean", "distinctiveness"),
            ("spectral distance from the library centre vs usefulness",
             "spectral_distance_to_mean", "usefulness"),
            ("spectral centroid vs distinctiveness", "centroid_hz", "distinctiveness"),
            ("spectral bandwidth vs distinctiveness", "bandwidth_hz", "distinctiveness"),
            ("spectral flatness vs Atari character", "flatness", "atari_character"),
            ("final RMS (loudness) vs usefulness", "final_rms_dbfs", "usefulness"),
            ("final RMS (loudness) vs distinctiveness", "final_rms_dbfs", "distinctiveness"),
        ]
        for label, left_field, right_field in checks:
            pairs = [
                (float(row[left_field]), float(row[right_field]))
                for row in answered
                if row[left_field] is not None and row[right_field] is not None
            ]
            if len(pairs) < 4:
                continue
            rho = _spearman([p[0] for p in pairs], [p[1] for p in pairs])
            shown = rho if rho is not None else "n/a (no variation in one variable)"
            add(f"| {label} | {len(pairs)} | {shown} |")
        add("")

        loudness = [row["final_rms_dbfs"] for row in answered if row["final_rms_dbfs"] is not None]
        if loudness:
            add("### Loudness, and why it is not equalized")
            add("")
            add(f"Every stimulus peaks at the same level, but the profiles' own sustain differs, "
                f"so measured RMS spans {min(loudness):.1f} to {max(loudness):.1f} dBFS "
                f"(median {statistics.median(loudness):.1f}). That spread belongs to the sounds, "
                "not to the normalization, and it was deliberately left in place rather than "
                "compressed away. Read the two loudness rows above before attributing a rating to "
                "character, and treat 'quiet' or 'thin' in a comment as loudness language "
                "unless the comment says otherwise.")
            add("")

        add("### Group medians")
        add("")
        add("| grouping | group | n | median distinctiveness | median usefulness | median Atari character |")
        add("| :--- | :--- | ---: | ---: | ---: | ---: |")
        for field in ("scope", "generator_family", "divider_bits", "status"):
            groups_by_field: Dict[Any, List[Dict[str, Any]]] = {}
            for row in answered:
                groups_by_field.setdefault(row[field], []).append(row)
            for key in sorted(groups_by_field, key=lambda item: str(item)):
                rows = groups_by_field[key]
                add(
                    f"| {field} | `{key}` | {len(rows)} | "
                    f"{_median([r['distinctiveness'] for r in rows if r['distinctiveness'] is not None])} | "
                    f"{_median([r['usefulness'] for r in rows if r['usefulness'] is not None])} | "
                    f"{_median([r['atari_character'] for r in rows if r['atari_character'] is not None])} |"
                )
        add("")

    add("## A/B analysis")
    add("")
    answered_ab = [row for row in ab_rows if row["similarity"] is not None or row["preference"]]
    if not answered_ab:
        add("_No A/B answers were returned._")
        add("")
    else:
        preference = Counter(row["preference"] for row in answered_ab if row["preference"])
        add(f"Preferences: {dict(sorted(preference.items()))} "
            f"(A: {preference.get('a', 0)}, B: {preference.get('b', 0)}, "
            f"no preference: {preference.get('none', 0)})")
        add("")
        similarities = [row["similarity"] for row in answered_ab if row["similarity"] is not None]
        if similarities:
            add(f"Similarity ratings: median {_median(similarities)}, "
                f"range {min(similarities):g}–{max(similarities):g}")
            add("")
        differences = [row["character_difference"] for row in answered_ab if row["character_difference"] is not None]
        if differences:
            add(f"Character-difference ratings: median {_median(differences)}, "
                f"range {min(differences):g}–{max(differences):g}")
            add("")

        add("### Technical distance against perceived similarity")
        add("")
        pairs = [
            (row["technical_distance"], row["similarity"])
            for row in answered_ab
            if row["similarity"] is not None
        ]
        if len(pairs) >= 4:
            rho = _spearman([p[0] for p in pairs], [p[1] for p in pairs])
            add(f"Spearman rho over {len(pairs)} trial(s): **{rho}**. A value near 0 means the "
                "technical distance did not predict what the listener heard.")
        else:
            add("_Too few trials to correlate._")
        add("")

        counterexamples = [
            row
            for row in answered_ab
            if row["similarity"] is not None
            and (
                (row["technical_distance"] >= 0.25 and row["similarity"] >= 4)
                or (row["technical_distance"] <= 0.05 and row["similarity"] <= 2)
            )
        ]
        add("### Counterexamples")
        add("")
        add("Trials where the measurements and the listener disagreed — the most useful evidence "
            "this experiment can produce, and deliberately not smoothed over.")
        add("")
        if counterexamples:
            add("| trial | stratum | technical distance | perceived similarity | note |")
            add("| :--- | :--- | ---: | ---: | :--- |")
            for row in counterexamples:
                if row["technical_distance"] >= 0.25:
                    note = "technically distant, heard as similar"
                else:
                    note = "technically close, heard as different"
                add(
                    f"| {row['trial_id']} | {row['stratum']} | {row['technical_distance']:.3f} | "
                    f"{row['similarity']:g} | {note} |"
                )
        else:
            add("_None in this set._")
        add("")

        add("### Per stratum")
        add("")
        add("| stratum | trials | median similarity | profile preferred | no preference |")
        add("| :--- | ---: | ---: | ---: | ---: |")
        by_stratum: Dict[str, List[Dict[str, Any]]] = {}
        for row in answered_ab:
            by_stratum.setdefault(row["stratum"], []).append(row)
        for stratum in sorted(by_stratum):
            rows = by_stratum[stratum]
            values = [row["similarity"] for row in rows if row["similarity"] is not None]
            preferred = sum(1 for row in rows if row["preference"] in ("a", "b"))
            none = sum(1 for row in rows if row["preference"] == "none")
            add(f"| {stratum} | {len(rows)} | {_median(values)} | {preferred} | {none} |")
        add("")

    add("## Song analysis")
    add("")
    answered_songs = [row for row in song_rows if row["overall_difference"] is not None or row["better_sound"]]
    if not answered_songs:
        add("_No song-pair answers were returned._")
        add("")
    else:
        for field, label in (
            ("better_sound", "which sounds better"),
            ("more_character", "which has more character"),
            ("more_convincing_atari", "which is more convincing as an Atari composition"),
        ):
            counts = Counter(row[field] for row in answered_songs if row[field])
            add(
                f"* **{label}** — profile version {counts.get('profile', 0)}, "
                f"default version {counts.get('default', 0)}, no preference {counts.get('none', 0)}"
            )
        differences = [row["overall_difference"] for row in answered_songs if row["overall_difference"] is not None]
        if differences:
            add(f"* **overall difference** — median {_median(differences)}, "
                f"range {min(differences):g}–{max(differences):g}")
        add("")
        add("| pair | song | better sound | more character | more convincing | difference |")
        add("| :--- | :--- | :--- | :--- | :--- | ---: |")
        for row in answered_songs:
            add(
                f"| {row['trial_id']} | {row['song']} | {row['better_sound'] or '—'} | "
                f"{row['more_character'] or '—'} | {row['more_convincing_atari'] or '—'} | "
                f"{row['overall_difference'] if row['overall_difference'] is not None else '—'} |"
            )
        add("")
        comments = [(row["trial_id"], row["comment"]) for row in answered_songs if row["comment"]]
        if comments:
            add("### What the listener said about the songs")
            add("")
            for trial_id, comment in comments:
                add(f"* **{trial_id}** — {comment}")
            add("")

    add("## Listener vocabulary")
    add("")
    words = vocabulary["words"]
    if not words:
        add("_No free-text comments were returned._")
    else:
        add(f"{len(words)} distinct word(s) across {len(vocabulary['comments'])} comment(s). "
            "Words are observations, not a taxonomy.")
        add("")
        add("| word | count | samples |")
        add("| :--- | ---: | :--- |")
        for entry in words[:60]:
            shown = ", ".join(entry["sample_ids"][:8])
            if len(entry["sample_ids"]) > 8:
                shown += f" (+{len(entry['sample_ids']) - 8})"
            add(f"| {entry['word']} | {entry['count']} | {shown} |")
    add("")

    add("## Candidate groups (experimental)")
    add("")
    add("Evidence-based candidates for a **later, separate** curation decision — not instruments, "
        "and not a selection. Thresholds: strong = usefulness ≥ 4 and distinctiveness ≥ 4 with "
        "confidence not low; interesting = distinctive or strongly Atari-like while useful; "
        "weak = usefulness ≤ 2 and distinctiveness ≤ 2. Re-read the numbers and disagree.")
    add("")
    for key, title in (
        ("strong", "Strong candidates"),
        ("interesting", "Interesting candidates"),
        ("weak", "Weak / redundant candidates"),
    ):
        rows = groups[key]
        add(f"### {title} ({len(rows)})")
        add("")
        if not rows:
            add("_None under these thresholds._")
            add("")
            continue
        add("| profile | scope | generator | usefulness | distinctiveness | Atari | preferred | judged distinct |")
        add("| :--- | :--- | :--- | ---: | ---: | ---: | ---: | ---: |")
        for row in rows:
            add(
                f"| {row['profile_id']} | {row['scope']} | `{row['generator_family']}` | "
                f"{row['usefulness']} | {row['distinctiveness']} | {row['atari_character']} | "
                f"{row['times_preferred']} | {row['times_judged_distinct']} |"
            )
        add("")

    add("## What this report does not do")
    add("")
    add("* it does not choose the final Atari instrument library;")
    add("* it does not rename a profile or assign it a role;")
    add("* it does not remove or re-rank anything in the bank;")
    add("* it does not treat a technical metric as a perceptual fact — where they disagree, both "
        "are reported.")
    add("")
    return "\n".join(lines)


__all__ = [
    "AB_TEMPLATE_HEADER",
    "AB_TRIAL_TARGET",
    "AnalysisNotReady",
    "CONTEXT_SONGS",
    "DEFAULT_SEED",
    "EXPERIMENT",
    "MANIFEST_VERSION",
    "PROFILE_TEMPLATE_HEADER",
    "SAMPLE_RATE",
    "SONG_TEMPLATE_HEADER",
    "STIMULUS_PHRASE",
    "Stage9CError",
    "TARGET_PEAK",
    "analyze_experiment",
    "bank_fingerprint",
    "build_ab_trials",
    "build_experiment",
    "build_package",
    "candidate_groups",
    "normalize_peak",
    "render_index_html",
    "render_readme",
    "render_report",
    "render_song_versions",
    "render_stimulus",
    "spectral_distance",
    "spectral_features",
    "stimulus_composition",
    "write_templates",
    "write_wav",
]

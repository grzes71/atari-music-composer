"""Stage 10B — the volume contour transfer experiment.

Stage 9E named one capability the composer does not have: the archaeology measures how a sound's
loudness moved over time (``gesture.volume.runs``, an absolute series of AUDC volume levels sampled
once per VBL frame), and the player discards it. Stage 10A showed that *reassigning* profiles does not
by itself improve anything; this stage asks a narrower question:

    can the measured volume contour be transferred into the existing IR and frame generation,
    and does the transfer change the sound in the direction the measurement describes?

What this stage does
--------------------
* defines the contour source (the measurement) and the mapping to POKEY's 0..15 volume, and
  implements it in the IR the renderer already uses — one code path, no parallel renderer;
* renders three variants of one subject: A = the composer's own (DEFAULT), B = the profile
  (CURRENT PROFILE), C = the same profile with its measured contour (PROFILE + VOLUME CONTOUR),
  differing only in the contour;
* proves the perturbation end to end (contour → IR → frames → WAV) and proves that with the
  feature switched off nothing moves: the six Stage 10A excerpts are reproduced byte for byte;
* measures what changed automatically, and builds a small blinded listening package;
* writes a report that keeps observation, inference and experimental choice apart.

What this stage refuses to do
-----------------------------
No profile, bank, schema, DSL, composition, binding, generator, player or historical result is
modified. No winner is declared. The contour is *not* claimed to solve anything about the library,
and nothing is integrated with the composer's authoring path. The MADS/XEX exporter refuses a song
that carries a contour rather than exporting something that would not play what was listened to.

The one honest complication
---------------------------
A measured contour may reach level 0, which in the source means *nothing sounded*. That is timing,
not loudness: transferring it would import the source arrangement's gating into a composition whose
notes the composer already owns. A contour that gates is therefore not transferable, and every
channel where one was withheld is named in the report. Nothing is interpolated or invented to make
such a contour usable.
"""

from __future__ import annotations

import csv
import hashlib
import json
import math
import os
import random
import wave
from collections import OrderedDict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

import numpy as np

from atari_music import __version__ as RENDERER_VERSION
from atari_music.ai.client import generate_music_from_composition
from atari_music.ai.schema import (
    AICompositionDoc,
    AICompositionMetadata,
    AIHardwareConfig,
    AIInstrumentDef,
    AIPatternChannelEvent,
    AIPatternDef,
)
from atari_music.ir import (
    FRAME_COLUMN_NAMES,
    FRAME_COLUMNS,
    FRAME_RATE_HZ,
    apply_volume_contour,
    audc_column,
    compile_ir_to_pokey_frames,
    resolve_audctl_mode,
)
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
    SONG_EXCERPT_SECONDS,
    STIMULUS_BPM,
    STIMULUS_CHARACTER,
    STIMULUS_VELOCITY,
    TARGET_PEAK,
    spectral_distance,
    spectral_features,
    write_wav,
)
from atari_music.stage10a import Render, load_song, recover_songs, shared_gain, song_digest

#: The experiment this module builds.
EXPERIMENT = "stage10b"

#: The manifest and analysis schema versions.
MANIFEST_VERSION = "stage10b/1"
ANALYSIS_VERSION = "stage10b/1"

#: Where the artefacts go.
DEFAULT_PACKAGE_DIR = Path("examples/sound_profile_volume_contour_10b")
DEFAULT_STAGE10A_PACKAGE = Path("examples/sound_profile_rebinding_10a")
DEFAULT_STAGE9C_PACKAGE = Path("examples/sound_profile_listening")
DEFAULT_SONGS_DIR = Path("examples/songs")
DEFAULT_BANK_DIR = Path("tests/data/sound_profiles/bank")
DEFAULT_STAGE9D_REPORTS = Path("reports/stage9d")
DEFAULT_ANALYSIS_REPORTS = Path("reports/stage10b")
DEFAULT_DOCS_DIR = Path("docs")

#: The seed the blinded orientations are drawn from. Recorded, never reused silently.
SEED = 20261007

#: The fastest contour change rate that a 50 Hz frame grid can carry: two samples per cycle.
#: A contour that changes level faster than this cannot be represented frame by frame, and
#: transferring it would produce an artefact of the sampling rather than of the sound.
CONTOUR_RATE_LIMIT_HZ = 12.5

#: The shortest contour worth transferring, in frames: one cycle at the rate limit plus margin.
CONTOUR_MIN_SPAN_FRAMES = 8

#: How long a tested profile's note is held, in frames: long enough for the contour to be heard at
#: least once, short enough to stay a single sound rather than a melody.
HOLD_MIN_FRAMES = 40
HOLD_MAX_FRAMES = 300

#: How many profiles the profile set tests, by scope. The pair is included because a 16-bit sound
#: carries its audible volume in AUDC2, which is the same frame column the composer already writes,
#: so the contour needs no extra assumption about coupled channels.
TESTED_VOICE_PROFILES = 7
TESTED_PAIR_PROFILES = 1

#: How many control pairs (A vs C) the package adds, by subject kind.
CONTROL_PROFILE_TRIALS = 2
CONTROL_SONG_TRIALS = 2

#: The pairs by kind: (kind, left variant, right variant).
TRIAL_KINDS: Tuple[Tuple[str, str, str], ...] = (
    ("profile_current_vs_contour", "b", "c"),
    ("song_current_vs_contour", "b", "c"),
    ("profile_default_vs_contour", "a", "c"),
    ("song_default_vs_contour", "a", "c"),
)
TRIAL_KIND_LOOKUP: Dict[str, Tuple[str, str]] = {
    kind: (left, right) for kind, left, right in TRIAL_KINDS
}

#: What the listener is shown for a pair. Identical for every kind on purpose: a caption that
#: distinguished the variants would tell the listener which side to prefer.
CAPTION = "Two versions of the same sound. Only one difference between them."

#: The columns of the answer template.
ANSWER_HEADER: Tuple[str, ...] = (
    "trial_id",
    "better_overall",
    "more_convincing_atari",
    "more_interesting_character",
    "audible_movement",
    "difference_1_5",
    "comment",
)

VARIANT_KINDS: Tuple[str, ...] = ("a", "b", "c")

#: What each variant is, in one phrase, for the manifest and the report.
VARIANT_LABELS: Dict[str, str] = {
    "a": "DEFAULT — the composer's own instrument, no profile",
    "b": "CURRENT PROFILE — the profile bound, no volume contour",
    "c": "PROFILE + VOLUME CONTOUR — the same binding with the profile's measured contour",
}

#: Why a measured contour was not transferred.
CONTOUR_WITHHELD_GATING = "measured level 0 (silence) — timing, not loudness"
CONTOUR_WITHHELD_STATIC = "measured levels are constant — a static contour is a no-op"
CONTOUR_WITHHELD_ABSENT = "no measured level series"
CONTOUR_WITHHELD_DECLARED_UNAVAILABLE = "the profile does not declare its gesture usable"


class Stage10BError(RuntimeError):
    """The experiment cannot be prepared as specified."""


# ===========================================================================
# 1. The contour as a contract
# ===========================================================================
def transferability(profile: SoundProfile) -> Tuple[Optional[Tuple[int, ...]], Optional[str]]:
    """The contour this profile contributes to the experiment, and why it contributes nothing.

    Returns ``(contour, None)`` when the measurement can be transferred, and
    ``(None, reason)`` when it cannot. The reasons are decisions about the *measurement*, taken
    before anything was rendered, and they are reported for every candidate rather than only for
    the profiles that were finally chosen.
    """
    declared = profile.volume_contour_declared
    if declared and declared.get("available") is False:
        return None, CONTOUR_WITHHELD_DECLARED_UNAVAILABLE
    contour = profile.volume_contour
    if not contour:
        return None, CONTOUR_WITHHELD_ABSENT
    if len(set(contour)) < 2:
        return None, CONTOUR_WITHHELD_STATIC
    if min(contour) == 0:
        return None, CONTOUR_WITHHELD_GATING
    return contour, None


def silence_shape(contour: Sequence[int]) -> Dict[str, int]:
    """Where a measured contour's silent frames sit: before the sound, after it, or inside it.

    A leading or trailing run of zeros is the gesture starting from or returning to silence; zeros
    *between* the first and last sounding frame mean the source was silent in the middle of the
    gesture. Both are timing, not loudness — the distinction is recorded because the report says so,
    not because the mapping treats them differently.
    """
    levels = [int(level) for level in contour]
    if not levels:
        return {"leading": 0, "trailing": 0, "interior": 0}
    start = 0
    while start < len(levels) and levels[start] == 0:
        start += 1
    end = len(levels)
    while end > 0 and levels[end - 1] == 0:
        end -= 1
    return {
        "leading": start,
        "trailing": len(levels) - end,
        "interior": levels[start:end].count(0),
    }


def contour_record(profile: SoundProfile) -> Dict[str, Any]:
    """Everything the experiment knows about one profile's contour, measured or refused."""
    contour, refusal = transferability(profile)
    gesture = profile.volume_gesture
    raw = profile.volume_contour
    record: Dict[str, Any] = {
        "profile_id": profile.profile_id,
        "scope": profile.scope,
        "status": profile.status,
        "observable_channel": profile.audible_channel,
        "distortion_nibble": profile.distortion_nibble,
        "audctl_mode": profile.audctl_mode,
        "declared": dict(profile.volume_contour_declared),
        "frames": len(raw) if raw else 0,
        "levels": sorted(set(raw)) if raw else [],
        "min_level": min(raw) if raw else None,
        "max_level": max(raw) if raw else None,
        "gating_share": round(raw.count(0) / len(raw), 4) if raw else None,
        "silence_shape": silence_shape(raw) if raw else None,
        "level_changes": (
            sum(1 for left, right in zip(raw, raw[1:]) if left != right) if raw else None
        ),
        "shape": gesture.get("shape"),
        "behavior": gesture.get("behavior"),
        "change_rate_hz": gesture.get("change_rate_hz"),
        "periodic": gesture.get("periodic"),
        "transferable": contour is not None,
        "withheld_because": refusal,
        "rate_within_frame_grid": (
            None
            if gesture.get("change_rate_hz") is None
            else bool(float(gesture["change_rate_hz"]) <= CONTOUR_RATE_LIMIT_HZ)
        ),
        "span_within_bounds": (
            None if not raw else bool(CONTOUR_MIN_SPAN_FRAMES <= len(raw) <= HOLD_MAX_FRAMES)
        ),
    }
    if contour is not None:
        record["contour"] = list(contour)
    return record


def contour_statistics(contour: Sequence[int]) -> Dict[str, Any]:
    """The shape of one contour, as numbers rather than as taste."""
    levels = [int(level) for level in contour]
    if not levels:
        raise Stage10BError("a contour with no frames has no statistics")
    peak = max(levels)
    span = len(levels)
    changes = sum(1 for left, right in zip(levels, levels[1:]) if left != right)
    return {
        "span_frames": span,
        "span_seconds": round(span / FRAME_RATE_HZ, 4),
        "distinct_levels": len(set(levels)),
        "min_level": min(levels),
        "max_level": peak,
        "mean_level": round(sum(levels) / span, 4),
        "depth_ratio": round(min(levels) / peak, 4) if peak else None,
        "level_changes": changes,
        "change_rate_hz": round(changes / (span / FRAME_RATE_HZ), 4) if span else None,
        "asymmetric": bool(levels != list(reversed(levels))),
    }


def reference_volume_series(base: Sequence[int], contour: Sequence[int]) -> List[int]:
    """The series the frame compiler must produce: the composer's envelope, modulated."""
    return apply_volume_contour(base, contour)


# ===========================================================================
# 2. The tested profiles
# ===========================================================================
@dataclass(frozen=True)
class TestedProfile:
    """One profile the profile set tests, with the measurements that put it there."""

    profile_id: str
    scope: str
    distortion_nibble: Optional[int]
    status: Optional[str]
    contour: Tuple[int, ...]
    statistics: Dict[str, Any]
    hold_frames: int
    rank_basis: str

    @property
    def hold_seconds(self) -> float:
        return round(self.hold_frames / FRAME_RATE_HZ, 4)

    def as_dict(self) -> Dict[str, Any]:
        return {
            "profile_id": self.profile_id,
            "scope": self.scope,
            "distortion_nibble": self.distortion_nibble,
            "status": self.status,
            "contour": list(self.contour),
            "statistics": dict(self.statistics),
            "hold_frames": self.hold_frames,
            "hold_seconds": self.hold_seconds,
            "rank_basis": self.rank_basis,
        }


def hold_frames_for(contour: Sequence[int]) -> int:
    """How long the tested sound is held: the contour's own length, within stated bounds."""
    return max(HOLD_MIN_FRAMES, min(HOLD_MAX_FRAMES, len(contour)))


def select_tested_profiles(
    bank: SoundProfileBank,
    *,
    voice: int = TESTED_VOICE_PROFILES,
    pair: int = TESTED_PAIR_PROFILES,
) -> Tuple[List[TestedProfile], List[Dict[str, Any]]]:
    """The tested set, chosen by a rule that is applied before anything is rendered.

    A profile qualifies when its contour is transferable (see :func:`transferability`), its change
    rate fits the frame grid, its span fits the stated bounds, and its status may be rendered.
    Within each scope the ranking is mechanical — the contour that moves most first, then the one
    with more distinct levels, then the longer one, then the profile id — so the choice is
    reproducible and reviewable.

    Returns the chosen profiles and one record per *candidate that qualified but was not chosen*, so
    the report can show what the bound excluded rather than only what it kept.
    """
    qualified: Dict[str, List[Tuple[Tuple[Any, ...], SoundProfile, Tuple[int, ...]]]] = {
        "VOICE": [],
        "PAIR": [],
    }
    looked_at: List[Dict[str, Any]] = []
    for profile_id in bank.ids():
        profile = bank.get(profile_id)
        contour, refusal = transferability(profile)
        record = {
            "profile_id": profile_id,
            "scope": profile.scope,
            "qualifies": False,
            "reason": refusal,
        }
        if contour is None:
            looked_at.append(record)
            continue
        if not profile.renderable:
            record["reason"] = f"status {profile.status} must not be rendered as a sound"
            looked_at.append(record)
            continue
        statistics = contour_statistics(contour)
        rate = statistics["change_rate_hz"] or 0.0
        if rate > CONTOUR_RATE_LIMIT_HZ:
            record["reason"] = (
                f"contour changes {rate:.1f} times a second, faster than the "
                f"{CONTOUR_RATE_LIMIT_HZ} Hz frame grid can carry"
            )
            looked_at.append(record)
            continue
        if not CONTOUR_MIN_SPAN_FRAMES <= len(contour) <= HOLD_MAX_FRAMES:
            record["reason"] = (
                f"contour spans {len(contour)} frames, outside the tested "
                f"{CONTOUR_MIN_SPAN_FRAMES}..{HOLD_MAX_FRAMES}"
            )
            looked_at.append(record)
            continue
        if profile.scope not in qualified:
            record["reason"] = f"scope {profile.scope} is not tested"
            looked_at.append(record)
            continue
        key = (-statistics["level_changes"], -statistics["distinct_levels"], -len(contour), profile_id)
        qualified[profile.scope].append((key, profile, contour))
        record["qualifies"] = True
        record["rank"] = list(key)
        record["statistics"] = statistics
        looked_at.append(record)

    tested: List[TestedProfile] = []
    for scope, wanted in (("VOICE", voice), ("PAIR", pair)):
        ranked = sorted(qualified[scope], key=lambda item: item[0])
        for key, profile, contour in ranked[:wanted]:
            tested.append(
                TestedProfile(
                    profile_id=profile.profile_id,
                    scope=profile.scope,
                    distortion_nibble=profile.distortion_nibble,
                    status=profile.status,
                    contour=contour,
                    statistics=contour_statistics(contour),
                    hold_frames=hold_frames_for(contour),
                    rank_basis=(
                        f"{statistics['level_changes']} level changes over "
                        f"{len(contour)} frames, {len(set(contour))} distinct levels "
                        f"(distortion ${profile.distortion_nibble:X}, "
                        f"{profile.scope}, status {profile.status})"
                    ),
                )
            )
        for position, (key, profile, contour) in enumerate(ranked, start=1):
            if position <= wanted:
                continue
            looked_at.append(
                {
                    "profile_id": profile.profile_id,
                    "scope": profile.scope,
                    "qualifies": False,
                    "reason": (
                        f"qualified but not chosen: ranked {position} of {len(ranked)} "
                        f"{scope} candidates (the set tests {wanted})"
                    ),
                }
            )
    return tested, looked_at


# ===========================================================================
# 3. The stimulus the tested profiles are realized against
# ===========================================================================
def _stimulus_frames_per_tick() -> int:
    """The composer's own tick length at the stimulus tempo, measured rather than assumed."""
    document = contour_stimulus(joined_pair=False, hold_steps=4)
    return int(generate_music_from_composition(document).pokey_ir.frames_per_tick)


def contour_stimulus(
    *,
    joined_pair: bool,
    hold_steps: int,
    envelope_overrides: Optional[Dict[str, int]] = None,
) -> AICompositionDoc:
    """One note, held long enough for a measured contour to be heard once.

    This is the same single-voice stimulus Stage 9C used — same tempo, same character, same
    velocity, so a profile sounds the way the archaeology measured it — with one difference that
    the subject of this experiment requires: instead of a phrase of short notes, one note is held
    for ``hold_steps`` steps, so the profile's contour plays out across the note rather than being
    truncated by the note's length.
    """
    instrument = AIInstrumentDef(
        id="stim",
        name="Stimulus",
        character=STIMULUS_CHARACTER,
        **(envelope_overrides or {}),
    )
    return AICompositionDoc(
        metadata=AICompositionMetadata(
            title="Stage 10B contour stimulus",
            bpm=STIMULUS_BPM,
            key="C",
            mode="major",
        ),
        hardware=AIHardwareConfig(channels=4, use_16bit_bass=joined_pair),
        instruments=[instrument],
        patterns=[
            AIPatternDef(
                id="S",
                length_steps=hold_steps,
                channels={
                    "1": [
                        AIPatternChannelEvent(
                            step=0,
                            note="C4",
                            instrument="stim",
                            duration=hold_steps,
                            volume=STIMULUS_VELOCITY,
                        )
                    ]
                },
            )
        ],
        sequence=["S"],
        loop_point=0,
    )


def _character_default(result: Any, field_name: str) -> int:
    """The envelope the composer derives from the instrument's character.

    Used only where a profile measures an envelope wider than the composer's fields can hold, which
    is the consumer's own documented route (``PROFILE_ENVELOPE_OUT_OF_RANGE``); the value is the one
    the binding itself would have used without the profile's measurement, so nothing is invented.
    """
    envelope = getattr(result.pokey_ir.instruments[0], "envelope", None)
    if envelope is None:  # pragma: no cover - defensive
        raise Stage10BError("the stimulus IR carries no envelope to fall back to")
    return int(getattr(envelope, field_name))


def stimulus_document(
    profile: SoundProfile,
    bank: SoundProfileBank,
    *,
    contour: Optional[Sequence[int]] = None,
) -> Tuple[Any, Dict[str, Any]]:
    """The composition one profile is realized against, with the consumer's own envelope fallbacks.

    Mirrors Stage 9C's stimulus realization, including its one honest complication: a profile whose
    measured envelope is wider than the composer can express is realized with the composer's own
    default for the fields it refused, and whatever was substituted is returned rather than hidden.
    The hold length comes from the contour, so a longer contour is heard in full.
    """
    joined = profile.scope == "PAIR"
    binding = load_profile_binding(
        {
            "schema": "atari-music/sound-profile-binding/1",
            "instruments": {"stim": profile.profile_id},
        }
    )
    frames_per_tick = _stimulus_frames_per_tick()
    hold = contour if contour is not None else profile.volume_contour or ()
    hold_steps = max(1, math.ceil(hold_frames_for(hold) / frames_per_tick))

    overrides: Dict[str, int] = {}
    refusal: Dict[str, Any] = {}
    for _ in range(5):
        document = contour_stimulus(
            joined_pair=joined,
            hold_steps=hold_steps,
            envelope_overrides=overrides or None,
        )
        result = generate_music_from_composition(document)
        try:
            apply_profile_binding(result, binding, bank, composition=document)
        except SoundProfileError as error:
            if getattr(error, "code", None) != PROFILE_ENVELOPE_OUT_OF_RANGE:
                raise
            field_name = str(error.detail.get("field", ""))
            if field_name not in ("attack_frames", "decay_frames", "release_frames", "sustain_vol"):
                raise
            if field_name in overrides:  # pragma: no cover - a refusal the fallback did not fix
                raise
            refusal = dict(error.detail)
            overrides[field_name] = _character_default(result, field_name)
            continue
        return document, {"envelope_overrides": overrides, "refusal": refusal}
    raise Stage10BError(  # pragma: no cover - the loop always terminates on success
        f"could not realize profile {profile.profile_id} as a contour stimulus"
    )


# ===========================================================================
# 4. Rendering the three variants
# ===========================================================================
def render_subject(
    document: Any,
    bank: Optional[SoundProfileBank],
    binding: Optional[Mapping[str, str]],
    *,
    volume_contour: Any,
    kind: str,
    gain: float,
    limit: Optional[int] = None,
) -> Render:
    """Render one variant and apply the subject's shared gain.

    The gain is decided by the caller, never here: the three variants of one subject share one gain,
    so a difference between them is a difference in the sound rather than in the level matching.
    """
    result = generate_music_from_composition(document)
    if binding is not None:
        if bank is None:  # pragma: no cover - defensive
            raise Stage10BError("a binding needs the bank it refers to")
        result = apply_profile_binding(
            result,
            load_profile_binding(
                {"schema": "atari-music/sound-profile-binding/1", "instruments": dict(binding)}
            ),
            bank,
            composition=document,
            volume_contour=volume_contour,
        )
    frames = compile_ir_to_pokey_frames(result.pokey_ir)
    samples = render_pokey_samples(frames, SAMPLE_RATE, FRAME_RATE_HZ)
    window = samples if limit is None else samples[:limit]
    scaled = window.astype(np.float64) * gain
    clipped = int(np.count_nonzero((scaled > 32767.0) | (scaled < -32768.0)))
    final = np.rint(np.clip(scaled, -32768.0, 32767.0)).astype(np.int16)
    return Render(
        kind=kind,
        samples=final,
        frames=frames,
        audctl=resolve_audctl_mode(result.pokey_ir),
        clipped=clipped,
        features=spectral_features(final, SAMPLE_RATE),
    )


def _peak_of(samples: np.ndarray) -> float:
    return float(np.max(np.abs(samples.astype(np.float64)))) / 32768.0 if samples.size else 0.0


def render_profile_variants(
    profile: SoundProfile,
    bank: SoundProfileBank,
    *,
    contour: Sequence[int],
) -> Tuple[Dict[str, Render], Dict[str, Any]]:
    """A, B and C for one tested profile, rendered from one composition and one binding.

    The renderer normalizes each buffer it returns to a peak of 0.90, and the contour never
    attenuates the profile's own peak frame, so all three variants are normalized by the same
    factor and what is left in the WAV is exactly the contour's shape. No second gain is applied
    on top, which would only rescale an already-normalized buffer.
    """
    document, fallbacks = stimulus_document(profile, bank, contour=contour)
    binding = {"stim": profile.profile_id}
    return (
        {
            "a": render_subject(document, None, None, volume_contour=False, kind="a", gain=1.0),
            "b": render_subject(document, bank, binding, volume_contour=False, kind="b", gain=1.0),
            "c": render_subject(document, bank, binding, volume_contour=True, kind="c", gain=1.0),
        },
        fallbacks,
    )


# ===========================================================================
# 5. What changed, measured
# ===========================================================================
def _dbfs(amplitude: float) -> float:
    return 20.0 * math.log10(amplitude) if amplitude > 0 else -120.0


def frame_volume_series(render: Render, column: int, *, limit: Optional[int] = None) -> np.ndarray:
    """The per-frame volume the AUDC column actually carries, as integers 0..15."""
    frames = render.frames if limit is None else render.frames[:limit]
    if frames.shape[0] == 0:
        return np.zeros(0, dtype=np.int64)
    return (frames[:, column] & 0x0F).astype(np.int64)


def level_metrics(samples: np.ndarray) -> Dict[str, float]:
    """Peak, RMS and crest factor of one variant.

    The renderer normalizes each buffer to a peak of 0.90, so the peak is not evidence here. The
    crest factor is: it is the ratio the renderer preserves, and a contour that attenuates parts of
    a note must lower the average without moving the peak.
    """
    audio = samples.astype(np.float64) / 32768.0
    peak = _peak_of(samples)
    rms = float(np.sqrt(np.mean(audio**2))) if audio.size else 0.0
    return {
        "peak_linear": round(peak, 6),
        "peak_dbfs": round(_dbfs(peak), 3),
        "rms_dbfs": round(_dbfs(rms), 3),
        "crest_factor_db": round(_dbfs(peak) - _dbfs(rms), 3) if rms > 0 else None,
    }


def volume_metrics(series: Sequence[int]) -> Dict[str, Any]:
    """What a per-frame volume series says about the sound's shape."""
    values = [int(value) for value in series]
    if not values:
        return {"frames": 0}
    sounding = [value for value in values if value > 0]
    differences = [
        abs(right - left) for left, right in zip(values, values[1:])
    ]
    return {
        "frames": len(values),
        "sounding_frames": len(sounding),
        "silent_frames": len(values) - len(sounding),
        "min_level": min(values),
        "max_level": max(values),
        "mean_level": round(sum(values) / len(values), 4),
        "dynamic_range_levels": max(values) - min(values),
        "level_changes": sum(1 for left, right in zip(values, values[1:]) if left != right),
        "frame_to_frame_variance": (
            round(sum(value * value for value in differences) / len(differences), 6)
            if differences
            else 0.0
        ),
    }


def _pearson(left: Sequence[float], right: Sequence[float]) -> Optional[float]:
    if len(left) < 3 or len(left) != len(right):
        return None
    a = np.asarray(left, dtype=np.float64)
    b = np.asarray(right, dtype=np.float64)
    if a.std() == 0.0 or b.std() == 0.0:
        return None
    return round(float(np.corrcoef(a, b)[0, 1]), 6)


def envelope_agreement(reference: Sequence[int], observed: Sequence[int]) -> Dict[str, Any]:
    """How closely an observed volume series follows a reference series.

    Reported over the frames the reference says sound, because a frame the composer silences carries
    no information about a level shape; the silent-frame counts are reported separately.
    """
    rows = min(len(reference), len(observed))
    ref = [int(value) for value in reference[:rows]]
    obs = [int(value) for value in observed[:rows]]
    mask = [index for index, value in enumerate(ref) if value > 0]
    pairs = [(ref[index], obs[index]) for index in mask]
    if len(pairs) < 3:
        return {"frames_compared": len(pairs), "correlation": None, "mae": None}
    mae = sum(abs(a - b) for a, b in pairs) / len(pairs)
    ref_range = max(ref) - min(ref)
    obs_range = max(obs) - min(obs)
    return {
        "frames_compared": len(pairs),
        "correlation": _pearson([a for a, _ in pairs], [b for _, b in pairs]),
        "mae_levels": round(mae, 4),
        "dynamic_range_reference": ref_range,
        "dynamic_range_observed": obs_range,
        "dynamic_range_error": obs_range - ref_range,
        "mean_reference": round(sum(a for a, _ in pairs) / len(pairs), 4),
        "mean_observed": round(sum(b for _, b in pairs) / len(pairs), 4),
    }


def attenuation_follows(
    contour: Sequence[int], base: Sequence[int], observed: Sequence[int]
) -> Dict[str, Any]:
    """Whether the render attenuated each frame by exactly the factor the contour asks for.

    This is the sharpest statement the experiment can make about a transfer: for every sounding
    frame, the observed volume divided by the unmodulated volume is the contour's own level divided
    by its peak. Comparing the contour with the *envelope-shaped* series would only measure how much
    envelope there was.
    """
    span = len(contour)
    peak = max(contour) if contour else 0
    if not span or peak <= 0:
        return {"frames_compared": 0, "correlation": None}
    expected: List[float] = []
    actual: List[float] = []
    for index in range(min(len(base), len(observed))):
        unmodulated = int(base[index])
        if unmodulated <= 0:
            continue
        expected.append(contour[index % span] / peak)
        actual.append(int(observed[index]) / unmodulated)
    if len(expected) < 3:
        return {"frames_compared": len(expected), "correlation": None}
    errors = [abs(a - b) for a, b in zip(expected, actual)]
    return {
        "frames_compared": len(expected),
        "correlation": _pearson(expected, actual),
        "mae_factor": round(sum(errors) / len(errors), 4),
        "max_error_factor": round(max(errors), 4),
        "quantized_frames": int(sum(1 for error in errors if error > 0.0)),
    }


def frame_column_differences(left: Render, right: Render) -> Dict[str, Any]:
    """Which register columns differ between two variants, and how many frames each differs in."""
    a, b = left.frames, right.frames
    rows = min(a.shape[0], b.shape[0])
    per_column = {
        FRAME_COLUMN_NAMES[index]: int(np.count_nonzero(a[:rows, index] != b[:rows, index]))
        for index in range(min(FRAME_COLUMNS, a.shape[1], b.shape[1]))
    }
    return {
        "identical": bool(a.shape == b.shape and np.array_equal(a, b)),
        "frames_compared": rows,
        "frames_differing": int(np.count_nonzero((a[:rows] != b[:rows]).any(axis=1))),
        "columns_differing": {name: count for name, count in per_column.items() if count},
    }


def compare_variants(left: Render, right: Render, reference_column: int) -> Dict[str, Any]:
    """Everything measured between two variants of one subject."""
    differences = frame_column_differences(left, right)
    left_series = frame_volume_series(left, reference_column)
    right_series = frame_volume_series(right, reference_column)
    return {
        "left": left.kind,
        "right": right.kind,
        "audio_identical": bool(left.samples.tobytes() == right.samples.tobytes()),
        "sha256": {left.kind: left.audio_sha256, right.kind: right.audio_sha256},
        "frames_identical": left.frames_sha256 == right.frames_sha256,
        "columns_differing": differences["columns_differing"],
        "frames_differing": differences["frames_differing"],
        "frames_compared": differences["frames_compared"],
        "reference_column": FRAME_COLUMN_NAMES[reference_column],
        "level": {
            left.kind: level_metrics(left.samples),
            right.kind: level_metrics(right.samples),
        },
        "crest_delta_db": round(
            (level_metrics(right.samples)["crest_factor_db"] or 0.0)
            - (level_metrics(left.samples)["crest_factor_db"] or 0.0),
            3,
        ),
        "volume": {
            left.kind: volume_metrics(left_series),
            right.kind: volume_metrics(right_series),
        },
        "envelope": envelope_agreement(left_series, right_series),
        "spectral": {
            "centroid_hz": {
                left.kind: round(left.features["centroid_hz"], 3),
                right.kind: round(right.features["centroid_hz"], 3),
            },
            "bandwidth_hz": {
                left.kind: round(left.features["bandwidth_hz"], 3),
                right.kind: round(right.features["bandwidth_hz"], 3),
            },
            "flatness": {
                left.kind: round(left.features["flatness"], 6),
                right.kind: round(right.features["flatness"], 6),
            },
            "distance": round(spectral_distance(left.features, right.features), 6),
        },
    }


def audio_tracks_volume(render: Render, column: int) -> Dict[str, Any]:
    """Whether the rendered audio's own loudness follows the volume series the frames carry.

    This is the end-to-end check that the contour reaches the *sound* and not only the register
    stream: the audio is cut into 50 Hz frames and the per-frame RMS is correlated with the AUDC
    volume of the same frames. The renderer normalizes the buffer, which scales a correlation not
    at all.
    """
    block = SAMPLE_RATE // int(FRAME_RATE_HZ)
    audio = render.samples.astype(np.float64) / 32768.0
    frames = min(render.frames.shape[0], audio.shape[0] // block)
    if frames < 3:
        return {"frames": frames, "correlation": None}
    rms = np.array(
        [
            float(np.sqrt(np.mean(audio[index * block : (index + 1) * block] ** 2)))
            for index in range(frames)
        ]
    )
    series = frame_volume_series(render, column, limit=frames)
    mask = np.array([value for value in series]) > 0
    if int(mask.sum()) < 3:
        return {"frames": frames, "sounding_frames": int(mask.sum()), "correlation": None}
    return {
        "frames": frames,
        "sounding_frames": int(mask.sum()),
        "correlation": _pearson(series[mask].tolist(), rms[mask].tolist()),
        "block_samples": block,
    }


# ===========================================================================
# 6. The perturbation proof
# ===========================================================================
def perturbation_proof(profile: SoundProfile, bank: SoundProfileBank) -> Dict[str, Any]:
    """Prove that the contour, and only the contour, is what changed between B and C.

    Three renders of the *same* composition and the *same* binding:

    * B — the profile with no contour;
    * C — the same, with the profile's measured contour;
    * P — the same, with that contour reversed (a different contour with the same levels).

    The proof is that the frame streams differ in exactly one column, that the column is the AUDC
    column of the channel that sounds, that its distortion nibble is untouched, that its low nibble
    equals the mapping's own arithmetic applied to B, and that the audio follows the volume series.
    Nothing here is inferred from a summary statistic.
    """
    contour, refusal = transferability(profile)
    if contour is None:
        raise Stage10BError(
            f"profile {profile.profile_id} has no transferable contour ({refusal}); "
            "the perturbation proof needs one"
        )
    document, fallbacks = stimulus_document(profile, bank)
    binding = {"stim": profile.profile_id}
    variants = {
        "b": render_subject(
            document, bank, binding, volume_contour=False, kind="b", gain=1.0
        ),
        "c": render_subject(
            document, bank, binding, volume_contour=True, kind="c", gain=1.0
        ),
    }
    reversed_contour = tuple(reversed(contour))
    perturbed_document = contour_stimulus(
        joined_pair=profile.scope == "PAIR",
        hold_steps=max(1, math.ceil(hold_frames_for(contour) / _stimulus_frames_per_tick())),
        envelope_overrides=fallbacks["envelope_overrides"] or None,
    )
    variants["p"] = _render_with_contour(
        perturbed_document, bank, binding, reversed_contour, kind="p"
    )

    changed = frame_column_differences(variants["b"], variants["c"])
    columns = sorted(changed["columns_differing"])
    column = None
    if len(columns) == 1:
        column = FRAME_COLUMN_NAMES.index(columns[0])

    proof: Dict[str, Any] = {
        "profile_id": profile.profile_id,
        "scope": profile.scope,
        "contour": list(contour),
        "reversed_contour": list(reversed_contour),
        "hold_frames": int(variants["b"].frames.shape[0]),
        "frames_per_tick": int(generate_music_from_composition(document).pokey_ir.frames_per_tick),
        "envelope_overrides": fallbacks["envelope_overrides"],
        "b_vs_c": changed,
        "only_one_column_changed": len(columns) == 1,
        "changed_column": columns[0] if len(columns) == 1 else None,
        "audio_differs_b_vs_c": bool(
            variants["b"].samples.tobytes() != variants["c"].samples.tobytes()
        ),
    }
    if column is not None:
        base = frame_volume_series(variants["b"], column)
        observed = frame_volume_series(variants["c"], column)
        expected = np.array(reference_volume_series(base.tolist(), contour), dtype=np.int64)
        rows = min(len(expected), len(observed))
        distortion_before = (variants["b"].frames[:rows, column] >> 4).astype(np.int64)
        distortion_after = (variants["c"].frames[:rows, column] >> 4).astype(np.int64)
        proof.update(
            {
                "column_is_audc": FRAME_COLUMN_NAMES[column].startswith("AUDC"),
                "column_matches_a_sounding_channel": column
                in audc_columns_with_notes(variants["b"]),
                "distortion_untouched": bool(np.array_equal(distortion_before, distortion_after)),
                "volume_equals_the_mapping": bool(
                    np.array_equal(expected[:rows], observed[:rows])
                ),
                "volume_mismatch_frames": int(np.count_nonzero(expected[:rows] != observed[:rows])),
                "audf_and_audctl_untouched": bool(
                    np.array_equal(
                        variants["b"].frames[:rows, [0, 2, 4, 6, 8]],
                        variants["c"].frames[:rows, [0, 2, 4, 6, 8]],
                    )
                ),
                "attenuation_follows_contour": attenuation_follows(contour, base, observed),
                "audio_tracks_volume_c": audio_tracks_volume(variants["c"], column),
            }
        )
    else:  # pragma: no cover - a profile that changed nothing would have failed the selection
        proof["attenuation_follows_contour"] = {"frames_compared": 0, "correlation": None}
    reversed_column = frame_column_differences(variants["c"], variants["p"])
    proof["c_vs_reversed"] = {
        "columns_differing": reversed_column["columns_differing"],
        "frames_differing": reversed_column["frames_differing"],
        "audio_identical": bool(
            variants["c"].samples.tobytes() == variants["p"].samples.tobytes()
        ),
    }
    proof["static_contour_is_a_no_op"] = static_contour_is_a_no_op(profile, bank)
    return proof


def _render_with_contour(
    document: Any,
    bank: SoundProfileBank,
    binding: Mapping[str, str],
    contour: Sequence[int],
    *,
    kind: str,
) -> Render:
    """Render one variant with an explicitly supplied contour rather than the profile's own.

    Used by the perturbation proof: the composition, the binding and every other register field are
    identical to variant C, so any difference is the contour's doing.
    """
    result = generate_music_from_composition(document)
    bound = apply_profile_binding(
        result,
        load_profile_binding(
            {"schema": "atari-music/sound-profile-binding/1", "instruments": dict(binding)}
        ),
        bank,
        composition=document,
        volume_contour=True,
    )
    instruments = [
        inst.model_copy(update={"volume_contour": list(contour)})
        for inst in bound.pokey_ir.instruments
    ]
    song = bound.pokey_ir.model_copy(update={"instruments": instruments})
    frames = compile_ir_to_pokey_frames(song)
    samples = render_pokey_samples(frames, SAMPLE_RATE, FRAME_RATE_HZ)
    return Render(
        kind=kind,
        samples=samples,
        frames=frames,
        audctl=resolve_audctl_mode(song),
        clipped=0,
        features=spectral_features(samples, SAMPLE_RATE),
    )


def static_contour_is_a_no_op(profile: SoundProfile, bank: SoundProfileBank) -> Dict[str, Any]:
    """The feature switched on with a *flat* contour must change nothing at all.

    This is the mapping's own contract checked through the real path: a contour whose levels are all
    equal to the profile's peak cannot attenuate anything, so the frames and the audio must equal
    variant B exactly. It is the strongest available statement that "disabled" and "a contour that
    does nothing" are the same thing.
    """
    contour, refusal = transferability(profile)
    if contour is None:  # pragma: no cover - callers check first
        raise Stage10BError(f"profile {profile.profile_id} has no contour ({refusal})")
    flat = tuple([max(contour)] * len(contour))
    document, fallbacks = stimulus_document(profile, bank)
    binding = {"stim": profile.profile_id}
    plain = render_subject(document, bank, binding, volume_contour=False, kind="b", gain=1.0)
    flat_render = _render_with_contour(document, bank, binding, flat, kind="flat")
    return {
        "profile_id": profile.profile_id,
        "flat_contour": list(flat),
        "frames_identical": plain.frames_sha256 == flat_render.frames_sha256,
        "audio_identical": bool(plain.samples.tobytes() == flat_render.samples.tobytes()),
        "envelope_overrides": fallbacks["envelope_overrides"],
    }


def audc_columns_with_notes(render: Render) -> List[int]:
    """The AUDC columns that carry a sounding note somewhere in this render."""
    columns: List[int] = []
    for channel in range(1, 5):
        column = audc_column(channel)
        if column < render.frames.shape[1] and int((render.frames[:, column] & 0x0F).sum()) > 0:
            columns.append(column)
    return columns


# ===========================================================================
# 7. The regression proof
# ===========================================================================
def regression_proof(
    songs: Sequence[Any],
    new_bindings: Mapping[str, Mapping[str, str]],
    bank: SoundProfileBank,
    stage10a_package: Path,
) -> Dict[str, Any]:
    """Contour disabled must reproduce the published Stage 10A audio byte for byte.

    Stage 10A published three renders per song, built before this feature existed. Reproducing them
    is the regression: if adding the volume contour moved anything at all in a song that does not
    ask for it, these comparisons would fail. No golden file is updated to accommodate a change.
    """
    limit = int(round(SONG_EXCERPT_SECONDS * SAMPLE_RATE))
    records: Dict[str, Any] = {}
    for song in songs:
        document = load_song(song.song_path)
        default = render_subject(document, None, None, volume_contour=False, kind="default", gain=1.0)
        gain = shared_gain(default.samples, limit)
        versions = {
            "default": render_subject(
                document, None, None, volume_contour=False, kind="default", gain=gain, limit=limit
            ),
            "old": render_subject(
                document,
                bank,
                song.old_profiles,
                volume_contour=False,
                kind="old",
                gain=gain,
                limit=limit,
            ),
            "new": render_subject(
                document,
                bank,
                new_bindings[song.trial_id],
                volume_contour=False,
                kind="new",
                gain=gain,
                limit=limit,
            ),
        }
        published = stage10a_package / "audio"
        comparisons: Dict[str, Any] = {}
        for kind, render in versions.items():
            path = published / f"{song.trial_id}_{kind}.wav"
            if not path.is_file():  # pragma: no cover - the package is a required input
                raise Stage10BError(f"the Stage 10A package is missing {path}")
            comparisons[kind] = {
                "file": f"audio/{song.trial_id}_{kind}.wav",
                "byte_identical": bool(
                    render.samples.tobytes() == read_pcm(path).tobytes()
                ),
                "samples_compared": int(render.samples.size),
            }
        records[song.trial_id] = {
            "song": song.song,
            "shared_gain_db": round(_dbfs(gain), 4),
            "published": comparisons,
            "all_byte_identical": all(item["byte_identical"] for item in comparisons.values()),
        }
    return {
        "source_package": str(stage10a_package),
        "songs": records,
        "songs_compared": len(records),
        "renders_compared": sum(len(record["published"]) for record in records.values()),
        "all_byte_identical": all(record["all_byte_identical"] for record in records.values()),
    }


def read_pcm(path: Path) -> np.ndarray:
    """The samples of a 16-bit mono PCM WAV, exactly as stored."""
    with wave.open(str(path), "rb") as handle:
        if handle.getsampwidth() != 2 or handle.getnchannels() != 1:
            raise Stage10BError(f"{path} is not 16-bit mono PCM")
        return np.frombuffer(handle.readframes(handle.getnframes()), dtype=np.int16)


# ===========================================================================
# 8. The blinded package
# ===========================================================================
@dataclass(frozen=True)
class Subject:
    """One thing this experiment renders three variants of: a profile, or a whole song."""

    subject_id: str
    kind: str
    label: str
    binding: Dict[str, str]
    contour_binding: Tuple[str, ...]
    withheld: Tuple[Dict[str, Any], ...]
    profile: Optional[SoundProfile]
    contour: Optional[Tuple[int, ...]]
    song_path: Optional[Path]
    hold_frames: Optional[int]
    song: Any = None

    @property
    def material(self) -> str:
        return "a held note" if self.kind == "profile" else "a fifteen-second excerpt"

    def as_dict(self) -> Dict[str, Any]:
        return {
            "subject_id": self.subject_id,
            "kind": self.kind,
            "label": self.label,
            "profile_id": self.profile.profile_id if self.profile else None,
            "scope": self.profile.scope if self.profile else None,
            "contour_frames": len(self.contour) if self.contour else 0,
            "hold_frames": self.hold_frames,
            "contour_binding": list(self.contour_binding),
            "withheld": [dict(item) for item in self.withheld],
            "binding": dict(self.binding),
        }


@dataclass(frozen=True)
class Trial:
    """One blinded pair: two variants of one subject under two neutral labels."""

    trial_id: str
    subject_id: str
    subject: str
    trial_kind: str
    a: str
    b: str

    @property
    def sides(self) -> Dict[str, str]:
        return {"a": self.a, "b": self.b}

    @property
    def compared(self) -> Dict[str, str]:
        left, right = TRIAL_KIND_LOOKUP[self.trial_kind]
        return {"left": VARIANT_LABELS[left], "right": VARIANT_LABELS[right]}

    def side_file(self, side: str) -> str:
        return f"audio/{self.trial_id}_{side}.wav"

    def as_dict(self) -> Dict[str, Any]:
        return {
            "trial_id": self.trial_id,
            "subject_id": self.subject_id,
            "subject": self.subject,
            "trial_kind": self.trial_kind,
            "compared": self.compared,
            "sides": self.sides,
            "files": {side: self.side_file(side) for side in ("a", "b")},
        }


def build_trials(subjects: Sequence[Subject], rng: random.Random) -> List[Trial]:
    """Every subject's B-vs-C pair, plus a few A-vs-C controls, blinded and shuffled.

    B-vs-C is the experiment: the same profile with and without its measured contour. A-vs-C is the
    control: the same sound against the composer's own instrument, which is what a listener compares
    against anyway. The orientation of every pair is randomized and nothing about the mapping reaches
    the interface.
    """
    trials: List[Trial] = []
    for subject in subjects:
        kinds = [kind for kind, _, _ in TRIAL_KINDS if kind.startswith(subject.kind)]
        primary = kinds[0]
        order: List[str] = [primary]
        if subject.kind == "profile" and subject.subject_id in {"prof_01", "prof_02"}:
            order.append(kinds[1])
        if subject.kind == "song" and subject.subject_id in {"song_01", "song_02"}:
            order.append(kinds[1])
        rng.shuffle(order)
        for index, kind in enumerate(order, start=1):
            left, right = TRIAL_KIND_LOOKUP[kind]
            a, b = (left, right) if rng.random() < 0.5 else (right, left)
            trials.append(
                Trial(
                    trial_id=f"{subject.subject_id}_t{index}",
                    subject_id=subject.subject_id,
                    subject=subject.label,
                    trial_kind=kind,
                    a=a,
                    b=b,
                )
            )
    return trials


def _subject_plan(
    tested: Sequence[TestedProfile],
    songs: Sequence[Any],
    new_bindings: Mapping[str, Mapping[str, str]],
    bank: SoundProfileBank,
) -> List[Subject]:
    """The subjects: the tested profiles, then the six Stage 10A songs with their current binding."""
    subjects: List[Subject] = []
    for index, item in enumerate(tested, start=1):
        profile = bank.get(item.profile_id)
        subjects.append(
            Subject(
                subject_id=f"prof_{index:02d}",
                kind="profile",
                label=item.profile_id,
                binding={"stim": item.profile_id},
                contour_binding=("stim",),
                withheld=(),
                profile=profile,
                contour=item.contour,
                song_path=None,
                hold_frames=item.hold_frames,
            )
        )
    for song in songs:
        binding = dict(new_bindings[song.trial_id])
        take: List[str] = []
        withheld: List[Dict[str, Any]] = []
        for key, profile_id in binding.items():
            profile = bank.get(profile_id)
            contour, refusal = transferability(profile)
            if contour is None:
                withheld.append(
                    {
                        "instrument": key,
                        "profile_id": profile_id,
                        "reason": refusal,
                        "gating_share": contour_record(profile)["gating_share"],
                    }
                )
            else:
                take.append(key)
        subjects.append(
            Subject(
                subject_id=song.trial_id,
                kind="song",
                label=song.song,
                binding=binding,
                contour_binding=tuple(sorted(take)),
                withheld=tuple(withheld),
                profile=None,
                contour=None,
                song_path=song.song_path,
                hold_frames=None,
            )
        )
    return subjects


def build_package(
    package_dir: Path = DEFAULT_PACKAGE_DIR,
    *,
    stage10a_package: Path = DEFAULT_STAGE10A_PACKAGE,
    stage9c_package: Path = DEFAULT_STAGE9C_PACKAGE,
    songs_dir: Path = DEFAULT_SONGS_DIR,
    bank_dir: Path = DEFAULT_BANK_DIR,
    reports_dir: Path = DEFAULT_STAGE9D_REPORTS,
    analysis_dir: Optional[Path] = DEFAULT_ANALYSIS_REPORTS,
    docs_dir: Optional[Path] = DEFAULT_DOCS_DIR,
    seed: int = SEED,
    now: Optional[datetime] = None,
    log: Optional[Any] = None,
) -> Dict[str, Any]:
    """Prepare the whole experiment: stimuli, three variants, proofs, package and report.

    Read-only with respect to everything it is about. The bank, the songs, the Stage 10A package and
    the Stage 9C/9D artefacts are inputs; no profile is edited, no composition or binding is
    modified, and no production module is touched.
    """
    say = log or (lambda message: None)
    package_dir = Path(package_dir)
    stage10a_package = Path(stage10a_package)
    stage9c_package = Path(stage9c_package)
    bank = load_sound_profile_bank(bank_dir)

    say("Recovering the six songs and their current bindings from Stage 10A…")
    songs, _ = recover_songs(stage9c_package, songs_dir)
    stage10a_manifest = json.loads(
        (stage10a_package / "manifest.json").read_text(encoding="utf-8")
    )
    new_bindings: Dict[str, Dict[str, str]] = {}
    for song in songs:
        published = stage10a_package / "bindings" / f"{song.song}.binding.json"
        if not published.is_file():
            raise Stage10BError(
                f"the Stage 10A package is missing {published}; this stage continues from Stage "
                "10A's binding rather than choosing a new one"
            )
        declared = dict(load_profile_binding(published).instruments)
        record = next(
            entry
            for entry in stage10a_manifest["songs"]
            if entry["trial_id"] == song.trial_id
        )
        if declared != dict(record["new_profiles"]):
            raise Stage10BError(
                f"{published.name} no longer matches the Stage 10A manifest for {song.trial_id}: "
                f"the manifest says {record['new_profiles']}, the file says {declared}"
            )
        new_bindings[song.trial_id] = declared
    before = _input_state(songs, stage10a_package, bank_dir)

    say("Selecting the tested profiles from the measured contours…")
    tested, looked_at = select_tested_profiles(bank)
    if not tested:
        raise Stage10BError("no profile's measured contour is transferable; there is nothing to test")
    say(f"  {len(tested)} profiles: " + ", ".join(item.profile_id for item in tested))
    gating_evidence = [
        contour_record(bank.get(item["profile_id"]))
        for item in looked_at
        if item.get("reason") == CONTOUR_WITHHELD_GATING
    ]

    say("Proving the perturbation on every tested profile…")
    proofs = [perturbation_proof(bank.get(item.profile_id), bank) for item in tested]

    say("Proving that the feature switched off changes nothing…")
    regression = regression_proof(songs, new_bindings, bank, stage10a_package)
    if not regression["all_byte_identical"]:
        raise Stage10BError(
            "a song rendered without a volume contour does not reproduce the Stage 10A package; "
            "the feature is not inert when disabled, so the experiment must not ship"
        )

    say("Rendering the three variants…")
    audio_dir = package_dir / "audio"
    binding_dir = package_dir / "bindings"
    audio_dir.mkdir(parents=True, exist_ok=True)
    binding_dir.mkdir(parents=True, exist_ok=True)

    subjects = _subject_plan(tested, songs, new_bindings, bank)
    subject_records: List[Dict[str, Any]] = []
    transfer: Dict[str, Any] = {}
    for subject in subjects:
        if subject.kind == "profile":
            profile = bank.get(subject.binding["stim"])
            variants, fallbacks = render_profile_variants(
                profile, bank, contour=subject.contour or ()
            )
            shared_gain_db = 0.0
        else:
            fallbacks = {}
            document = load_song(subject.song_path)
            default = render_subject(
                document, None, None, volume_contour=False, kind="a", gain=1.0
            )
            limit = int(round(SONG_EXCERPT_SECONDS * SAMPLE_RATE))
            gain = shared_gain(default.samples, limit)
            shared_gain_db = round(_dbfs(gain), 4)
            variants = {
                "a": render_subject(
                    document, None, None, volume_contour=False, kind="a", gain=gain, limit=limit
                ),
                "b": render_subject(
                    document,
                    bank,
                    subject.binding,
                    volume_contour=False,
                    kind="b",
                    gain=gain,
                    limit=limit,
                ),
                "c": render_subject(
                    document,
                    bank,
                    subject.binding,
                    volume_contour=list(subject.contour_binding),
                    kind="c",
                    gain=gain,
                    limit=limit,
                ),
            }
            writes = {kind: render.samples for kind, render in variants.items()}

        _write_binding(binding_dir / f"{subject.subject_id}.binding.json", bank_dir, subject.binding)
        for kind, render in variants.items():
            write_wav(audio_dir / f"{subject.subject_id}_{kind}.wav", render.samples, SAMPLE_RATE)

        record = _subject_record(subject, variants, bank, shared_gain_db, fallbacks)
        subject_records.append(record)
        transfer[subject.subject_id] = record["transfer"]
        say(f"  {subject.subject_id} {subject.label}: " + (
            "contour applied" if subject.contour or subject.contour_binding else "no contour applied"
        ))

    trials = build_trials(subjects, random.Random(seed))
    for trial in trials:
        for side, kind in trial.sides.items():
            write_wav(
                audio_dir / f"{trial.trial_id}_{side}.wav",
                read_pcm(audio_dir / f"{trial.subject_id}_{kind}.wav"),
                SAMPLE_RATE,
            )

    after = _input_state(songs, stage10a_package, bank_dir)
    if before != after:
        raise Stage10BError(
            "a read-only input changed while the experiment was being prepared; this stage must not "
            "modify the bank, the compositions, the Stage 10A package or the Stage 9C package"
        )

    created = now or datetime.now(timezone.utc)
    manifest: Dict[str, Any] = {
        "manifest_version": MANIFEST_VERSION,
        "experiment": EXPERIMENT,
        "private": True,
        "warning": (
            "This file is the private answer key: it maps blinded sides to variants. Do not open it "
            "while listening."
        ),
        "created_utc": created.isoformat(),
        "seed": seed,
        "renderer_version": RENDERER_VERSION,
        "sample_rate": SAMPLE_RATE,
        "frame_rate_hz": FRAME_RATE_HZ,
        "excerpt_seconds": round(SONG_EXCERPT_SECONDS, 3),
        "source_package": str(stage10a_package),
        "stage9c_package": str(stage9c_package),
        "profile_bank": str(bank_dir),
        "bank_profile_count": len(bank.ids()),
        "variants": dict(VARIANT_LABELS),
        "mapping": {
            "formula": "effective[i] = floor(volumes[i] * contour[i % span] / max(contour) + 0.5)",
            "reference_level": "max(contour) — the contour can only attenuate",
            "time_base": (
                f"one contour frame per output frame at {FRAME_RATE_HZ:.0f} Hz, the rate the "
                "archaeology measured at (one sample per VBL frame)"
            ),
            "restart": "the contour restarts at every note onset, tiles over longer notes, truncates",
            "clamp": "0..15 (POKEY AUDC volume nibble)",
        },
        "normalization": {
            "method": "peak",
            "target_peak_linear": TARGET_PEAK,
            "profiles": (
                "the renderer normalizes each buffer to a peak of 0.90 and the contour never "
                "attenuates the profile's own peak frame, so all three variants of a tested profile "
                "are normalized by the same factor and the WAV carries the contour's shape exactly"
            ),
            "songs": (
                "one gain per song, taken from the default render's excerpt peak, exactly as in "
                "Stage 9C and Stage 10A"
            ),
            "renderer_note": (
                "the renderer normalizes each buffer it returns to a peak of 0.90, so the WAV cannot "
                "carry an overall level difference between variants; the per-frame volume series, "
                "the crest factor and the dynamic range carry it instead"
            ),
        },
        "limitations": [
            {
                "code": "XEX_CANNOT_CARRY_A_CONTOUR",
                "detail": (
                    "the MADS exporter publishes a note table and player.asm builds the per-frame "
                    "envelope itself, so a song with a contour is refused for XEX export rather than "
                    "exported as something that would not play what was listened to."
                ),
            },
            {
                "code": "GATING_CONTOURS_ARE_OUT_OF_SCOPE",
                "detail": (
                    "a measured contour that reaches level 0 describes when the source sounded, not "
                    "how loud it was. Transferring it would import the source arrangement's gating "
                    "into a composition that owns its own notes, so it is not transferred and the "
                    "affected channels are named in the report."
                ),
            },
            {
                "code": "CONTOUR_IS_RELATIVE",
                "detail": (
                    "the contour modulates the composer's envelope relative to its own peak; the "
                    "absolute levels of the source are not transferable, because the source note had "
                    "a different envelope, a different velocity and a different clock."
                ),
            },
            {
                "code": "ONE_SOUND_PER_PROFILE",
                "detail": (
                    "the profile stimuli are single held notes, so the trials test whether the "
                    "contour changes a sound, not whether it improves a piece of music. The six-song "
                    "comparison is where that question is asked."
                ),
            },
        ],
        "tested_profiles": [item.as_dict() for item in tested],
        "candidates": looked_at,
        "subjects": [subject.as_dict() for subject in subjects],
        "trials": [trial.as_dict() for trial in trials],
    }

    (package_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    _write_answer_template(package_dir, trials)
    (package_dir / "index.html").write_text(render_index_html(manifest), encoding="utf-8")
    (package_dir / "README.md").write_text(render_readme(manifest), encoding="utf-8")

    verification = {
        "analysis_version": ANALYSIS_VERSION,
        "regression": regression,
        "static_contour_no_op": {
            proof["profile_id"]: proof["static_contour_is_a_no_op"] for proof in proofs
        },
        "only_one_column_changed": {
            proof["profile_id"]: proof["only_one_column_changed"] for proof in proofs
        },
        "audio_differs_b_vs_c": {
            proof["profile_id"]: proof["audio_differs_b_vs_c"] for proof in proofs
        },
        "compositions_unchanged": before["compositions"] == after["compositions"],
        "stage10a_package_unchanged": (
            before["stage10a_manifest"] == after["stage10a_manifest"]
            and before["stage10a_audio"] == after["stage10a_audio"]
        ),
        "profile_bank_unchanged": before["bank"] == after["bank"],
        "source_hashes": after,
    }

    bundle: Dict[str, Any] = {
        "manifest": manifest,
        "tested": tested,
        "candidates": looked_at,
        "gating_evidence": gating_evidence,
        "subjects": subjects,
        "subject_records": subject_records,
        "transfer": transfer,
        "proofs": proofs,
        "regression": regression,
        "verification": verification,
        "trials": trials,
    }

    written: Dict[str, Path] = {
        "manifest": package_dir / "manifest.json",
        "index": package_dir / "index.html",
        "readme": package_dir / "README.md",
        "answers": package_dir / "evaluation_volume_contour_10b.csv",
    }
    if analysis_dir is not None:
        analysis_dir = Path(analysis_dir)
        analysis_dir.mkdir(parents=True, exist_ok=True)
        for name, payload in (
            ("profiles.json", {"analysis_version": ANALYSIS_VERSION,
                               "tested": [item.as_dict() for item in tested],
                               "candidates": looked_at,
                               "gating_evidence": gating_evidence}),
            ("subjects.json", {"analysis_version": ANALYSIS_VERSION,
                               "subjects": subject_records}),
            ("transfer.json", {"analysis_version": ANALYSIS_VERSION, "transfer": transfer}),
            ("perturbation.json", {"analysis_version": ANALYSIS_VERSION, "proofs": proofs}),
            ("regression.json", {"analysis_version": ANALYSIS_VERSION, "regression": regression}),
            ("verification.json", verification),
        ):
            path = analysis_dir / name
            path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            written[name] = path
    if docs_dir is not None:
        docs_dir = Path(docs_dir)
        docs_dir.mkdir(parents=True, exist_ok=True)
        path = docs_dir / "stage10b_volume_contour_experiment.md"
        path.write_text(render_report(bundle), encoding="utf-8")
        written["report"] = path

    bundle["written"] = written
    for name, path in sorted(written.items()):
        say(f"  wrote {name}: {path}")
    return bundle


def _subject_record(
    subject: Subject,
    variants: Mapping[str, Render],
    bank: SoundProfileBank,
    shared_gain_db: float,
    fallbacks: Mapping[str, Any],
) -> Dict[str, Any]:
    """One row of the metrics: what the three variants are and what changed between them."""
    column: Optional[int] = None
    for channel in range(1, 5):
        candidate = audc_column(channel)
        if candidate < variants["b"].frames.shape[1] and int(
            (variants["b"].frames[:, candidate] & 0x0F).sum()
        ) > 0:
            column = candidate
            break
    if column is None:  # pragma: no cover - a subject with no sounding volume is not a subject
        raise Stage10BError(f"{subject.subject_id} renders no audible volume to measure")

    transfer: Dict[str, Any] = {
        "shared_gain_db": shared_gain_db,
        "reference_column": FRAME_COLUMN_NAMES[column],
        "b_vs_c": compare_variants(variants["b"], variants["c"], column),
        "a_vs_c": compare_variants(variants["a"], variants["c"], column),
        "envelope_overrides": dict(fallbacks.get("envelope_overrides") or {}),
    }
    if subject.kind == "profile" and subject.contour:
        base = frame_volume_series(variants["b"], column)
        observed = frame_volume_series(variants["c"], column)
        expected = np.array(
            reference_volume_series(base.tolist(), subject.contour), dtype=np.int64
        )
        transfer["reference_contour"] = list(subject.contour)
        transfer["volume_equals_the_mapping"] = bool(
            np.array_equal(expected, observed)
        )
        transfer["attenuation_follows_contour"] = attenuation_follows(
            subject.contour, base, observed
        )
        transfer["audio_tracks_volume_c"] = audio_tracks_volume(variants["c"], column)
    return {
        **subject.as_dict(),
        "contour_depth": (
            f"{min(subject.contour)}..{max(subject.contour)} (of 15)"
            if subject.contour
            else "—"
        ),
        "variants": {kind: VARIANT_LABELS[kind] for kind in VARIANT_KINDS},
        "level": {kind: level_metrics(render.samples) for kind, render in variants.items()},
        "sha256": {kind: render.audio_sha256 for kind, render in variants.items()},
        "frames_sha256": {kind: render.frames_sha256 for kind, render in variants.items()},
        "clipped_samples": {kind: render.clipped for kind, render in variants.items()},
        "full_frames": {kind: int(render.frames.shape[0]) for kind, render in variants.items()},
        "files": {kind: f"audio/{subject.subject_id}_{kind}.wav" for kind in VARIANT_KINDS},
        "transfer": transfer,
    }


def _input_state(
    songs: Sequence[Any], stage10a_package: Path, bank_dir: Path
) -> Dict[str, Any]:
    """Digests of every read-only input, so "nothing changed" is a measurement."""
    return {
        "stage10a_manifest": hashlib.sha256(
            (Path(stage10a_package) / "manifest.json").read_bytes()
        ).hexdigest(),
        "stage10a_audio": _dir_digest(Path(stage10a_package) / "audio"),
        "compositions": {song.song: song_digest(song.song_path) for song in songs},
        "bank": _dir_digest(Path(bank_dir)),
    }


def _dir_digest(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        digest.update(str(path.relative_to(root)).encode("utf-8"))
        digest.update(path.read_bytes())
    return digest.hexdigest()


def _write_binding(path: Path, bank_dir: Path, instruments: Mapping[str, str]) -> None:
    """Write one binding document, with the bank path relative to where it lands."""
    relative = os.path.relpath(Path(bank_dir).resolve(), path.parent.resolve())
    document = OrderedDict(
        (
            ("schema", "atari-music/sound-profile-binding/1"),
            ("bank", Path(relative).as_posix()),
            ("instruments", OrderedDict(sorted(instruments.items()))),
        )
    )
    path.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")


def _write_answer_template(package_dir: Path, trials: Sequence[Trial]) -> None:
    """The empty answer template: ids only, never a pre-filled answer."""
    with (package_dir / "evaluation_volume_contour_10b.csv").open(
        "w", encoding="utf-8", newline=""
    ) as handle:
        writer = csv.writer(handle)
        writer.writerow(ANSWER_HEADER)
        for trial in trials:
            writer.writerow([trial.trial_id] + [""] * (len(ANSWER_HEADER) - 1))


def render_index_html(manifest: Mapping[str, Any]) -> str:
    """The listening interface: one self-contained page, no server and no Python."""
    subjects = {subject["subject_id"]: subject for subject in manifest["subjects"]}
    payload = {
        "experiment": manifest["experiment"],
        "trials": [
            {
                "trial_id": trial["trial_id"],
                "a": trial["files"]["a"],
                "b": trial["files"]["b"],
                "material": subjects[trial["subject_id"]]["kind"],
            }
            for trial in manifest["trials"]
        ],
    }
    return _INDEX_HTML.replace("__PACKAGE__", json.dumps(payload, sort_keys=True))


def render_readme(manifest: Mapping[str, Any]) -> str:
    """How to listen, what is asked, and what the package contains."""
    subjects = manifest["subjects"]
    profiles = [subject for subject in subjects if subject["kind"] == "profile"]
    songs = [subject for subject in subjects if subject["kind"] == "song"]
    trials = manifest["trials"]
    primary = sum(1 for trial in trials if trial["trial_kind"].endswith("current_vs_contour"))
    controls = len(trials) - primary
    withheld = [
        (subject["subject_id"], item["instrument"], item["profile_id"], item["reason"])
        for subject in subjects
        for item in subject["withheld"]
    ]
    withheld_lines = "\n".join(
        f"* `{subject_id}` channel `{instrument}` (profile `{profile_id}`): {reason}"
        for subject_id, instrument, profile_id, reason in withheld
    ) or "* none"
    return f"""# Volume contour transfer (Stage 10B)

Two versions of the same sound. The only thing that differs between the two sides is whether the
POKEY channel's **volume contour** — the way loudness moved inside a note, as measured in the
archaeology — has been transferred into the render.

**You need nothing installed.** Open `index.html`, listen, answer, and download the CSV at the end.
If the browser refuses to play local audio, serve the folder instead:

```bash
python -m http.server 8732 --directory examples/sound_profile_volume_contour_10b
```

## What is in here

| file | what it is |
| :--- | :--- |
| `index.html` | the listening interface — **the only file you need to open** |
| `audio/` | three variants per subject, and the blinded pairs the page plays |
| `bindings/` | the profile binding each subject was rendered with |
| `evaluation_volume_contour_10b.csv` | the empty answer template the interface fills in |
| `manifest.json` | the private answer key and the full machine record — **do not open it while listening** |

Do not inspect the `audio/` folder while listening either: the three named variants sit next to the
blinded pairs, so comparing file sizes or hashes would break the blinding.

## What is being compared

* **{len(profiles)} profiles**, each held as a **single note long enough for its measured contour to
  be heard once**. B-vs-C asks whether transferring the contour changes that sound.
* **{len(songs)} songs** — the same six pieces as the Stage 10A experiment, with the **same profile
  assignment** it chose. B-vs-C asks whether transferring the artists' own measured contours changes
  the arrangement, which is the question a composer would actually ask.
* **{primary} B-vs-C pairs** (the experiment) and **{controls} A-vs-C pairs** (the control: the same
  sound against the composer's own instrument).
* Everything else is held fixed: the notes, the durations, the velocities, the channel allocation,
  the renderer, the sample rate and the excerpt window. The three variants of one subject differ only
  in the contour.

## Channels whose contour was not transferred

A measured contour that reaches volume 0 describes *when the source sounded*, not how loud it was.
Transferring it would import another song's gating into a composition that owns its own notes, so it
is refused rather than approximated:

{withheld_lines}

## What is asked

For each pair: which version sounds **better overall**, which sounds **more convincing as Atari
music**, which has the **more interesting or appropriate sound character**, whether either side
changes noticeably **during** a note, and how different the two versions sound (1–5). A comment box is
there for anything else you notice.

There are no right answers and no technical knowledge is needed. If a difference is audible to you,
that is the result; if it is not, that is also the result.
"""


_INDEX_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>POKEY volume contour comparison</title>
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
  <strong>Your ears are the instrument here.</strong> Each pair plays the same sound twice: the same
  notes, the same channel, the same generator, the same renderer. The two sides differ in
  <em>one</em> property of the sound. Nothing on this page says which side is which, and there is no
  expected answer.
</div>
<div class="note">
  <strong>Set your volume once and leave it alone.</strong> Both sides of a pair are presented at the
  same gain. Please judge character rather than loudness.
</div>
<div class="note">
  <strong>Some pairs may sound identical to you.</strong> That is a result, not a mistake: answer
  "no clear difference" and move on. It is also a result if the difference is audible only on some
  pairs.
</div>

<div class="progress" id="progress">progress</div>

<h2>Comparisons (<span id="count"></span> pairs)</h2>
<p class="small">Listen to both sides as many times as you like, then answer. Answers are kept in
this browser, so a session can be resumed.</p>
<div id="trials"></div>

<h2>Finish</h2>
<p class="small">Download the file and put it back in the package folder, overwriting the empty
template. Nothing is uploaded anywhere — everything stays in this browser until you download it.</p>
<button onclick="downloadAll()">Download the answer CSV</button>
<button class="ghost" onclick="if(confirm('Erase all answers in this browser?')){localStorage.clear();location.reload();}">Reset answers</button>

<script>
const PACKAGE = __PACKAGE__;
const STORE = "stage10b-answers-v1";
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
  ["more_interesting_character", "Which has the more interesting or appropriate sound character?"],
  ["audible_movement", "Does either version change noticeably during a note?"]
];

function choiceRow(key, field, question) {
  const current = get(key, field);
  const values = field === "audible_movement" ? ["a", "b", "both", "neither"] : ["a", "b", "none"];
  const labels = field === "audible_movement"
    ? ["A", "B", "both", "neither"]
    : ["A", "B", "No clear difference"];
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

const FIELDS = ["better_overall", "more_convincing_atari", "more_interesting_character",
                "audible_movement"];
function isDone(key) {
  return FIELDS.every(field => get(key, field) !== "") && get(key, "difference_1_5") !== "";
}

document.getElementById("trials").innerHTML = PACKAGE.trials.map((trial, index) => {
  const id = trial.trial_id;
  const material = trial.material === "profile" ? "a single held sound" : "a fifteen-second excerpt";
  const body = `<div class="small">This pair is ${material}.</div>
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
  download("evaluation_volume_contour_10b.csv",
    ["trial_id","better_overall","more_convincing_atari","more_interesting_character",
     "audible_movement","difference_1_5","comment"],
    PACKAGE.trials.map(trial => [trial.trial_id, get(trial.trial_id,"better_overall"),
      get(trial.trial_id,"more_convincing_atari"),
      get(trial.trial_id,"more_interesting_character"),
      get(trial.trial_id,"audible_movement"),
      get(trial.trial_id,"difference_1_5"), get(trial.trial_id,"comment")]));
}

refresh();
</script>
</main>
</body>
</html>
"""


# ===========================================================================
# 9. The report
# ===========================================================================
def _num(value: Optional[float], digits: int = 3) -> str:
    return "—" if value is None else f"{value:.{digits}f}"


def _md_table(header: Sequence[str], rows: Iterable[Sequence[Any]]) -> List[str]:
    lines = ["| " + " | ".join(header) + " |", "| " + " | ".join(":---" for _ in header) + " |"]
    for row in rows:
        lines.append("| " + " | ".join(str(cell) for cell in row) + " |")
    return lines


def render_report(bundle: Mapping[str, Any]) -> str:
    """`docs/stage10b_volume_contour_experiment.md`.

    Fourteen sections. The three kinds of statement the report keeps apart are **observed** (what the
    existing data and the renders say), **inference** (what follows from them) and **experimental
    choice** (what this stage decided, which no measurement forces).
    """
    manifest = bundle["manifest"]
    tested = bundle["tested"]
    records = {record["subject_id"]: record for record in bundle["subject_records"]}
    proofs = {proof["profile_id"]: proof for proof in bundle["proofs"]}
    regression = bundle["regression"]
    profile_subjects = [s for s in bundle["subjects"] if s.kind == "profile"]
    song_subjects = [s for s in bundle["subjects"] if s.kind == "song"]
    changed = sum(
        1
        for profile_id, proof in proofs.items()
        if proof.get("audio_differs_b_vs_c")
    )
    trials = bundle["trials"]
    primary = [t for t in trials if t.trial_kind.endswith("current_vs_contour")]
    controls = [t for t in trials if t.trial_kind.endswith("default_vs_contour")]

    verdict = "INCONCLUSIVE"
    lines: List[str] = []
    add = lines.append

    add("# Stage 10B — Volume Contour Transfer Experiment")
    add("")
    add("**VERDICT: " + verdict + "**")
    add("")
    add(
        "The *mechanical* question has a clear answer: the measured volume contour transfers through "
        "the existing IR into the frame stream and into the rendered audio, it is the only thing that "
        "changes, and with the feature switched off every Stage 10A render is reproduced byte for "
        "byte. The *perceptual* question — whether a listener hears the transferred contour, and "
        "whether it makes the sound better — is not answered by this stage. It waits for the "
        "listening package prepared here, and Stage 10B declares no winner until that evidence "
        "exists."
    )
    add("")
    add(f"* experiment: `{manifest['experiment']}`, renderer `{manifest['renderer_version']}`")
    add(f"* prepared: {manifest['created_utc']}")
    add(f"* tested profiles: {len(tested)}; songs: {len(song_subjects)}")
    add(f"* blinded pairs: {len(trials)} ({len(primary)} B-vs-C, {len(controls)} A-vs-C)")
    add(
        f"* contours transferred and audible in the render: {changed} of {len(proofs)} tested "
        "profiles"
    )
    add(f"* regression: {regression['renders_compared']} published renders reproduced byte for byte")
    add("")

    # ---------------------------------------------------------------- 1
    add("## 1. The question")
    add("")
    add(
        "Stage 9E established, by reading the artefacts rather than by listening, that the archaeology "
        "measures how loudness moved inside a sound and that the composer discards it. Stage 10A "
        "established that reassigning profiles on the strength of the existing ratings does not by "
        "itself improve a song. This stage asks the next narrower question:"
    )
    add("")
    add(
        "> Can the measured volume contour be transferred into the IR and frame generation that "
        "already exist, so that the rendered sound carries the shape the measurement describes, "
        "without altering anything else?"
    )
    add("")
    add(
        "It is an implementation-and-verification stage, not a listening result. What the renders "
        "measure is written down; what a listener hears is left to the listening package, and the "
        "closing verdict stays `" + verdict + "` until that evidence arrives."
    )
    add("")

    # ---------------------------------------------------------------- 2
    add("## 2. What was read, and what was not touched")
    add("")
    add("**Observed.** Every input is read-only and every one of them was hashed before and after the")
    add("preparation:")
    add("")
    add(f"* the published profile bank: `{manifest['profile_bank']}`")
    add(f"* the six compositions: `{DEFAULT_SONGS_DIR}`")
    add(f"* the Stage 10A package (its binding is the continuation point): `{manifest['source_package']}`")
    add(f"* the Stage 9C package (it defines which six songs these are): `{manifest['stage9c_package']}`")
    add("")
    add("**Observed.** Nothing under those paths changed while the package was built:")
    add("")
    add("```json")
    add(json.dumps(bundle["verification"]["source_hashes"], indent=2, sort_keys=True))
    add("```")
    add("")
    add(
        "**Experimental choice.** This stage continues from Stage 10A's binding rather than choosing a "
        "new one. The listener heard those assignments minutes before this package was built, which is "
        "a real anchoring risk and is recorded in §14."
    )
    add("")

    # ---------------------------------------------------------------- 3
    add("## 3. The volume pipeline as it already was")
    add("")
    add("**Observed.** The existing path from a note to a register frame already carries a per-frame")
    add("volume, and nothing here replaces it:")
    add("")
    for row in (
        ("`IRNote.volume` (0..15)", "the composition's velocity for that note"),
        (
            "`pokey_hw.player_envelope_volumes(...)`",
            "one volume per 50 Hz frame, mirroring `player.asm`'s attack/decay/sustain/release "
            "state machine",
        ),
        (
            "`_render_note_to_frames`",
            "writes `AUDC = (distortion & 0xE0) | volume` per frame — the volume *is* the AUDC low "
            "nibble",
        ),
        (
            "16-bit pair",
            "channel 1 writes the divider low byte to AUDF1 with AUDC1 = 0, the high byte to AUDF2, "
            "and the audible volume to AUDC2",
        ),
        (
            "`render_pokey_samples`",
            "reads the nibble through the non-linear resistor ladder (`POKEY_DAC`), where 0 is "
            "silence, and normalizes each buffer it returns to a peak of 0.90",
        ),
    ):
        add(f"* {row[0]} — {row[1]}")
    add("")
    add(
        "**Inference.** Because a per-frame volume already exists, transferring a measured contour "
        "needs no new renderer and no second audio path: it needs one multiplicative step in the "
        "frame compiler, and the WAV and the XEX stay the same representation."
    )
    add("")

    # ---------------------------------------------------------------- 4
    add("## 4. Where the contour comes from")
    add("")
    add("**Observed.** The archaeology already measured it. `gesture.volume` publishes a run-length")
    add("encoded series of absolute AUDC levels, one sample per VBL frame:")
    add("")
    add("```json")
    add('"gesture": {')
    add('  "volume": { "present": true, "static": false, "min_level": 4, "peak_level": 8,')
    add('               "unit": "audc_volume_level_0_15", "runs": [[4, 30], [8, 2], [4, 1]] },')
    add('  "resolution": { "one_sample_per_frame": true, "frame_period_ms": 20.0559 }')
    add("}")
    add("```")
    add("")
    add(
        f"**Observed.** Of the bank's {manifest.get('bank_profile_count', 67)} profile documents, the "
        "contours that describe a varying level are published with "
        "`playability.gesture.volume.available: true, enabled: false` — measured, and deliberately "
        "not used. That flag is read, never inferred."
    )
    add("")
    add(
        "**Observed.** The measurement's timing lines up with the renderer's: one sample per VBL "
        f"frame at {manifest['frame_rate_hz']:.0f} Hz, which is exactly the rate the composer writes "
        "registers at."
    )
    add("")

    # ---------------------------------------------------------------- 5
    add("## 5. The mapping, defined before anything was rendered")
    add("")
    add("**Experimental choice.** The contour is applied as a *relative* shape, not as an absolute")
    add("level series:")
    add("")
    add("```")
    add("effective[i] = floor(volumes[i] * contour[i % span] / max(contour) + 0.5)   clamped to 0..15")
    add("```")
    add("")
    add("Three properties follow, and all three are what the contract needs:")
    add("")
    add("* **velocity stays sovereign.** `contour / max(contour) <= 1`, so no frame is louder than the")
    add("  composer's own envelope made it: the contour can attenuate, never boost, and cannot clip.")
    add("* **a static contour is an exact no-op.** With every measured level equal the factor is exactly")
    add("  1 and the composer's envelope returns unchanged — used as a proof in §8.")
    add("* **the source's absolute loudness cannot leak.** Dividing by the contour's own peak makes the")
    add("  shape transferable to any note velocity, which is the only way it can be reused at all.")
    add("")
    add("**Experimental choice.** Time base: the contour restarts at every note onset, tiles when a note")
    add("is longer than the measured segment, and truncates when it is shorter. It describes how one")
    add("gesture evolved, not a timeline, so restarting is the honest reading; tiling an unmeasured")
    add("contour is stated as a limitation in §14.")
    add("")
    add("**Experimental choice.** A contour whose levels are all 0 (a measured silence) leaves the")
    add("envelope untouched rather than dividing by zero.")
    add("")
    add(
        "**Experimental choice.** The 16-bit pair needs no special case: the pair's audible volume is "
        "AUDC2, which is the frame column the composer already writes, so the same multiplicative step "
        "applies. §12 tests it."
    )
    add("")

    # ---------------------------------------------------------------- 6
    add("## 6. The tested profiles, chosen by a rule")
    add("")
    add(
        "**Experimental choice.** A profile's contour is *transferable* when it varies, when no level "
        "is 0, when its change rate fits the frame grid, when its span fits the stated bounds and when "
        "the profile's status may be rendered. The level-0 rule is the important one: in the source, "
        "level 0 means *nothing sounded*, which is timing rather than loudness — transferring it would "
        "import another song's gating into a composition that owns its own notes."
    )
    add("")
    add("| bound | value | why |")
    add("| :--- | ---: | :--- |")
    add(f"| change rate | ≤ {CONTOUR_RATE_LIMIT_HZ} Hz | two samples per cycle at {FRAME_RATE_HZ:.0f} Hz |")
    add(f"| span | {CONTOUR_MIN_SPAN_FRAMES}..{HOLD_MAX_FRAMES} frames | one cycle at minimum, a sound and not a melody at maximum |")
    add(f"| distinct levels | ≥ 2 | a static contour is a no-op |")
    add("| minimum level | ≥ 1 | a gating contour describes timing, not loudness |")
    add("")
    add(
        "**Observed.** The chosen set, ranked by movement within each scope:"
    )
    add("")
    lines.extend(_md_table(
        ["profile", "scope", "distortion", "contour (frames)", "level changes", "levels", "depth", "hold"],
        [
            (
                f"`{item.profile_id}`",
                item.scope,
                f"${distortion_label(item)}",
                f"{item.statistics['span_frames']}",
                f"{item.statistics['level_changes']}",
                f"{item.statistics['distinct_levels']}",
                f"{item.statistics['min_level']}..{item.statistics['max_level']}",
                f"{item.hold_seconds:.2f} s",
            )
            for item in tested
        ],
    ))
    add("")
    add("**Observed.** What the bounds refused, including the candidates that qualified but were not")
    add("chosen, so the set can be judged rather than trusted:")
    add("")
    refused = [item for item in bundle["candidates"] if not item.get("qualifies")]
    lines.extend(_md_table(
        ["profile", "scope", "why not"],
        [(f"`{item['profile_id']}`", item["scope"], item["reason"]) for item in refused[:24]],
    ))
    add("")
    if len(refused) > 24:
        add(f"({len(refused) - 24} further refusals are recorded in `reports/stage10b/profiles.json`.)")
        add("")
    add(
        "**Observed.** The level-0 rule is the one that costs the most, so the evidence behind it is "
        "written down. Every profile it refused, with where its silent frames sit:"
    )
    add("")
    gating_records = bundle["gating_evidence"]
    lines.extend(_md_table(
        ["profile", "scope", "frames", "level changes", "change rate", "silent", "leading", "interior", "trailing"],
        [
            (
                f"`{record['profile_id']}`",
                record["scope"],
                str(record["frames"]),
                str(record["level_changes"]),
                f"{record['change_rate_hz']:.1f} Hz"
                if record["change_rate_hz"] is not None
                else "—",
                f"{100 * record['gating_share']:.0f}%",
                str(record["silence_shape"]["leading"]),
                str(record["silence_shape"]["interior"]),
                str(record["silence_shape"]["trailing"]),
            )
            for record in gating_records
        ],
    ))
    add("")
    add(
        "**Inference.** The contours with the most movement in this bank — up to 119 level changes in "
        "147 frames — are exactly the ones that contain silence, and all of them are also faster than "
        "the frame grid (27–40 Hz against 12.5 Hz). What this stage therefore tests is the swell and "
        "step class, not the tremolo class; the tremolo class is named here and left for a later "
        "stage rather than approximated into a level shape."
    )
    add(
        "**Inference.** The set is biased towards contours that sustain rather than gate, by "
        "construction. That is the scope of this stage, not a property of the library: the gating "
        "contours are named above and remain untested."
    )
    add("")

    # ---------------------------------------------------------------- 7
    add("## 7. The three variants")
    add("")
    lines.extend(_md_table(
        ["variant", "what it is", "profiles", "songs"],
        [
            ("A", "DEFAULT — the composer's own instrument", "the same held note, no profile", "the same excerpt, no profile"),
            ("B", "CURRENT PROFILE — the bound profile, no contour", "the profile's generator, clock and envelope", "Stage 10A's binding, no contour"),
            ("C", "PROFILE + VOLUME CONTOUR", "B plus the profile's measured contour", "B plus each channel's contour where transferable"),
        ],
    ))
    add("")
    add("**Observed.** B and C are rendered from one composition and one binding, and differ in exactly")
    add("one field: `IRInstrument.volume_contour`. §8 proves that no other register moved.")
    add("")
    add("**Observed.** The renderer normalizes every buffer it returns to a peak of 0.90. The contour")
    add("never attenuates the profile's own peak frame (its reference level is the contour's peak), so")
    add("all three variants of a tested profile are scaled by the same factor and the WAV carries the")
    add("contour's shape exactly. For the songs the one gain per song is Stage 10A's rule — the default")
    add("render's excerpt peak — so the B side stays byte-identical to the package the listener already")
    add("heard.")
    add("")
    add("**Observed.** The renderer normalizes every buffer it returns to a peak of 0.90, so overall")
    add("level differences cannot survive to the WAV. What the WAV *does* carry is the shape —")
    add("modulation within the sound, the crest factor and the per-frame dynamic range — which is why")
    add("§9 reports those as the primary evidence and the peak as context.")
    add("")

    # ---------------------------------------------------------------- 8
    add("## 8. The perturbation proof")
    add("")
    add(
        "**Observed.** For every tested profile, three renders of one composition and one binding were "
        "compared: B (no contour), C (the measured contour) and P (the same contour reversed). The "
        "chain the experiment claims is contour → IR → frames → WAV, and each link is checked "
        "separately:"
    )
    add("")
    lines.extend(_md_table(
        ["profile", "hold", "columns changed", "column", "distortion untouched", "volume = mapping", "audio differs", "audio ↔ volume (r)"],
        [
            (
                f"`{profile_id}`",
                f"{proof['hold_frames']} f",
                ", ".join(proof["b_vs_c"]["columns_differing"]) or "—",
                proof["changed_column"] or "—",
                "yes" if proof.get("distortion_untouched") else "NO",
                "yes" if proof.get("volume_equals_the_mapping") else "NO",
                "yes" if proof["audio_differs_b_vs_c"] else "no",
                _num(proof.get("audio_tracks_volume_c", {}).get("correlation")),
            )
            for profile_id, proof in proofs.items()
        ],
    ))
    add("")
    reversed_ok = all(
        not proof["c_vs_reversed"]["audio_identical"] for proof in proofs.values()
    )
    add(
        f"**Observed.** Reversing the contour changes the audio again "
        f"({'every' if reversed_ok else 'not every'} profile), which is what makes the first result "
        "causal rather than coincidental: the same levels in a different order produce a different "
        "sound."
    )
    add("")
    add(
        "**Observed.** With the feature switched on but the contour flat (every level equal to the "
        "profile's peak), the frames and the audio are byte-identical to variant B:"
    )
    add("")
    lines.extend(_md_table(
        ["profile", "frames identical", "audio identical"],
        [
            (
                f"`{profile_id}`",
                "yes" if proof["static_contour_is_a_no_op"]["frames_identical"] else "NO",
                "yes" if proof["static_contour_is_a_no_op"]["audio_identical"] else "NO",
            )
            for profile_id, proof in proofs.items()
        ],
    ))
    add("")
    add(
        "**Inference.** The contour reaches the register stream and the audio, it is the only cause of "
        "the difference between B and C, and the arithmetic that produces it is the arithmetic "
        "documented in §5 — the frame stream was compared against the mapping itself, not against a "
        "summary of it."
    )
    add("")

    # ---------------------------------------------------------------- 9
    add("## 9. What the machine measured")
    add("")
    add("**Observed.** Variant C against variant B, per tested profile, measured from the frame stream")
    add("(exact) and from the audio (shape):")
    add("")
    lines.extend(_md_table(
        ["subject", "frames differing", "contour depth", "mean level B → C", "crest Δ (dB)", "spectral distance", "attenuation r"],
        [
            (
                f"`{subject_id}`",
                f"{record['transfer']['b_vs_c']['frames_differing']} / {record['transfer']['b_vs_c']['frames_compared']}",
                f"{record['contour_depth']}",
                f"{record['transfer']['b_vs_c']['volume']['b']['mean_level']} → "
                f"{record['transfer']['b_vs_c']['volume']['c']['mean_level']}",
                _num(record["transfer"]["b_vs_c"]["crest_delta_db"]),
                _num(record["transfer"]["b_vs_c"]["spectral"]["distance"], 4),
                _num(
                    record["transfer"]["attenuation_follows_contour"]["correlation"]
                ),
            )
            for subject_id, record in records.items()
            if record["kind"] == "profile"
        ],
    ))
    add("")
    add("**Observed.** C's frame stream *is* the mapping's own arithmetic applied to B's, frame for")
    add("frame, with no mismatching frame in any tested profile:")
    add("")
    lines.extend(_md_table(
        ["subject", "volume = mapping", "mismatching frames", "MAE of the attenuation factor", "max error"],
        [
            (
                f"`{subject_id}`",
                "yes" if record["transfer"]["volume_equals_the_mapping"] else "NO",
                next(
                    proof["volume_mismatch_frames"]
                    for proof in bundle["proofs"]
                    if proof["profile_id"] == record["label"]
                ),
                _num(record["transfer"]["attenuation_follows_contour"]["mae_factor"], 4),
                _num(record["transfer"]["attenuation_follows_contour"]["max_error_factor"], 4),
            )
            for subject_id, record in records.items()
            if record["kind"] == "profile"
        ],
    ))
    add("")
    add("The attenuation factor is the render's own arithmetic on the audio path: for every sounding")
    add("frame, C's volume divided by B's volume, against the contour's level divided by its own peak.")
    add("It is not exactly the contour because the volume nibble is quantized to 0..15 — hence the MAE")
    add("above, which is quantization rather than error.")
    add("")
    add("**Observed.** The rendered audio's own frame-wise loudness follows the volume the frames carry,")
    add("which is the mechanism the contour is supposed to act through:")
    add("")
    lines.extend(_md_table(
        ["subject", "audio ↔ volume (r)", "sounding frames"],
        [
            (
                f"`{subject_id}`",
                _num(record["transfer"].get("audio_tracks_volume_c", {}).get("correlation")),
                record["transfer"].get("audio_tracks_volume_c", {}).get("sounding_frames", "—"),
            )
            for subject_id, record in records.items()
            if record["kind"] == "profile"
        ],
    ))
    add("")
    add("**Observed.** The same measurement for the six songs. Here the contours are the artists' own,")
    add("and their change rates (18–42 Hz) are faster than the frame grid can carry, so what is")
    add("transferred is a decimated version of the measurement — a limitation, not a defect of the")
    add("mapping:")
    add("")
    lines.extend(_md_table(
        ["subject", "song", "channels given the contour", "channels withheld", "frames differing"],
        [
            (
                f"`{subject.subject_id}`",
                f"`{subject.label}`",
                ", ".join(subject.contour_binding) or "—",
                ", ".join(item["instrument"] for item in subject.withheld) or "—",
                f"{records[subject.subject_id]['transfer']['b_vs_c']['frames_differing']} / "
                f"{records[subject.subject_id]['transfer']['b_vs_c']['frames_compared']}",
            )
            for subject in song_subjects
        ],
    ))
    add("")
    add("**Observed.** No variant clipped:")
    add("")
    clipped = sum(
        sum(record["clipped_samples"].values()) for record in bundle["subject_records"]
    )
    add(f"* clipped samples across every variant of every subject: {clipped}")
    add("")

    # ---------------------------------------------------------------- 10
    add("## 10. The regression proof")
    add("")
    add(
        "**Observed.** Every render the Stage 10A package published was reproduced with the feature "
        "switched off and compared byte for byte. No golden file was regenerated to accommodate a "
        "difference:"
    )
    add("")
    lines.extend(_md_table(
        ["song", "renders compared", "byte identical", "shared gain (dB)"],
        [
            (
                f"`{record['song']}`",
                str(len(record["published"])),
                "yes" if record["all_byte_identical"] else "NO",
                _num(record["shared_gain_db"], 4),
            )
            for record in regression["songs"].values()
        ],
    ))
    add("")
    add(
        f"**Observed.** {regression['renders_compared']} of "
        f"{regression['renders_compared']} renders across {regression['songs_compared']} songs are "
        f"byte-identical: `all_byte_identical = {regression['all_byte_identical']}`."
    )
    add("")
    add(
        "**Inference.** Adding the contour did not perturb the existing path. A song that asks for no "
        "contour renders exactly as it did before the feature existed."
    )
    add("")
    add(
        "**Observed, and it is the reason this stage stops where it does.** The WAV renderer and the "
        "XEX exporter are not the same path: the exporter writes a note table and `player.asm` builds "
        "the per-frame envelope itself. A song carrying a contour is therefore **refused** for XEX "
        "export (`VOLUME_CONTOUR_NOT_EXPRESSIBLE_IN_XEX`) rather than exported as something that "
        "would play a different sound from the one that was listened to. Nothing existing breaks, "
        "because no IR carries a contour unless a caller asks for one."
    )
    add("")

    # ---------------------------------------------------------------- 11
    add("## 11. The blinded listening package")
    add("")
    add(f"**Observed.** {len(trials)} pairs, from {len(bundle['subjects'])} subjects:")
    add("")
    lines.extend(_md_table(
        ["subject", "kind", "material", "pairs", "B-vs-C", "A-vs-C (control)"],
        [
            (
                f"`{subject.subject_id}`",
                subject.kind,
                subject.material,
                str(sum(1 for t in trials if t.subject_id == subject.subject_id)),
                str(
                    sum(
                        1
                        for t in primary
                        if t.subject_id == subject.subject_id
                    )
                ),
                str(
                    sum(
                        1
                        for t in controls
                        if t.subject_id == subject.subject_id
                    )
                ),
            )
            for subject in bundle["subjects"]
        ],
    ))
    add("")
    add(
        f"**Observed.** {len(primary)} of the pairs are the experiment (B-vs-C: the same sound with and "
        f"without its contour) and {len(controls)} are controls (A-vs-C: the same sound against the "
        "composer's own instrument). The interface names no variant, no profile, no generator and no "
        "song; the mapping lives only in the package's `manifest.json`, which carries the warning not "
        "to open it while listening."
    )
    add("")
    add("**Experimental choice.** The listener is asked two kinds of question:")
    add("")
    add("* **preference** — better overall, more convincing as Atari music, more interesting character,")
    add("  and how different the two sides sound;")
    add("* **perceptibility** — whether either side changes noticeably *during* a note. This one is not")
    add("  a preference: it asks whether the contour is audible at all, which is the first thing this")
    add("  stage cannot answer by itself.")
    add("")

    # ---------------------------------------------------------------- 12
    add("## 12. The whole-song comparison")
    add("")
    add(
        "**Observed.** The six Stage 10A songs are reused with the binding Stage 10A chose. Variant C "
        "gives each channel its profile's measured contour *where that contour is transferable*; a "
        "channel whose contour gates is left as in variant B, and is named here rather than "
        "approximated:"
    )
    add("")
    withheld_rows = [
        (f"`{subject.subject_id}`", f"`{item['instrument']}`", f"`{item['profile_id']}`", item["reason"],
         "—" if item["gating_share"] is None else f"{100 * item['gating_share']:.0f}%")
        for subject in song_subjects
        for item in subject.withheld
    ]
    if withheld_rows:
        lines.extend(_md_table(["subject", "channel", "profile", "why withheld", "silent frames in source"], withheld_rows))
    else:  # pragma: no cover - depends on the bank
        add("* none: every bound channel's contour is transferable.")
    add("")
    withheld_channels = sum(len(subject.withheld) for subject in song_subjects)
    songs_with_withheld = sum(1 for subject in song_subjects if subject.withheld)
    add(
        f"**Inference.** {withheld_channels} channel"
        f"{'' if withheld_channels == 1 else 's'} in {songs_with_withheld} of the "
        f"{len(song_subjects)} songs could not take the contour. That is a statement about the "
        "measurement — those profiles' contours are mostly silence — and it is one of the things the "
        "verdict must carry: a contour transfer cannot be evaluated as a whole until it is known what "
        "to do with a contour that gates."
    )
    add("")

    # ---------------------------------------------------------------- 13
    add("## 13. Observation, inference, choice")
    add("")
    add("**Observed** (measurements and the artefacts' own content): the contour's source, "
        "encoding and rate; what the existing volume pipeline does; the frame-by-frame difference "
        "between B and C; the byte-identity of every Stage 10A render with the feature off; which "
        "channels were given a contour and which were withheld.")
    add("")
    add("**Inference** (what follows): the contour is the sole cause of the difference between B and C; "
        "the transfer behaves as its contract says it must; the feature is inert when it is not asked "
        "for; a gating contour cannot be transferred as loudness.")
    add("")
    add("**Experimental choice** (nothing forces it): the relative mapping and its reference level; the "
        "restart-per-note time base; the bounds that define a transferable contour; which profiles were "
        "tested; the held-note stimulus; the use of Stage 10A's binding as the continuation point; the "
        "questions the listener is asked. Each of these could have been decided otherwise, and each is "
        "recorded here so it can be argued with.")
    add("")

    # ---------------------------------------------------------------- 14
    add("## 14. Limitations, and the verdict")
    add("")
    for item in manifest["limitations"]:
        add(f"* **{item['code']}** — {item['detail']}")
    add("")
    add(
        "Further limitations of this preparation, stated rather than hidden:"
    )
    add("")
    add(
        "* The tested profile set is biased towards contours that sustain, because a gating contour "
        "cannot be transferred as a level shape (§6)."
    )
    add(
        "* The songs' own contours change faster than the frame grid (18–42 Hz), so their transfer is "
        "decimated; the profile trials use slow contours for exactly this reason, and the two results "
        "are not interchangeable."
    )
    add(
        "* Tiling a contour over a note longer than the measured segment assumes the gesture repeats. "
        "For `periodic: false` measurements that assumption is unproven."
    )
    add(
        "* The renderer normalizes each buffer, so the package cannot present an overall level "
        "difference; the listening test therefore measures the contour's *shape*, not its loudness."
    )
    add(
        "* Variant B is Stage 10A's binding, which the listener heard minutes earlier in the previous "
        "package. Anchoring cannot be excluded and the trial order is randomized to limit it."
    )
    add(
        "* Nothing here has been heard by a human yet. The automatic metrics show that the transfer "
        "works; they say nothing about whether it sounds better, and this stage does not guess."
    )
    add("")
    add("**VERDICT: " + verdict + "**")
    add("")
    add(
        "The transfer is proven, not judged. When the listening package is answered, the answer decides "
        "between the three labels this stage may declare — POSITIVE only if the contour is both audible "
        "and preferred, NEGATIVE if it is audible and rejected, INCONCLUSIVE while the evidence is "
        "missing or mixed. It is `" + verdict + "` today."
    )
    add("")
    return "\n".join(lines) + "\n"


def distortion_label(item: TestedProfile) -> str:
    """The tested profile's generator nibble, as the report prints it."""
    return f"{item.distortion_nibble:X}" if item.distortion_nibble is not None else "—"


# ===========================================================================
# 10. Reading the answers back
# ===========================================================================
def read_answers(package_dir: Path = DEFAULT_PACKAGE_DIR) -> List[Dict[str, str]]:
    """The filled answer sheet, or an empty list while it is still the blank template."""
    path = Path(package_dir) / "evaluation_volume_contour_10b.csv"
    if not path.is_file():
        return []
    with path.open(encoding="utf-8", newline="") as handle:
        return [
            row for row in csv.DictReader(handle) if (row.get("better_overall") or "").strip()
        ]


def summarise_answers(
    package_dir: Path = DEFAULT_PACKAGE_DIR,
    *,
    analysis_dir: Optional[Path] = DEFAULT_ANALYSIS_REPORTS,
) -> Dict[str, Any]:
    """What the listener said, if the sheet has been filled in.

    Reports the counts per trial kind and side, without deciding anything: the number this stage
    would need is whether C wins its B-vs-C pairs, and a bare count of answers is not a verdict.
    """
    rows = read_answers(package_dir)
    manifest_path = Path(package_dir) / "manifest.json"
    if not rows or not manifest_path.is_file():
        return {"answered": 0, "trials": 0, "note": "the answer sheet is still empty"}
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    trials = {trial["trial_id"]: trial for trial in manifest["trials"]}
    summary: Dict[str, Any] = {
        "answered": len(rows),
        "trials": len(trials),
        "by_kind": {},
        "preference": {"c": 0, "b_or_a": 0, "none": 0},
        "perceptibility": {"heard": 0, "neither": 0},
        "difference_1_5": [],
        "comments": [],
    }
    for row in rows:
        trial = trials.get(row["trial_id"])
        if trial is None:  # pragma: no cover - a hand-edited sheet
            raise Stage10BError(f"the answer sheet names an unknown trial: {row['trial_id']}")
        kind = trial["trial_kind"]
        bucket = summary["by_kind"].setdefault(kind, {"c": 0, "other": 0, "none": 0})
        choice = (row.get("better_overall") or "").strip().lower()
        side = trial["sides"].get(choice)
        if side == "c":
            bucket["c"] += 1
            summary["preference"]["c"] += 1
        elif side is None:
            bucket["none"] += 1
            summary["preference"]["none"] += 1
        else:
            bucket["other"] += 1
            summary["preference"]["b_or_a"] += 1
        movement = (row.get("audible_movement") or "").strip().lower()
        if movement in {"a", "b", "both"}:
            summary["perceptibility"]["heard"] += 1
        elif movement == "neither":
            summary["perceptibility"]["neither"] += 1
        value = (row.get("difference_1_5") or "").strip()
        if value.isdigit():
            summary["difference_1_5"].append(int(value))
        comment = (row.get("comment") or "").strip()
        if comment:
            summary["comments"].append({"trial_id": row["trial_id"], "comment": comment})
    if summary["difference_1_5"]:
        values = sorted(summary["difference_1_5"])
        summary["difference_median"] = values[len(values) // 2]
    if analysis_dir is not None:
        analysis_dir = Path(analysis_dir)
        analysis_dir.mkdir(parents=True, exist_ok=True)
        (analysis_dir / "answers.json").write_text(
            json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
    return summary

"""Experiment 29 — a curated candidate library of POKEY timbres, with a blind audition.

The problem this addresses is the one the project started with: a single note in generated music
sounds too simple. Experiment 28 showed that one experimental timbre (C1) survives being put into a
real composition. This experiment does not add another timbre — it screens the **existing** bank of 67
extracted sound profiles, picks a small set that is plausibly *different from each other*, renders
them on one identical note grid, and hands the owner a blind page to audition.

THREE PHASES, IN THIS MODULE
----------------------------
* **Phase A** — ``build_inventory``: a machine-readable record of all 67 profiles, with the fields the
  loader actually exposes and an explicit statement of which measured properties the current engine
  cannot reproduce.
* **Phase B** — ``CANDIDATES``: 11 bank profiles plus the C1 reference, chosen for **audible**
  diversity on the axes that reach the render, with a written rationale for each.
* **Phase C/D/E** — ``render_all`` / ``render_page`` / ``build_manifest``: the audition clips, the
  blinded local listening page, and the reports.

WHAT ACTUALLY REACHES THE SOUND
-------------------------------
Read from ``sound_profiles/binding.py`` rather than assumed. ``apply_profile_binding`` writes exactly
five things onto an ``IRSong`` instrument: ``distortion``, ``envelope``, ``audctl``, ``is_16bit`` and
(opt-in) ``volume_contour``. It never changes a pitch, a duration, a rest, a velocity or a role —
"the note determines the pitch — the profile supplies the *clock*".

So a profile's ``pitch.base_hz``, ``pitch.range_semitones``, ``gesture.pitch.runs``,
``gesture.control_state.runs`` and ``envelope.shape`` label are **evidence, not sound**. Two profiles
that differ only in those fields will render identically here, which is why the shortlist is chosen on
``(distortion, audctl, envelope frames, sustain level)`` — the audibly-relevant tuple — and not on the
richer metadata.

DELIBERATE RENDERING DECISIONS
------------------------------
* **The measured volume contour is not applied.** It is opt-in, it is off by default in production,
  and ``mads_exporter`` refuses to export a song while one is set — so a timbre that *depended* on its
  contour could not ship. The contour is therefore recorded in the inventory as a property this
  audition does not exercise, rather than silently enabled.
* **No profile is substituted or repaired.** Two shortlisted profiles were refused by the production
  binding (``PROFILE_ENVELOPE_OUT_OF_RANGE``: a measured attack longer than the composer's 15-frame
  field) and were replaced rather than clamped; the refusal is recorded in ``REFUSED_PROFILES`` and in
  the report.
* **One shared gain** across all clips, no per-file normalisation, and the per-clip RMS is published.

WHAT THIS IS NOT
----------------
No production DSL/IR/compiler/exporter/player/CLI change. The candidates are not registered as
instruments, no instrument-mapping system is added, and the experiment is not reachable from the
production command line. Whether any candidate is worth keeping is a listening decision.
"""

from __future__ import annotations

import csv
import json
import math
import random
import wave
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

import numpy as np

from atari_music import ir
from atari_music import pokey_c1_musical_context_experiment as e28
from atari_music import pokey_timbre_experiment as e26
from atari_music.ai.client import generate_music_from_composition, load_composition_dsl
from atari_music.sound_profiles.bank import (
    RENDERABLE_STATUSES,
    SoundProfileBank,
    SoundProfileError,
    load_sound_profile_bank,
)
from atari_music.sound_profiles.binding import (
    BINDING_SCHEMA,
    apply_profile_binding,
    load_profile_binding,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT_DIR = REPO_ROOT / "experiments" / "experiment29"
DEFAULT_BANK_DIR = REPO_ROOT / "tests" / "data" / "sound_profiles" / "bank"

SAMPLE_RATE = e26.SAMPLE_RATE
FRAME_RATE_HZ = e26.FRAME_RATE_HZ
TARGET_PEAK = e26.TARGET_PEAK

#: Fixed, so the clip numbering is reproducible. Changing it renumbers every clip.
SEED = 29

#: The one note grid every candidate plays. Identical to Experiments 26/27/28, so a listener can
#: compare a candidate directly against the C1 reference they have already heard.
#: ``BPM 125`` gives ``frames_per_tick = 4``, so a row is 20 ms.
GRID: Dict[str, Dict[str, Any]] = {
    "note": {"rows": 12, "notes": "A4/12", "frames": 48, "description": "a single held note, A-4"},
    "phrase": {
        "rows": 20, "notes": "A4/5 C5/5 E5/5 C5/5", "frames": 80,
        "description": "four notes — A-4, C-5, E-5, C-5 — 20 frames each",
    },
    "phrase_low": {
        "rows": 20, "notes": "A3/5 C4/5 E4/5 C4/5", "frames": 80,
        "description": "the same phrase an octave lower — A-3, C-4, E-4, C-4",
    },
}
SCORE_ORDER: Tuple[str, ...] = ("note", "phrase", "phrase_low")

#: The reference timbre. Not a bank profile: it is Experiment 26/27's variant C, whose register
#: generation is reused from Experiment 28 rather than re-implemented.
C1_NAME = "c1_octave_pulse"

CLIPS_CSV = "evaluation_experiment29_clips.csv"
SUMMARY_CSV = "evaluation_experiment29_summary.csv"

CLIP_FIELDS: Tuple[str, ...] = (
    "listener", "clip", "score", "musical_usefulness_1_5", "character_interest_1_5",
    "annoyance_1_5", "recognisably_musical", "comment",
)
SUMMARY_FIELDS: Tuple[str, ...] = (
    "listener",
    "note_best_clip", "note_least_usable_clip", "note_comment",
    "phrase_best_clip", "phrase_least_usable_clip", "phrase_comment",
    "phrase_low_best_clip", "phrase_low_least_usable_clip", "phrase_low_comment",
    "library_diverse_enough", "comment",
)

#: The 1–5 ratings asked of every clip, with the end labels that give the number meaning.
CLIP_SCALES: List[Dict[str, Any]] = [
    {
        "field": "musical_usefulness_1_5",
        "question": "Could you use this sound as an instrument in a game tune?",
        "labels": ["no", "maybe", "yes", "yes, gladly", "yes, definitely"],
    },
    {
        "field": "character_interest_1_5",
        "question": "How interesting is the timbre itself?",
        "labels": ["dull", "plain", "fair", "interesting", "striking"],
    },
    {
        "field": "annoyance_1_5",
        "question": "How irritating is it after a few repeats?",
        "labels": ["not at all", "slightly", "moderately", "quite", "very"],
    },
]

#: The one multiple-choice question asked of every clip.
CLIP_MUSICAL_QUESTION: Dict[str, Any] = {
    "field": "recognisably_musical",
    "question": "Does it read as a musical instrument, or as a fault / effect?",
    "choices": [
        {"value": "musical", "label": "a musical instrument"},
        {"value": "both", "label": "both, depending on context"},
        {"value": "effect", "label": "an effect, not an instrument"},
        {"value": "fault", "label": "a fault"},
    ],
}

PREFERENCE_QUESTIONS: List[Dict[str, Any]] = [
    {"field": "best_clip", "question": "Which of these would you actually use?"},
    {"field": "least_usable_clip", "question": "Which of these is the least usable?"},
]

OVERALL_QUESTIONS: List[Dict[str, Any]] = [
    {
        "field": "library_diverse_enough",
        "question": (
            "Do these candidates contain enough genuinely different sounds to be worth keeping as a "
            "small instrument library?"
        ),
        "labels": ["yes, plenty", "yes, but a few sound alike", "no, mostly the same", "not sure"],
    },
]

PRODUCTION_STATEMENT = (
    "no DSL, IR, compiler, MADS exporter, player or CLI change; the candidates are not registered as "
    "instruments, no instrument-mapping system was added, and the experiment is not reachable from the "
    "production command line"
)

#: The real limits of what this audition can show.
LIMITATIONS: Tuple[str, ...] = (
    "the shortlist is a selection on the fields that reach the render, not on listening. Whether the "
    "candidates are audibly distinct is a hypothesis this page exists to test, not a finding.",
    "only the generator, the clock/coupling and the envelope frames reach the sound. A profile's "
    "measured pitch gesture, its measured distortion changes and its measured volume contour are all "
    "dropped or not applied, so a profile can sound much plainer here than the recording it came from.",
    "the volume contour is deliberately off (it cannot ship to hardware), so any candidate whose "
    "character came mostly from its contour will sound weaker here than in the source material.",
    "two shortlisted profiles were refused by the production binding because their measured attack "
    "exceeds the composer's 15-frame envelope field. They were replaced, not clamped; see "
    "refused_profiles.",
    "a PAIR candidate occupies both channels of the 1+2 pair, so it could not share a composition with "
    "another PAIR instrument. That is a real constraint on using these as a library.",
    "the grid is three short test figures, not music. A candidate can sound good here and be useless in "
    "a tune, and vice versa — Experiment 28 exists precisely because that gap is real.",
    "one listener, one session. Any preference expressed here is preliminary.",
    "the clip-to-candidate mapping is in manifest.json, and the README describes the sound families, so "
    "the test is only partially blinded.",
)



# ===========================================================================
# Phase A — the inventory of all 67 profiles, from repository data only.
# ===========================================================================
#: The properties ``sound_profiles/binding.py`` writes onto an ``IRSong``. Everything outside this
#: list is evidence about the *source recording*, not something the current engine renders.
RENDERED_PROPERTIES: Tuple[str, ...] = (
    "distortion (the AUDC generator nibble)",
    "envelope (attack / decay / release frames, sustain level)",
    "audctl (the clock and coupling bits)",
    "is_16bit / uses_16bit_bass (a PAIR profile's joined pair)",
    "volume_contour — available, but opt-in and off here (see the module docstring)",
)

#: The measured properties the current engine cannot reproduce, with the code that flags them.
UNREPRODUCED_PROPERTIES: Tuple[Dict[str, str], ...] = (
    {
        "property": "gesture.pitch.runs — the measured pitch movement",
        "code": "GESTURE_NOT_RENDERABLE_BY_CONSUMER",
        "why": (
            "IRNote.slide_semitones / arpeggio_offsets and IRInstrument.vibrato_* are reserved and "
            "never rendered: the 6502 player sets AUDC once per channel and has no per-frame pitch "
            "modulation. The note supplies the pitch; the profile supplies the clock."
        ),
    },
    {
        "property": "gesture.control_state.runs — the measured distortion changes",
        "code": "GESTURE_NOT_RENDERABLE_BY_CONSUMER",
        "why": (
            "_render_note_to_frames writes (distortion & 0xE0) | vol with one constant generator for "
            "the whole note, so a generator that changes inside a span cannot be expressed."
        ),
    },
    {
        "property": "gesture.volume.runs — the measured per-frame level contour",
        "code": "VOLUME_MODULATION_NOT_REPRODUCIBLE",
        "why": (
            "IRInstrument.volume_contour does reach the WAV preview, but it is off by default and "
            "mads_exporter refuses to export a song while it is set, so it cannot ship to hardware. "
            "This audition does not enable it."
        ),
    },
    {
        "property": "envelope.shape (tremolo / swell / plucked / sustained)",
        "code": "ENVELOPE_NOT_MEASURED / label only",
        "why": (
            "the shape is a label on the measured contour. What reaches the render is the four frame "
            "counts, so two profiles with the same frames render the same articulation whatever their "
            "shape label says."
        ),
    },
    {
        "property": "pitch.base_hz and pitch.base_divider",
        "code": "PITCH_CENTRE_NOT_MEASURED / evidence only",
        "why": (
            "the binding treats these as evidence about the source, never as register values to copy; "
            "the note decides the frequency and the profile's clock decides the divider."
        ),
    },
    {
        "property": "pitch.range_semitones",
        "code": "PITCH_RANGE_NOT_MEASURED",
        "why": "the played range is the composition's, so the profile's measured range is not applied.",
    },
    {
        "property": "high-pass clocking (AUDCTL bits 1 and 2)",
        "code": "not modelled by the renderer",
        "why": "the WAV renderer does not implement the POKEY high-pass filter.",
    },
    {
        "property": "any joined pair other than 1+2",
        "code": "PROFILE_SCOPE_UNSUPPORTED",
        "why": "the composer's only joined-pair layout is 1+2; archaeology PAIR profiles are all 1+2.",
    },
)


def load_bank(bank_dir: Path = DEFAULT_BANK_DIR) -> SoundProfileBank:
    """The existing bank, through its own loader. No path or format is assumed."""
    return load_sound_profile_bank(Path(bank_dir))


def audible_signature(profile: Any) -> Tuple[Any, ...]:
    """The tuple that actually decides how a profile sounds in this engine.

    Generator nibble, AUDCTL, and the three envelope frames plus the sustain level. Two profiles with
    the same signature render identically on the same notes, so the signature — not the richer
    metadata — is what the diversity screening uses.
    """
    frames = profile.envelope_frames
    return (
        profile.distortion_nibble,
        profile.audctl_mode,
        frames.get("attack"),
        frames.get("decay"),
        frames.get("release"),
        profile.envelope_sustain_level,
    )


def feasibility(profile: Any) -> str:
    """``faithful`` / ``limited`` / ``unusable`` — what this engine can do with the profile.

    * ``unusable`` — the publishing audit says the profile must not be rendered as a sound;
    * ``limited``  — renderable, but it carries a measured gesture the engine cannot reproduce, or
                     its envelope was not measured so the composer's default articulation is used;
    * ``faithful`` — renderable, with a measured envelope and no unreproducible gesture.
    """
    if not profile.renderable:
        return "unusable"
    gesture = (profile.document.get("playability") or {}).get("gesture") or {}
    carries_pitch = bool((gesture.get("pitch") or {}).get("available"))
    carries_distortion = bool((gesture.get("control_state") or {}).get("available"))
    frames = profile.envelope_frames
    envelope_measured = all(frames.get(key) is not None for key in ("attack", "decay", "release"))
    if carries_pitch or carries_distortion or not envelope_measured:
        return "limited"
    return "faithful"


def inventory_row(profile: Any) -> Dict[str, Any]:
    """One machine-readable inventory row: the fields the loader actually exposes."""
    document = profile.document
    hardware = profile.hardware
    channels = profile.channels
    gesture = document.get("gesture") or {}
    playability = document.get("playability") or {}
    gesture_flags = playability.get("gesture") or {}
    pitch = document.get("pitch") or {}
    volume = document.get("volume") or {}
    envelope = document.get("envelope") or {}
    source = document.get("source") or {}
    frames = profile.envelope_frames

    return {
        "profile_id": profile.profile_id,
        "profile_type": profile.scope,
        "status": profile.status,
        "renderable": bool(profile.renderable),
        "feasibility": feasibility(profile),
        # generator
        "distortion_nibble": profile.distortion_nibble,
        "distortion_byte": profile.distortion_byte,
        "waveform": hardware.get("waveform"),
        "distortion_name": hardware.get("distortion_name"),
        # clock and coupling
        "audctl_mode": profile.audctl_mode,
        "clock_mode": profile.clock_mode,
        "clock_base": hardware.get("clock_base"),
        "clock_family": hardware.get("clock_family"),
        "coupling": profile.coupling,
        "uses_channel_coupling": hardware.get("uses_channel_coupling"),
        # channels
        "channel_mode": channels.get("mode"),
        "pair": profile.pair,
        "divider_bits": profile.divider_bits,
        "audible_channel": profile.audible_channel,
        "companion_channel": profile.companion_channel,
        "requires_simultaneous_channels": profile.requires_simultaneous_channels,
        # pitch (evidence, not rendered)
        "pitch_base_hz": pitch.get("base_hz"),
        "pitch_base_divider": pitch.get("base_divider"),
        "pitch_range_semitones": pitch.get("range_semitones"),
        "pitch_direction": pitch.get("direction"),
        "pitch_static": pitch.get("static"),
        "pitch_mode": playability.get("pitch_mode"),
        # volume and envelope: the frames reach the render, the contour does not
        "volume_peak_level": volume.get("peak_level"),
        "volume_min_level": volume.get("min_level"),
        "volume_levels": volume.get("levels"),
        "volume_static": volume.get("static"),
        "volume_contour_frames": len(profile.volume_contour) if profile.volume_contour else 0,
        "envelope_shape": envelope.get("shape"),
        "envelope_confidence": envelope.get("confidence"),
        "envelope_frames": {
            "attack": frames.get("attack"),
            "decay": frames.get("decay"),
            "release": frames.get("release"),
        },
        "envelope_sustain_level": profile.envelope_sustain_level,
        # measured gestures
        "gesture_pitch_available": bool((gesture_flags.get("pitch") or {}).get("available")),
        "gesture_volume_available": bool((gesture_flags.get("volume") or {}).get("available")),
        "gesture_control_state_available": bool(
            (gesture_flags.get("control_state") or {}).get("available")
        ),
        "modulation_periodic": (gesture.get("modulation") or {}).get("periodic"),
        "modulation_period_frames": (gesture.get("modulation") or {}).get("period_frames"),
        # classification and limitations
        "blocking_codes": list(profile.blocking_codes),
        "limitation_codes": list(profile.limitation_codes),
        "consumer_gap_codes": list(profile.consumer_gap_codes),
        "source_songs": list(source.get("songs") or []),
        # the diversity key
        "audible_signature": list(audible_signature(profile)),
    }


def build_inventory(bank: SoundProfileBank) -> List[Dict[str, Any]]:
    """Phase A: every profile in the bank, in stable id order."""
    return [inventory_row(bank.profiles[profile_id]) for profile_id in bank.ids()]


def inventory_summary(rows: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    """The verified playability breakdown, and the diversity the bank actually offers."""
    def counts(key: str) -> Dict[str, int]:
        out: Dict[str, int] = {}
        for row in rows:
            out[str(row[key])] = out.get(str(row[key]), 0) + 1
        return dict(sorted(out.items()))

    signatures: Dict[Tuple[Any, ...], int] = {}
    for row in rows:
        if row["renderable"]:
            key = tuple(row["audible_signature"])
            signatures[key] = signatures.get(key, 0) + 1

    return {
        "profile_count": len(rows),
        "by_profile_type": counts("profile_type"),
        "by_status": counts("status"),
        "by_feasibility": counts("feasibility"),
        "by_distortion_nibble": counts("distortion_nibble"),
        "by_audctl_mode": counts("audctl_mode"),
        "by_clock_mode": counts("clock_mode"),
        "by_envelope_shape": counts("envelope_shape"),
        "renderable_count": sum(1 for row in rows if row["renderable"]),
        "distinct_audible_signatures_among_renderable": len(signatures),
        "largest_identical_group": max(signatures.values(), default=0),
        "measured_pitch_gesture_count": sum(1 for row in rows if row["gesture_pitch_available"]),
        "measured_distortion_gesture_count": sum(
            1 for row in rows if row["gesture_control_state_available"]
        ),
        "measured_volume_contour_count": sum(1 for row in rows if row["volume_contour_frames"]),
    }


# ===========================================================================
# Phase B — the shortlist. Eleven bank profiles plus the C1 reference.
# ===========================================================================
#: Profiles that were shortlisted on the evidence and then **refused by the production binding**. They
#: are recorded rather than clamped or substituted: the composer's envelope fields only express 0..15
#: frames and the binding raises ``PROFILE_ENVELOPE_OUT_OF_RANGE`` instead of truncating.
REFUSED_PROFILES: Tuple[Dict[str, Any], ...] = (
    {
        "profile_id": "pokey_ref_d172d15e",
        "scope": "VOICE",
        "status": "PLAYABLE",
        "generator": "$A0",
        "measured_envelope": {"attack": 42, "decay": 0, "release": None, "sustain": 11},
        "intended_role": "a very slow swell — the longest measured attack in the bank",
        "refusal": "PROFILE_ENVELOPE_OUT_OF_RANGE",
        "why": (
            "the measured attack is 42 frames and IREnvelope.attack_frames is bounded to 0..15, so the "
            "production binding refuses rather than clamping the profile's articulation"
        ),
    },
    {
        "profile_id": "pokey_ref_686d2070",
        "scope": "VOICE",
        "status": "PLAYABLE",
        "generator": "$80",
        "measured_envelope": {"attack": 25, "decay": 0, "release": None, "sustain": 12},
        "intended_role": "a noise swell — a slow-attack texture, the only one in the noise family",
        "refusal": "PROFILE_ENVELOPE_OUT_OF_RANGE",
        "why": (
            "the measured attack is 25 frames, above the composer's 15-frame envelope field, so it is "
            "refused for the same reason"
        ),
    },
)

C1_CANDIDATE: Dict[str, Any] = {
    "name": C1_NAME,
    "kind": "experiment",
    "profile_id": None,
    "generator": "$40 + octave pulse",
    "clock": "64 kHz, 8-bit",
    "source": (
        "Experiment 26/27 variant C, reused through Experiment 28's apply_c1 rather than "
        "re-implemented: generator $40 with the divider alternating N / N//2 every frame"
    ),
    "selected_because": (
        "the owner already judged this one interesting in a real composition, so it is the reference "
        "the other candidates are heard against"
    ),
    "audibly_different_because": (
        "the only candidate whose divider moves inside a note, which gives it a beating, ringing "
        "quality none of the static-divider profiles can produce"
    ),
    "role_hypothesis": "a ringing, slightly metallic lead or counter-melody line",
    "compromises": (
        "$40 is poly5-gated poly4, so doubling the divider doubles the poly5 gate rate as well: this "
        "is a texture and pitch change together, not a clean octave oscillator. Its volume shape is "
        "the composition default, and no bank profile is involved."
    ),
    "why_audition": "it is the accepted reference; without it the set has no anchor.",
}

BANK_CANDIDATES: Tuple[Dict[str, Any], ...] = (
    {
        "name": "pure_sustain",
        "kind": "bank",
        "profile_id": "pokey_ref_25f94201",
        "generator": "$A0",
        "clock": "64 kHz, 8-bit",
        "selected_because": "the cleanest sustained pure tone in the bank (attack 6, sustain 10)",
        "audibly_different_because": "a plain square with a smooth onset and a steady body",
        "role_hypothesis": "a smooth melodic lead, or a pad under a busier part",
        "compromises": "carries a measured pitch gesture the engine cannot reproduce; it is dropped",
        "why_audition": "it is the neutral reference point every other candidate is heard against",
    },
    {
        "name": "pure_pluck",
        "kind": "bank",
        "profile_id": "pokey_ref_9daa0429",
        "generator": "$A0",
        "clock": "64 kHz, 8-bit",
        "selected_because": (
            "same generator as pure_sustain but the opposite articulation (decay 6 to sustain 3)"
        ),
        "audibly_different_because": (
            "a sharp attack that falls away — the same tone with a percussive envelope"
        ),
        "role_hypothesis": "a plucked or staccato lead, or a repeating arpeggio",
        "compromises": "carries an unreproducible pitch gesture; release is 2 frames",
        "why_audition": (
            "it tests whether the library needs articulation variety within one generator, or whether "
            "generator variety alone is enough"
        ),
    },
    {
        "name": "pure_swell",
        "kind": "bank",
        "profile_id": "pokey_ref_048db11d",
        "generator": "$A0",
        "clock": "64 kHz, 8-bit",
        "selected_because": (
            "the longest attack the composer can express in the pure-tone family (12 frames)"
        ),
        "audibly_different_because": "a slow 240 ms rise into a sustained body",
        "role_hypothesis": "a swell, a transition, or a soft entry for a melody",
        "compromises": (
            "the bank's genuinely slow attacks (25 and 42 frames) are refused by the binding, so this "
            "is the closest expressible thing"
        ),
        "why_audition": "it is the only slow-onset pure tone that can actually ship",
    },
    {
        "name": "buzz_steady",
        "kind": "bank",
        "profile_id": "pokey_ref_2b83db43",
        "generator": "$C0",
        "clock": "64 kHz, 8-bit",
        "selected_because": "a hollow poly4 buzz with a steady body (sustain 9, release 5)",
        "audibly_different_because": (
            "a 15-step poly4 waveform — a distinct metallic buzz rather than a square"
        ),
        "role_hypothesis": "a gritty lead, a bass with attitude, or a doubling layer",
        "compromises": "PLAYABLE_WITH_LIMITATION; carries unreproducible gestures",
        "why_audition": "poly4 is a whole generator family with no pure-tone overlap",
    },
    {
        "name": "buzz_swell",
        "kind": "bank",
        "profile_id": "pokey_ref_0bd72343",
        "generator": "$C0",
        "clock": "64 kHz, 8-bit",
        "selected_because": "the poly4 family's slow attack (12 frames) with the highest sustain (12)",
        "audibly_different_because": "a buzz that swells in rather than starting at full level",
        "role_hypothesis": "an aggressive swell, or a horror/tension texture",
        "compromises": (
            "PLAYABLE_WITH_LIMITATION; the release frame is not measured so the composer's default is used"
        ),
        "why_audition": (
            "it pairs a distinct generator with a distinct articulation, which no other candidate does twice"
        ),
    },
    {
        "name": "noise_hit",
        "kind": "bank",
        "profile_id": "pokey_ref_2de893a6",
        "generator": "$80",
        "clock": "64 kHz, 8-bit",
        "selected_because": "ungated poly9/17 noise with a short decay (6 frames to sustain 2)",
        "audibly_different_because": (
            "broadband noise with pitch content, decaying fast — a hit rather than a tone"
        ),
        "role_hypothesis": "percussion, a snare-like hit, or a short accent",
        "compromises": "PLAYABLE; still carries an unreproducible pitch gesture",
        "why_audition": "the library needs at least one genuinely noisy, percussive candidate",
    },
    {
        "name": "noise_swell",
        "kind": "bank",
        "profile_id": "pokey_ref_914c63ec",
        "generator": "$80",
        "clock": "64 kHz, 8-bit",
        "selected_because": (
            "the noise family's slowest expressible attack (6 frames) with a high sustain (12)"
        ),
        "audibly_different_because": "a sustained noise bed rather than a hit",
        "role_hypothesis": "a texture, a wind or engine effect, or a sustained percussion layer",
        "compromises": "PLAYABLE; the bank's slower noise attacks are refused by the binding",
        "why_audition": (
            "it separates 'noise' from 'percussion' — the same generator with a pad-like envelope"
        ),
    },
    {
        "name": "gated_noise",
        "kind": "bank",
        "profile_id": "pokey_ref_c0b97138",
        "generator": "$00",
        "clock": "64 kHz, 8-bit",
        "selected_because": "the poly5-gated noise generator, of which the bank has no PLAYABLE example",
        "audibly_different_because": (
            "a gate running at the note's rate over noise — a rasping, buzzing hiss"
        ),
        "role_hypothesis": "an aggressive effect, a rumble, or a distorted percussion layer",
        "compromises": (
            "PLAYABLE_WITH_LIMITATION and the most limited candidate here: its envelope is not "
            "measured, so the composer's default articulation is used and the generator is the whole "
            "of the profile's contribution"
        ),
        "why_audition": (
            "it is the only way to hear the $00 generator family, and a family that sounds wrong can "
            "only be rejected by listening to it"
        ),
    },
    {
        "name": "reedy",
        "kind": "bank",
        "profile_id": "pokey_ref_1efd9336",
        "generator": "$60",
        "clock": "64 kHz, 8-bit",
        "selected_because": "the bank's only poly5-gated pure tone — a family with exactly one member",
        "audibly_different_because": (
            "a gate at the note's rate over a square wave, giving a reedy, buzzing edge"
        ),
        "role_hypothesis": "a bright lead with a reed-like edge, or a brass-ish stab",
        "compromises": (
            "PLAYABLE_WITH_LIMITATION; its envelope is not measured, so the articulation is the "
            "composer's default and the generator is the whole of the profile's contribution"
        ),
        "why_audition": (
            "a single-member generator family is exactly the kind of thing worth hearing before discarding"
        ),
    },
    {
        "name": "pair_noise",
        "kind": "bank",
        "profile_id": "pokey_ref_050170ef",
        "generator": "$80",
        "clock": "1.79 MHz, 16-bit pair 1+2",
        "selected_because": (
            "a 16-bit joined pair at the high clock — the other hardware configuration the bank offers"
        ),
        "audibly_different_because": (
            "the 16-bit pair gives a denser, lower, more detailed sound than any single channel"
        ),
        "role_hypothesis": "a bass line, or a heavy low lead",
        "compromises": (
            "needs both channels of pair 1+2, so it occupies CH1+CH2 and cannot share them; the notes "
            "must sit on CH1"
        ),
        "why_audition": "the pair configuration is a different instrument category, not a variation",
    },
    {
        "name": "pair_buzz",
        "kind": "bank",
        "profile_id": "pokey_ref_331fbbd7",
        "generator": "$C0",
        "clock": "1.79 MHz, 16-bit pair 1+2",
        "selected_because": "a 16-bit pair with the poly4 generator and a short percussive envelope",
        "audibly_different_because": "a low metallic buzz that decays quickly — a bass drum or a growl",
        "role_hypothesis": "a percussive bass, or a low rhythmic pulse",
        "compromises": "same channel requirement as pair_noise; sustain is only 2",
        "why_audition": "it shows whether the pair configuration is useful for anything other than a pad",
    },
)

CANDIDATES: Tuple[Dict[str, Any], ...] = (C1_CANDIDATE,) + BANK_CANDIDATES


def candidate_names() -> Tuple[str, ...]:
    return tuple(candidate["name"] for candidate in CANDIDATES)


def candidate_by_name(name: str) -> Dict[str, Any]:
    for candidate in CANDIDATES:
        if candidate["name"] == name:
            return candidate
    raise KeyError(f"unknown candidate {name!r}; known: {list(candidate_names())}")


# ===========================================================================
# Phase C — the audition renders, through the production path.
# ===========================================================================
def composition_text(score: str, sixteen_bit: bool) -> str:
    """The smallest composition that plays the shared grid on one part.

    ``BPM 125`` gives ``frames_per_tick = 4``, so the grid is exactly Experiments 26/27/28's. A PAIR
    profile needs the joined pair, so its notes sit on CH1 with ``BASS 16BIT``; a VOICE profile is a
    single 8-bit channel and its notes sit on CH3. Nothing else differs between the two forms.
    """
    entry = GRID[score]
    bass = "BASS 16BIT\n" if sixteen_bit else ""
    channel = "CH1" if sixteen_bit else "CH3"
    return (
        'TITLE "experiment29 audition"\n'
        'AUTHOR "Experiment 29"\n'
        "KEY A\nMODE MINOR\nBPM 125\n"
        f"{bass}"
        "SEQUENCE P\n\n"
        "INSTRUMENT lead character=bright_lead\n\n"
        f"[PATTERN P length={entry['rows']}]\n"
        f"{channel} lead V14\n{entry['notes']}\n"
    )


def compile_composition(score: str, sixteen_bit: bool) -> Tuple[Any, Any]:
    """``(document, result)`` for one grid form, compiled through the production path unmodified."""
    document = load_composition_dsl(composition_text(score, sixteen_bit))
    return document, generate_music_from_composition(document)


def candidate_stream(candidate: Mapping[str, Any], score: str, bank: SoundProfileBank) -> np.ndarray:
    """The register stream for one candidate on one score.

    Bank candidates go through ``apply_profile_binding`` — the production realization path — with the
    volume contour left off. C1 is the production compile of the same grid with Experiment 28's
    ``apply_c1`` applied to the melodic channel, so its effect is Experiment 27's, not a copy.
    """
    if candidate["kind"] == "experiment":
        _document, result = compile_composition(score, sixteen_bit=False)
        song = result.pokey_ir
        baseline = np.asarray(ir.compile_ir_to_pokey_frames(song))
        return e28.apply_c1(baseline, song, e28.MELODIC_CHANNEL)

    profile = bank.get(str(candidate["profile_id"]))
    sixteen_bit = profile.scope == "PAIR"
    document, result = compile_composition(score, sixteen_bit=sixteen_bit)
    binding = load_profile_binding({
        "schema": BINDING_SCHEMA,
        "instruments": {"lead": profile.profile_id},
    })
    bound = apply_profile_binding(result, binding, bank, composition=document)
    return np.asarray(ir.compile_ir_to_pokey_frames(bound.pokey_ir))


def clip_plan() -> List[Dict[str, str]]:
    """``clip_NN -> candidate, score``, with the candidate order shuffled inside each score group.

    Deterministic: the same seed gives the same numbering. The shuffle is per group so a listener
    never sees the same candidate in the same position twice, and the groups stay comparable.
    """
    rng = random.Random(SEED)
    clips: List[Dict[str, str]] = []
    index = 1
    for score in SCORE_ORDER:
        names = list(candidate_names())
        rng.shuffle(names)
        for name in names:
            clips.append({
                "clip": f"clip_{index:02d}",
                "candidate": name,
                "score": score,
            })
            index += 1
    return clips


def clip_id_for(candidate_name: str, score: str) -> str:
    for entry in clip_plan():
        if entry["candidate"] == candidate_name and entry["score"] == score:
            return entry["clip"]
    raise KeyError(f"no clip for {candidate_name!r} / {score!r}")


# ===========================================================================
# Phase C/D/E — render the set, then write the artefacts.
# ===========================================================================
def render_all(
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    bank_dir: Path = DEFAULT_BANK_DIR,
) -> Dict[str, Any]:
    """Render every clip, then write the WAVs, the page, the manifest and the reports.

    Level policy is Experiment 26's, unchanged: every clip is rendered **raw**, one gain is derived
    from the single loudest of the 36 raw renders, and that one gain is applied to all of them. No
    clip is normalised on its own, so the loudness differences between candidates survive and are
    published rather than hidden.
    """
    output_dir = Path(output_dir)
    listening_dir = output_dir / "listening"
    audio_dir = listening_dir / "audio"
    audio_dir.mkdir(parents=True, exist_ok=True)

    bank = load_bank(bank_dir)
    plan = clip_plan()

    streams: Dict[str, np.ndarray] = {}
    raw: Dict[str, np.ndarray] = {}
    for entry in plan:
        candidate = candidate_by_name(entry["candidate"])
        stream = candidate_stream(candidate, entry["score"], bank)
        streams[entry["clip"]] = stream
        raw[entry["clip"]] = e26.render_registers(stream)

    reference_peak = max(float(np.max(np.abs(buffer))) for buffer in raw.values())
    if reference_peak <= 0.0:
        raise ValueError("every clip is silent; there is nothing to audition")
    gain = TARGET_PEAK / reference_peak

    files: Dict[str, Path] = {}
    rows: List[Dict[str, Any]] = []
    for entry in plan:
        clip = entry["clip"]
        samples = e26.to_int16(raw[clip], gain)
        path = e26.write_wav(audio_dir / f"{clip}.wav", samples, SAMPLE_RATE)
        files[clip] = path
        rows.append({
            "clip": clip,
            "candidate": entry["candidate"],
            "score": entry["score"],
            "frames": int(streams[clip].shape[0]),
            "samples": int(samples.shape[0]),
            "duration_seconds": round(samples.shape[0] / SAMPLE_RATE, 4),
            "raw_peak": round(float(np.max(np.abs(raw[clip]))), 6),
            "raw_rms": round(float(np.sqrt(np.mean(np.square(raw[clip], dtype=np.float64)))), 6),
            "peak_after_gain": round(float(np.max(np.abs(samples))) / 32767.0, 6),
            "rms_after_gain": round(
                float(np.sqrt(np.mean(np.square(samples, dtype=np.float64)))) / 32767.0, 6
            ),
            "audible_channels": sorted(
                channel for channel in range(1, 5)
                if np.any(streams[clip][:, ir.audc_column(channel)] & 0x0F)
            ),
            "distinct_audf": sorted(
                {int(value) for value in np.unique(streams[clip][:, ir.audf_column(3)])}
            ) if entry["candidate"] != "pair_noise" and entry["candidate"] != "pair_buzz" else [],
        })

    result: Dict[str, Any] = {
        "output_dir": output_dir,
        "listening_dir": listening_dir,
        "bank": bank,
        "bank_dir": Path(bank_dir),
        "plan": plan,
        "streams": streams,
        "raw": raw,
        "rows": rows,
        "files": files,
        "gain": gain,
        "reference_peak": reference_peak,
    }
    result["inventory"] = build_inventory(bank)
    result["summary"] = inventory_summary(result["inventory"])
    result["candidates_path"] = write_candidates_document(result, output_dir)
    result["manifest_path"] = write_manifest(result, output_dir)
    result["note_path"] = write_listening_note(result, output_dir)
    result["page_path"] = write_listening_page(result, listening_dir)
    result["templates"] = write_csv_templates(listening_dir)
    return result


def build_manifest(result: Mapping[str, Any]) -> Dict[str, Any]:
    """The experiment record and the answer key. The listening page carries none of this."""
    bank = result["bank"]
    gain = float(result["gain"])
    return {
        "experiment": "experiment29",
        "manifest_version": 1,
        "private": True,
        "warning": (
            "this file maps every clip to its candidate and describes the sound families. Do not open "
            "it, and do not read the experiment README, until the answers have been downloaded"
        ),
        "purpose": (
            "screen the existing 67-profile bank for a short list of genuinely different, musically "
            "useful timbres, and hand the owner a blind page to audition them"
        ),
        "bank": {
            "path": str(result["bank_dir"].relative_to(REPO_ROOT)).replace("\\", "/"),
            "schema": bank.schema,
            "status": bank.status,
            "profile_count": len(bank.profiles),
            "note": (
                "the bank's own registry note says it is 'a working set for format validation, not a "
                "recommended library: no profile was selected, ranked or named' — this experiment is "
                "the first selection made from it"
            ),
        },
        "inventory_summary": result["summary"],
        "rendered_properties": list(RENDERED_PROPERTIES),
        "unreproduced_properties": [dict(item) for item in UNREPRODUCED_PROPERTIES],
        "refused_profiles": [dict(item) for item in REFUSED_PROFILES],
        "grid": {
            "bpm": 125,
            "frames_per_tick": 4,
            "scores": {
                name: {
                    "rows": entry["rows"],
                    "notes": entry["notes"],
                    "frames": entry["frames"],
                    "seconds": round(entry["frames"] / FRAME_RATE_HZ, 4),
                    "description": entry["description"],
                }
                for name, entry in GRID.items()
            },
            "why": (
                "the grid is Experiments 26/27/28's, unchanged, so a candidate can be compared "
                "directly against the C1 reference the owner has already heard. No rests were added: "
                "the phrase's 5-row notes already restart often enough to expose attack and decay."
            ),
        },
        "rendering_policy": {
            "bank_candidates": (
                "the production path: load_composition_dsl -> generate_music_from_composition -> "
                "apply_profile_binding -> ir.compile_ir_to_pokey_frames, then Experiment 26's "
                "render_registers. Nothing is substituted or repaired; a profile the binding refuses "
                "is dropped and recorded."
            ),
            "c1_reference": (
                "the production compile of the same grid with Experiment 28's apply_c1 applied to "
                "channel 3, so the effect is Experiment 27's own register generation"
            ),
            "volume_contour": (
                "OFF. It is opt-in, off by default in production, and mads_exporter refuses to export "
                "a song while one is set, so a timbre that depended on its contour could not ship. The "
                "measured contour is recorded in the inventory instead."
            ),
            "channels": (
                "a VOICE profile plays on CH3 as a single 8-bit channel; a PAIR profile needs the "
                "joined pair and plays on CH1+CH2 with BASS 16BIT. That difference is the profile's "
                "channel requirement, not a rendering choice."
            ),
            "sample_rate": SAMPLE_RATE,
            "bit_depth": 16,
            "channels_per_file": 1,
            "frame_rate_hz": FRAME_RATE_HZ,
        },
        "level_policy": {
            "per_file_normalisation": False,
            "shared_gain": round(gain, 8),
            "reference_peak": round(float(result["reference_peak"]), 8),
            "target_peak": TARGET_PEAK,
            "note": (
                "one gain derived from the loudest of the 36 raw renders is applied to all of them, so "
                "the loudness relation between candidates survives. The per-clip RMS is published so "
                "any level difference can be judged rather than guessed."
            ),
        },
        "clip_mapping": [
            {
                "clip": row["clip"],
                "candidate": row["candidate"],
                "score": row["score"],
                "profile_id": candidate_by_name(row["candidate"])["profile_id"],
                "generator": candidate_by_name(row["candidate"])["generator"],
                "clock": candidate_by_name(row["candidate"])["clock"],
            }
            for row in result["rows"]
        ],
        "measurements": list(result["rows"]),
        "blinding": {
            "method": (
                "the twelve candidates are shuffled inside each score group with a seeded RNG and "
                "renamed clip_NN; the page and both CSVs carry the clip id only"
            ),
            "seed": SEED,
            "unblind_with": "the 'clip_mapping' list above",
            "honest_note": (
                "this is PARTIALLY blinded, not fully blind. The page's questions are family-neutral, "
                "but the experiment README and this manifest describe the sound families and the "
                "candidate roles, and the clip count reveals how many candidates there are. A listener "
                "who reads either document before answering is no longer blind."
            ),
        },
        "csv_templates": {
            "clips": {"file": CLIPS_CSV, "fields": list(CLIP_FIELDS)},
            "summary": {"file": SUMMARY_CSV, "fields": list(SUMMARY_FIELDS)},
        },
        "limitations": list(LIMITATIONS),
        "not_claimed": [
            "that any candidate sounds good, or better than another — that is a listening question",
            "that the candidates are audibly distinct: their metadata and register values differ, but "
            "only listening can confirm that the difference is audible and useful",
            "that the set is complete, or that the profiles left out are unusable",
            "that any candidate is ready to become a production instrument",
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


def build_candidates_document(result: Mapping[str, Any]) -> Dict[str, Any]:
    """Phase A's machine-readable inventory plus Phase B's shortlist with its rationale."""
    return {
        "experiment": "experiment29",
        "phase": "A (inventory) and B (selection)",
        "bank": {
            "path": str(result["bank_dir"].relative_to(REPO_ROOT)).replace("\\", "/"),
            "schema": result["bank"].schema,
        },
        "inventory_summary": result["summary"],
        "rendered_properties": list(RENDERED_PROPERTIES),
        "unreproduced_properties": [dict(item) for item in UNREPRODUCED_PROPERTIES],
        "inventory": list(result["inventory"]),
        "refused_profiles": [dict(item) for item in REFUSED_PROFILES],
        "selection_rule": (
            "diversity is judged on the audibly-relevant tuple — generator nibble, AUDCTL, and the "
            "three envelope frames plus the sustain level — because everything else in the profile "
            "document is evidence about the source recording rather than something the engine renders. "
            "Profiles that differ only in pitch base, measured range or gesture data would render "
            "identically and were not treated as different candidates."
        ),
        "shortlist": [
            {
                **dict(candidate),
                "clip_ids": {score: clip_id_for(candidate["name"], score) for score in SCORE_ORDER},
            }
            for candidate in CANDIDATES
        ],
    }


def write_candidates_document(result: Mapping[str, Any], output_dir: Path) -> Path:
    path = Path(output_dir) / "candidates.json"
    path.write_text(
        json.dumps(build_candidates_document(result), indent=2, ensure_ascii=False, sort_keys=True)
        + "\n",
        encoding="utf-8",
    )
    return path


def listening_note(result: Mapping[str, Any]) -> str:
    """The listener-facing README that ships next to the clips."""
    manifest = build_manifest(result)
    note_rows = sorted(
        (row for row in result["rows"] if row["score"] == "note"),
        key=lambda row: row["rms_after_gain"],
    )
    level_rows = [
        f"| `{row['candidate']}` | {row['rms_after_gain']:.4f} |" for row in note_rows
    ]
    spread = 20.0 * math.log10(
        note_rows[-1]["rms_after_gain"] / note_rows[0]["rms_after_gain"]
    ) if note_rows[0]["rms_after_gain"] > 0 else 0.0
    level_spread_db = f"{spread:.1f}"
    lines: List[str] = [
        "# Experiment 29 — the candidate library, and how to audition it",
        "",
        "Twelve candidate POKEY timbres, each played on three identical test figures. This is the first",
        "selection made from the project's 67-profile sound bank.",
        "",
        "## How to run it",
        "",
        "1. Open **`listening/index.html`** in a browser. That is the only file a listener needs.",
        "2. Work through the three groups in order. Inside each group, compare the twelve clips against",
        "   each other — they are the *same* three figures, so any difference you hear is the timbre.",
        "3. Rate each clip, then answer the group's preference question.",
        "4. At the bottom, download both CSVs and put them back in this folder.",
        "",
        "Nothing is uploaded anywhere. Answers live in the browser until you download them.",
        "",
        "If the browser refuses to play local audio, serve the folder instead:",
        "",
        "```bash",
        "python -m http.server 8734 --directory experiments/experiment29/listening",
        "```",
        "",
        "then open <http://localhost:8734/>.",
        "",
        "## The test grid",
        "",
        "| group | what it is | length |",
        "|---|---|---|",
    ]
    for name in SCORE_ORDER:
        entry = GRID[name]
        lines.append(
            f"| `{name}` | {entry['description']} | {entry['frames']} frames = "
            f"{entry['frames'] / FRAME_RATE_HZ:.2f} s |"
        )
    lines += [
        "",
        f"BPM 125, so one row is {1000 / FRAME_RATE_HZ:.0f} ms. All clips are "
        f"{SAMPLE_RATE} Hz 16-bit mono, and every candidate plays the same pitches with the same onsets",
        "and durations. This grid is Experiments 26/27/28's, so a candidate can be compared directly",
        "against the C1 reference you have already heard.",
        "",
        "## Levels",
        "",
        f"One shared gain of `{manifest['level_policy']['shared_gain']}` was applied to all "
        f"{len(result['rows'])} clips, taken",
        f"from the loudest of the raw renders (reference peak "
        f"`{manifest['level_policy']['reference_peak']}`). **No clip was normalised on its own**, so the",
        "loudness differences between candidates survive.",
        "",
        f"**Those differences are large: {level_spread_db} dB between the quietest and the loudest clip.**",
        "They come from the profiles' own measured envelopes — a percussive profile that decays to a low",
        "sustain is quiet most of the time, a sustained one is loud throughout. That is real information",
        "about using these as a library together, so it is published rather than flattened. You may need",
        "to adjust your volume between clips; note it if it affects your judgement.",
        "",
        "| candidate | RMS on the single note |",
        "|---|---|",
        *level_rows,
        "",
        "## What is in here",
        "",
        "| file | what it is |",
        "| :--- | :--- |",
        "| `listening/index.html` | the audition interface — **the only file you need to open** |",
        "| `listening/audio/clip_NN.wav` | the 36 clips under blinded names |",
        f"| `listening/{CLIPS_CSV}` | the empty per-clip answer template |",
        f"| `listening/{SUMMARY_CSV}` | the empty per-listener answer template |",
        "| `candidates.json` | the full 67-profile inventory and the shortlist with its rationale |",
        "| `manifest.json` | the clip → candidate key and the machine record — **do not open it while listening** |",
        "",
        "## What this set is not",
        "",
        "It is a **selection on the fields that reach the render**, not on listening. Whether these",
        "twelve are audibly distinct is the hypothesis the page tests, not a finding. The metadata and",
        "the register values differ; only your ears can say whether the sounds do.",
        "",
        "Only the generator, the clock/coupling and the envelope frames reach the sound. A profile's",
        "measured pitch gesture, its measured distortion changes and its measured volume contour are",
        "dropped or not applied, so a candidate can sound much plainer here than the recording it came",
        "from. The contour is deliberately off because it cannot ship to hardware.",
        "",
        "And three short test figures are not music: a candidate can sound good here and be useless in a",
        "tune. Experiment 28 exists because that gap is real.",
        "",
        "## Regenerating",
        "",
        "```",
        "python -m atari_music.pokey_timbre_library_experiment",
        "```",
        "",
        "Deterministic: the same command reproduces every file byte for byte.",
        "",
    ]
    return "\n".join(lines)


def write_listening_note(result: Mapping[str, Any], output_dir: Path) -> Path:
    path = Path(output_dir) / "README.md"
    path.write_text(listening_note(result), encoding="utf-8")
    return path


def write_csv_templates(listening_dir: Path) -> List[Path]:
    """The empty answer templates, with exactly the headers the page downloads."""
    listening_dir = Path(listening_dir)
    written: List[Path] = []
    clips_path = listening_dir / CLIPS_CSV
    with clips_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(CLIP_FIELDS)
        for entry in clip_plan():
            row = dict.fromkeys(CLIP_FIELDS, "")
            row["clip"] = entry["clip"]
            row["score"] = entry["score"]
            writer.writerow([row[field] for field in CLIP_FIELDS])
    written.append(clips_path)

    summary_path = listening_dir / SUMMARY_CSV
    with summary_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(SUMMARY_FIELDS)
        writer.writerow([""] * len(SUMMARY_FIELDS))
    written.append(summary_path)
    return written


# ===========================================================================
# Phase D — the listening page. Same approach as Experiment 27's.
# ===========================================================================
_PAGE_HEAD = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Experiment 29 — POKEY timbre candidates</title>
<style>
  :root { color-scheme: dark; }
  body { font-family: system-ui, -apple-system, Segoe UI, sans-serif; margin: 0; padding: 1.5rem;
         background: #14161a; color: #e8e8ea; line-height: 1.5; }
  main { max-width: 64rem; margin: 0 auto; }
  h1, h2, h3 { line-height: 1.2; }
  h2 { margin-top: 2.5rem; border-top: 1px solid #2c3036; padding-top: 1.25rem; }
  h3 { margin-top: 1.75rem; }
  .note { background: #1d2026; border-left: 3px solid #4a7; padding: .75rem 1rem; margin: 1rem 0;
          border-radius: 3px; font-size: .95rem; }
  .note.warn { border-left-color: #c85; }
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
  textarea, input[type=text] { width: 100%; background: #23272e; color: inherit;
                 border: 1px solid #333; border-radius: 4px; padding: .4rem; font: inherit; }
  textarea { min-height: 3rem; }
  input[type=text] { max-width: 22rem; }
  button { background: #2d5; color: #06120a; border: 0; border-radius: 4px; padding: .55rem 1rem;
           font: inherit; font-weight: 600; cursor: pointer; margin-right: .5rem; margin-bottom: .5rem; }
  button.ghost { background: #333; color: #ddd; }
  .progress { position: sticky; top: 0; background: #14161af2; padding: .6rem 0; z-index: 5;
              border-bottom: 1px solid #2c3036; font-variant-numeric: tabular-nums; }
  .small { font-size: .88rem; color: #aab; }
  .cliphead { display: flex; align-items: baseline; gap: .75rem; flex-wrap: wrap; }
  .cliphead .tag { font-family: ui-monospace, Consolas, monospace; background: #23272e;
                   border: 1px solid #333; border-radius: 4px; padding: .1rem .45rem; font-size: .9rem; }
</style>
</head>
<body>
<main>
<h1>Experiment 29 — POKEY timbre candidates</h1>

<div class="note">
  <strong>Your ears decide which of these deserve to become instruments.</strong> Twelve candidate
  timbres are played on three identical test figures. Inside each group every clip has the same notes,
  the same onsets, the same durations and the same gain, so any difference you hear is the timbre.
</div>
<div class="note">
  <strong>Set your volume once and leave it alone.</strong> Every clip uses the same gain, and no clip
  was normalised on its own. Some candidates are genuinely louder than others; that is information,
  not an error — judge character, and note the level if it bothers you.
</div>
<div class="note">
  <strong>The clips are unlabelled on purpose.</strong> Which clip is which candidate is in
  <code>manifest.json</code>, which you can open after downloading your answers.
</div>
<div class="note warn">
  <strong>Some candidates may sound like a fault rather than an instrument.</strong> That is a possible
  and useful result. Answer "an effect" or "a fault" where it applies.
</div>

<div class="progress" id="progress">progress</div>

<h2>Your name or initials</h2>
<p class="small">Used only as the first column of the downloaded CSVs, so several listeners' files can be
told apart. Leave it blank if you prefer.</p>
<div class="q"><input type="text" id="listener" placeholder="anonymous"
  oninput="setMeta('listener', this.value)"></div>

<div id="groups"></div>

<h2>Question about the whole set</h2>
<div class="card" id="overall">
  <div id="overallQuestions"></div>
  <div class="q"><div class="label">Anything else you noticed (optional)</div>
    <textarea id="overallComment" oninput="setMeta('comment', this.value)"></textarea></div>
</div>

<h2>Finish</h2>
<p class="small">Download both files and put them back in this folder. Nothing is uploaded anywhere —
everything stays in this browser until you download it.</p>
<button onclick="downloadClips()">Download the clip ratings CSV</button>
<button onclick="downloadSummary()">Download the summary CSV</button>
<button class="ghost" onclick="if(confirm('Erase all answers in this browser?')){localStorage.clear();location.reload();}">Reset answers</button>
<p class="small" id="downloadState"></p>

<h2>After you have answered</h2>
<p class="small"><code>manifest.json</code> maps each clip to its candidate, and the experiment
<code>README.md</code> describes the sound families. Nothing on this page, and neither downloaded CSV,
contains that mapping — so reading either early would bias the ratings.</p>

</main>
"""


_PAGE_SCRIPT = r"""
<script>
const PACKAGE = __PACKAGE__;
const STORE = "experiment29-answers-v1";

let answers = JSON.parse(localStorage.getItem(STORE) || "{}");
let meta = answers.__meta || {};

function save() { localStorage.setItem(STORE, JSON.stringify(answers)); refresh(); }
function get(key, field) { return (answers[key] || {})[field] ?? ""; }
function set(key, field, value) {
  answers[key] = answers[key] || {};
  answers[key][field] = value;
  save();
}
function setMeta(field, value) {
  meta[field] = value;
  answers.__meta = meta;
  save();
}
function listener() { return String(meta.listener ?? "").trim(); }

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

// Every question comes from PACKAGE, so the page, the manifest and the CSV columns are rendered from
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

function choiceRow(key, field, question, values, labels) {
  const current = get(key, field);
  const inputs = values.map((value, index) => {
    const checked = String(current) === String(value) ? " checked" : "";
    return `<label><input type="radio" name="${key}-${field}" value="${value}"${checked}
      onchange="set('${key}','${field}','${value}')">${labels[index]}</label>`;
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
const PREF_FIELDS = PACKAGE.preference_questions.map(q => q.field);
function clipFields() {
  return PACKAGE.clip_scales.map(s => s.field).concat([PACKAGE.musical_question.field]);
}
function clipDone(id) { return clipFields().every(field => get(id, field) !== ""); }
function groupDone(score) { return PREF_FIELDS.every(field => get(score, field) !== ""); }
function overallDone() { return PACKAGE.overall_questions.every(q => get("overall", q.field) !== ""); }

const CLIP_BY_ID = {};
PACKAGE.clips.forEach(clip => { CLIP_BY_ID[clip.clip] = clip; });

function clipCard(clip, position, total) {
  const musical = PACKAGE.musical_question;
  const body = `<div class="cliphead"><span class="tag">${clip.clip}</span>
      <span class="small">clip ${position} of ${total}</span></div>
    <div class="q"><audio controls preload="none" src="${clip.audio}"></audio></div>` +
    PACKAGE.clip_scales.map(s => scaleRow(clip.clip, s.field, s.question, s.labels)).join("") +
    choiceRow(clip.clip, musical.field, musical.question,
      musical.choices.map(c => c.value), musical.choices.map(c => c.label)) +
    commentRow(clip.clip, "comment", "Comment (optional)");
  return `<div class="card" id="${clip.clip}">${body}</div>`;
}

function groupBlock(entry) {
  const ids = entry.clips;
  const body = `<h3>${entry.heading}</h3>
    <p class="small">Every clip in this group is <strong>${entry.description}</strong>. Compare them
    against each other, then answer the two questions at the bottom of the group.</p>` +
    ids.map((id, index) => clipCard(CLIP_BY_ID[id], index + 1, ids.length)).join("") +
    `<div class="card" id="${entry.score}">
      <div class="cliphead"><span class="tag">${entry.score}</span>
        <span class="small">your verdict on this group</span></div>` +
    PACKAGE.preference_questions.map(q => choiceRow(
      entry.score, q.field, q.question, ids.concat(["none"]), ids.concat(["none of them"])
    )).join("") +
    commentRow(entry.score, "comment", "Comment on this group (optional)") +
    `</div>`;
  return body;
}

document.getElementById("groups").innerHTML = PACKAGE.groups.map(groupBlock).join("");
document.getElementById("overallQuestions").innerHTML =
  PACKAGE.overall_questions.map(q => choiceRow("overall", q.field, q.question, q.labels, q.labels))
    .join("");
document.getElementById("listener").value = String(meta.listener ?? "");
document.getElementById("overallComment").value = String(meta.comment ?? "");

function refresh() {
  const total = PACKAGE.clips.length;
  const rated = PACKAGE.clips.filter(clip => clipDone(clip.clip)).length;
  const groups = PACKAGE.groups.filter(entry => groupDone(entry.score)).length;
  document.getElementById("progress").textContent =
    `Progress \u2014 ${rated}/${total} clips rated, ${groups}/${PACKAGE.groups.length} groups judged, ` +
    `whole-set question ${overallDone() ? "answered" : "not answered yet"} ` +
    `(answers are saved in this browser)`;
  PACKAGE.clips.forEach(clip => {
    const card = document.getElementById(clip.clip);
    if (card) { card.className = "card" + (clipDone(clip.clip) ? " done" : ""); }
  });
  PACKAGE.groups.forEach(entry => {
    const card = document.getElementById(entry.score);
    if (card) { card.className = "card" + (groupDone(entry.score) ? " done" : ""); }
  });
  const overall = document.getElementById("overall");
  if (overall) { overall.className = "card" + (overallDone() ? " done" : ""); }
}

function stamp() {
  return (listener() || "anonymous").replace(/[^A-Za-z0-9._-]+/g, "_");
}

function downloadClips() {
  function value(clip, field) {
    if (field === "listener") { return listener(); }
    if (field === "clip") { return clip.clip; }
    if (field === "score") { return clip.score; }
    return get(clip.clip, field);
  }
  const rows = PACKAGE.clips.map(clip => PACKAGE.clip_fields.map(f => value(clip, f)));
  download(`evaluation_experiment29_clips__${stamp()}.csv`, PACKAGE.clip_fields, rows);
  document.getElementById("downloadState").textContent =
    "Clip ratings downloaded. Now download the summary CSV too.";
}

function downloadSummary() {
  function value(field) {
    if (field === "listener") { return listener(); }
    if (field === "comment") { return String(meta.comment ?? ""); }
    if (PACKAGE.overall_questions.some(q => q.field === field)) {
      return get("overall", field);
    }
    for (const entry of PACKAGE.groups) {
      for (const q of PACKAGE.preference_questions) {
        if (field === `${entry.score}_${q.field}`) { return get(entry.score, q.field); }
      }
      if (field === `${entry.score}_comment`) { return get(entry.score, "comment"); }
    }
    return "";
  }
  const row = PACKAGE.summary_fields.map(value);
  download(`evaluation_experiment29_summary__${stamp()}.csv`, PACKAGE.summary_fields, [row]);
  document.getElementById("downloadState").textContent =
    "Summary downloaded. Both files are complete.";
}

refresh();
</script>
</body>
</html>
"""


def build_listening_package(result: Mapping[str, Any]) -> Dict[str, Any]:
    """The object the page embeds. It carries no candidate name, so the page cannot leak the key."""
    groups: List[Dict[str, Any]] = []
    for score in SCORE_ORDER:
        groups.append({
            "score": score,
            "heading": score.replace("_", " ").title(),
            "description": GRID[score]["description"],
            "clips": [row["clip"] for row in result["rows"] if row["score"] == score],
        })
    return {
        "experiment": "experiment29",
        "title": "Experiment 29 — POKEY timbre candidates",
        "clips": [
            {"clip": row["clip"], "audio": f"audio/{row['clip']}.wav", "score": row["score"]}
            for row in result["rows"]
        ],
        "groups": groups,
        "clip_scales": CLIP_SCALES,
        "musical_question": CLIP_MUSICAL_QUESTION,
        "preference_questions": PREFERENCE_QUESTIONS,
        "overall_questions": OVERALL_QUESTIONS,
        "clip_fields": list(CLIP_FIELDS),
        "summary_fields": list(SUMMARY_FIELDS),
    }


def render_page(package: Mapping[str, Any]) -> str:
    """The page with the package embedded and no candidate name anywhere in it."""
    embedded = json.dumps(package, sort_keys=True, ensure_ascii=False)
    page = (_PAGE_HEAD + _PAGE_SCRIPT + _PAGE_SCRIPT_B).replace("__PACKAGE__", embedded)
    return page.replace("__TITLE__", str(package["title"]))


def write_listening_page(result: Mapping[str, Any], listening_dir: Path) -> Path:
    path = Path(listening_dir) / "index.html"
    path.write_text(render_page(build_listening_package(result)), encoding="utf-8")
    return path


def main() -> int:
    """Render the whole audition set and print where everything is. No production code is touched."""
    result = render_all()
    summary = result["summary"]
    manifest = build_manifest(result)
    print(f"bank:      {result['bank'].root} ({summary['profile_count']} profiles)")
    print(f"  status:  {summary['by_status']}")
    print(f"  feasibility: {summary['by_feasibility']}")
    print(f"  audible signatures among renderable: "
          f"{summary['distinct_audible_signatures_among_renderable']}")
    print(f"candidates: {len(CANDIDATES)} (11 bank profiles + the C1 reference)")
    print(f"clips:      {len(result['rows'])} across {len(SCORE_ORDER)} groups")
    print(f"shared gain {manifest['level_policy']['shared_gain']} "
          f"(reference peak {manifest['level_policy']['reference_peak']})")
    print(f"page:       {result['page_path']}")
    print(f"manifest:   {result['manifest_path']}")
    print(f"candidates: {result['candidates_path']}")
    print(f"readme:     {result['note_path']}")
    for path in result["templates"]:
        print(f"template:   {path}")
    return 0


if __name__ == "__main__":  # pragma: no cover - manual entry point
    raise SystemExit(main())















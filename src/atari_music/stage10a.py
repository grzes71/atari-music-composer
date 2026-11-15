"""Stage 10A: does evidence-based profile *assignment* improve whole songs?

Stage 9C compared six real songs rendered with the composer's own instruments against the same six
rendered with this library bound, and the profile-bound side lost 5-0. Stage 9E then measured why
the *machine* comparison is so flat and, separately, found that the bindings in ``examples/songs/``
were chosen by **generator family** — not by anything the listener said. So the 5-0 result does not
yet prove that profiles are wrong for whole songs; it may only mean the wrong profile was put on
each role.

This module prepares the experiment that separates those two readings. It changes **nothing in the
library, the renderer, the player, the composer, the DSL or the profiles**. The composition
documents are the same bytes, the renderer is the same code, the profiles are the same documents;
the *only* variable is which profile is bound to which already-declared instrument::

    composition (unchanged)
        |
        +-- the composer's own instruments    -> DEFAULT
        +-- examples/songs/*.binding.json     -> OLD   (generator-family assignment, unchanged)
        +-- this module's new binding         -> NEW   (assignment from the listening evidence)

Three renders per song, and a blinded listening package that asks which side is better. The machine
analysis explains the differences; it deliberately does **not** declare a winner, because the point
of the stage is that the previous claim (5-0) was a *machine* claim that only a listener can settle.

How a replacement is chosen (all of it mechanical, none of it taste):

* **Role class.** A role whose instrument id or name mentions percussion, drum, noise or beat is
  UNPITCHED; everything else is PITCHED. A profile may serve a role only if the listener heard it
  the same way: a PITCHED role accepts only profiles the listener tagged ``lead_tonal`` (the profile
  followed the melody in the audition), an UNPITCHED role only profiles tagged ``percussive_noisy``.
* **Channel groups.** Every instrument sounding on a channel shares one profile, because a POKEY
  channel carries one generator. A song's channels are therefore decided as units, not roles.
* **Compatibility is measured, not assumed.** A candidate is considered only if a binding carrying
  it *applies*: ``apply_profile_binding`` is run and any refusal removes the candidate.
* **A change needs to beat the old profile, not merely differ from it.** The listener's own scales
  decide. Stage 9D measured the listener against themselves on byte-identical pairs — usefulness
  ICC(1,1) 0.76, distinctiveness 0.73, Atari character 0.92 — so a single one-point difference is
  inside their own disagreement. A replacement is adopted only when it is rated **no lower on any of
  the three scales** and either improves one scale by 2 or more, or improves two scales together.
  A single one-point gain is not evidence, and the profile with no ratings at all is never chosen.

  Distinctiveness is deliberately *not* a criterion of its own. Stage 9D's listening shows
  distinctiveness and Atari character pulling in opposite directions (Spearman **−0.57**, n=60),
  and the brief's criteria are usefulness and Atari character. So the rule never buys
  distinctiveness with character — which is why a profile the listener called "typical atari lead
  tone" (character 5, distinctiveness 1) is *kept* rather than replaced by a more distinctive sound
  they rated less Atari-like.
* **Level and timing are untouched.** Same excerpt window, same shared gain derived from the default
  render, same sample rate, no compression, no EQ, no per-side level matching.

The audio the listener will judge is verified rather than trusted: the DEFAULT and OLD sides are
compared **byte for byte** with the Stage 9C package's own song WAVs. They are identical, which is
what makes this comparison comparable with the listening it re-tests.
"""

from __future__ import annotations

import csv
import hashlib
import json
import math
import os
import random
from collections import Counter, OrderedDict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

import numpy as np

from atari_music.ai.client import (
    generate_music_from_composition,
    load_composition_dsl,
    load_composition_json,
)
from atari_music.ir import (
    FRAME_COLUMN_NAMES,
    IRSong,
    compile_ir_to_pokey_frames,
    resolve_audctl_mode,
)
from atari_music.pokey_synth import render_pokey_samples
from atari_music.sound_profiles import (
    SoundProfileBank,
    SoundProfileError,
    apply_profile_binding,
    load_profile_binding,
    load_sound_profile_bank,
)
from atari_music.sound_profiles.binding import (
    _channels_with_notes,
    _instrument_channels,
    _resolve_targets,
)
from atari_music.stage9c import (
    SAMPLE_RATE,
    SONG_EXCERPT_SECONDS,
    TARGET_PEAK,
    spectral_distance,
    spectral_features,
    write_wav,
)

#: The experiment this module builds.
EXPERIMENT = "stage10a"

#: Version of the manifest this module writes.
MANIFEST_VERSION = "stage10a/1"

#: Version of the machine-readable extracts.
ANALYSIS_VERSION = "stage10a/1"

#: The default package directory.
DEFAULT_PACKAGE_DIR = Path("examples/sound_profile_rebinding_10a")

#: Where the Stage 9C package lives (read only: it is the record of the six songs).
DEFAULT_STAGE9C_PACKAGE = Path("examples/sound_profile_listening")

#: Where the per-song bindings live (read only: they are the OLD assignment).
DEFAULT_SONGS_DIR = Path("examples/songs")

#: The default profile bank.
DEFAULT_BANK_DIR = Path("tests/data/sound_profiles/bank")

#: Where the Stage 9D human evidence lives (read only).
DEFAULT_STAGE9D_REPORTS = Path("reports/stage9d")

#: Where the machine-readable extracts are written.
DEFAULT_ANALYSIS_REPORTS = Path("reports/stage10a")

#: Where the report is written.
DEFAULT_DOCS_DIR = Path("docs")

#: Seed for the blinded orientation. Recorded in the manifest.
SEED = 20261006

#: The listener's own vocabulary, as Stage 9D recorded it. A profile may serve a role only if the
#: listener heard it the way that role needs.
TAG_TONAL = "lead_tonal"
TAG_PERCUSSIVE = "percussive_noisy"
TAG_ARTEFACT = "artefact"

#: Words in an instrument's id or name that make its role UNPITCHED.
UNPITCHED_WORDS = ("perc", "drum", "noise", "beat")

#: How a replacement can be justified. See the module docstring.
RULE_MARGIN = "margin"
RULE_CONSISTENT = "consistent"

#: A gain on one listener rating this large is outside the disagreement the listener showed against
#: themselves on byte-identical sounds (Stage 9D: usefulness ICC(1,1) 0.76, distinctiveness 0.73).
MARGIN = 2.0

#: The listener's neutral point on the Atari-character scale. A sound they heard as *not* Atari-like
#: cannot be the improvement in an Atari composition, whatever else it scores.
CHARACTER_FLOOR = 3.0

#: Stage 9D's measured correlation between the listener's distinctiveness and Atari-character
#: judgements, over the whole library. Quoted in the module docstring and in the report because it is
#: why distinctiveness alone never justifies a replacement.
DISTINCTIVENESS_CHARACTER_RHO = -0.5689

#: The listening-session drift Stage 9D measured against presentation order, which is why the package
#: repeats the Stage 9C comparison as a control.
SESSION_DRIFT_RHO = {"atari_character": -0.367, "confidence": -0.472}

#: The three pairs every song contributes, as (kind, left version, right version).
TRIAL_KINDS: Tuple[Tuple[str, str, str], ...] = (
    ("default_vs_new", "default", "new"),
    ("old_vs_new", "old", "new"),
    ("default_vs_old", "default", "old"),
)

#: The pairs by kind.
TRIAL_KIND_LOOKUP: Dict[str, Tuple[str, str]] = {
    kind: (left, right) for kind, left, right in TRIAL_KINDS
}

#: The columns of the answer template.
ANSWER_HEADER: Tuple[str, ...] = (
    "trial_id",
    "better_overall",
    "more_convincing_atari",
    "more_interesting_character",
    "difference_1_5",
    "comment",
)

#: The pools the Stage 9B/9C bindings were drawn from, by generator family. The wording mirrors
#: `docs/profile_integration.md` §13.1, which documents the strategy the old bindings follow.
SELECTION_POOLS: Tuple[Tuple[str, str, str], ...] = (
    ("PAIR", "16-bit bass pool", "$C poly4 at $50, because the song's own channel 1 joins 1+2"),
    ("VOICE/$8", "percussion pool", "$8 poly9/17, the composer's own noise generator"),
    ("VOICE/$C", "8-bit bass pool", "$C poly4, the composer's own bass default"),
    ("VOICE/$0", "pure-noise pool", "$0 noise, unpitched"),
    ("VOICE/$A", "melodic pool", "$A pure tone, the composer's own lead/harmony default"),
)


class Stage10AError(RuntimeError):
    """The experiment cannot be prepared as specified."""


# ===========================================================================
# The six songs
# ===========================================================================
@dataclass(frozen=True)
class SongPlan:
    """One Stage 9C Part C song, as that package recorded it."""

    trial_id: str
    song: str
    song_path: Path
    old_binding_path: Path
    old_profiles: Dict[str, str]
    stage9c_entry: Dict[str, Any]


def recover_songs(
    stage9c_package: Path, songs_dir: Path
) -> Tuple[List[SongPlan], Dict[str, Any]]:
    """The exact six Part C songs, taken from the Stage 9C manifest rather than guessed.

    The manifest is the record of what the listener actually heard. The per-song binding file is
    then re-read and must agree with it at the level of profile ids: a binding edited since the
    experiment would silently change what "OLD" means, so it is refused instead.
    """
    manifest_path = stage9c_package / "manifest.json"
    if not manifest_path.is_file():
        raise Stage10AError(
            f"the Stage 9C package is not present ({manifest_path}); its manifest is the record of "
            "the six songs this experiment must use"
        )
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    trials = manifest.get("song_trials") or []
    if len(trials) != 6:
        raise Stage10AError(
            f"the Stage 9C manifest lists {len(trials)} song trials; this experiment is defined "
            "over the six Part C songs"
        )

    plans: List[SongPlan] = []
    for entry in trials:
        song_path = songs_dir / entry["song"]
        binding_path = songs_dir / entry["binding"]
        if not song_path.is_file():
            raise Stage10AError(f"song missing: {song_path}")
        if not binding_path.is_file():
            raise Stage10AError(f"binding missing: {binding_path}")
        declared = dict(load_profile_binding(binding_path).instruments)
        recorded = dict(entry["bound_profiles"])
        if declared != recorded:
            raise Stage10AError(
                f"{binding_path.name} no longer matches the Stage 9C manifest for "
                f"{entry['trial_id']}: the manifest says {recorded}, the file says {declared}. The "
                "old binding must be the one the listener heard"
            )
        plans.append(
            SongPlan(
                trial_id=entry["trial_id"],
                song=entry["song"],
                song_path=song_path,
                old_binding_path=binding_path,
                old_profiles=recorded,
                stage9c_entry=entry,
            )
        )
    return plans, manifest


def load_song(path: Path) -> Any:
    """Parse a song document the way the Composer does."""
    if path.suffix == ".dsl":
        return load_composition_dsl(path)
    return load_composition_json(path)


def song_digest(path: Path) -> str:
    """The hash that proves a composition document was not touched."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


# ===========================================================================
# The human evidence
# ===========================================================================
@dataclass(frozen=True)
class Evidence:
    """What the listener said about one profile, and the machine facts that frame it."""

    profile_id: str
    sample_id: str
    status: str
    scope: str
    generator_family: str
    audctl_mode: str
    audio_group: Optional[int]
    usefulness: Optional[float]
    distinctiveness: Optional[float]
    character: Optional[float]
    confidence: Optional[float]
    comment: str
    tags: Tuple[str, ...]
    candidate_class: str
    blocking_codes: Tuple[str, ...]
    used_in_song_trial: Optional[str]

    @property
    def has_ratings(self) -> bool:
        return None not in (self.usefulness, self.distinctiveness, self.character)

    @property
    def artefact(self) -> bool:
        return TAG_ARTEFACT in self.tags

    @property
    def pool(self) -> str:
        """The generator-family pool this profile belongs to, as the old strategy saw it."""
        for name, label, _why in SELECTION_POOLS:
            if name in (f"{self.scope}/{self.generator_family}", self.scope):
                return label
        return "no pool recorded"


def load_human_evidence(reports_dir: Path) -> Dict[str, Evidence]:
    """Stage 9D's per-profile scores — the only source of human ratings used here.

    Nothing is re-rated, interpolated or inferred, and a profile the listener did not rate simply
    has no evidence and can never be selected.
    """
    path = reports_dir / "profile_scores.json"
    if not path.is_file():
        raise Stage10AError(
            f"the Stage 9D analysis is not present ({path}); this experiment is defined by the "
            "human listening evidence it produced"
        )
    payload = json.loads(path.read_text(encoding="utf-8"))
    table: Dict[str, Evidence] = {}
    for row in payload["profiles"]:
        human = row["human"]
        machine = row["machine"]
        table[row["profile_id"]] = Evidence(
            profile_id=row["profile_id"],
            sample_id=row["sample_id"],
            status=row["status"],
            scope=machine["scope"],
            generator_family=machine["generator_family"],
            audctl_mode=machine["audctl_mode"],
            audio_group=row["audio_group"],
            usefulness=human["usefulness"],
            distinctiveness=human["distinctiveness"],
            character=human["character"],
            confidence=human["confidence"],
            comment=human["comment"] or "",
            tags=tuple(human.get("comment_categories") or ()),
            candidate_class=row.get("candidate_class") or "",
            blocking_codes=tuple(machine.get("blocking_codes") or ()),
            used_in_song_trial=machine.get("used_in_song_trial"),
        )
    return table


def role_class(instrument_id: str, instrument_name: str) -> str:
    """PITCHED or UNPITCHED, from the instrument the composition itself declares."""
    haystack = f"{instrument_id} {instrument_name}".lower()
    return "UNPITCHED" if any(word in haystack for word in UNPITCHED_WORDS) else "PITCHED"


def role_tag(role: str) -> str:
    """The listener tag a profile must carry to be considered for *role*."""
    return TAG_PERCUSSIVE if role == "UNPITCHED" else TAG_TONAL


# ===========================================================================
# Channels: one profile per channel
# ===========================================================================
@dataclass
class ChannelGroup:
    """The instruments that share one POKEY channel, and so one profile."""

    channel: int
    keys: Tuple[str, ...]
    names: Tuple[str, ...]
    roles: Tuple[str, ...]
    old_profile: str

    @property
    def pitched(self) -> bool:
        """A channel serves a pitched role unless every role on it is unpitched."""
        return any(role == "PITCHED" for role in self.roles)

    @property
    def mixed(self) -> bool:
        """True when one channel carries both a pitched and an unpitched role."""
        return len(set(self.roles)) > 1


def channel_groups(ir_song: IRSong, document: Any, binding_keys: Sequence[str]) -> List[ChannelGroup]:
    """Group a binding's instruments by the channel they sound on.

    Stage 9C's bindings already obey this (which is why ``dziki2.json`` binds one profile to three
    instruments on channel 4); the rule is made explicit because the new assignment must obey it
    too, and because two roles sharing a channel cannot be given two different generators.
    """
    names = {inst.id: inst.name for inst in ir_song.instruments}
    occupied: Dict[int, List[str]] = {}
    for key in binding_keys:
        targets = _resolve_targets(ir_song, key, document)
        if not targets:
            raise Stage10AError(f"{key!r} names no instrument of the composition")
        for channel in _instrument_channels(ir_song, targets[0]) or (0,):
            occupied.setdefault(channel, []).append(key)

    groups: List[ChannelGroup] = []
    for channel, keys in sorted(occupied.items()):
        ordered = tuple(key for key in binding_keys if key in keys)
        groups.append(
            ChannelGroup(
                channel=channel,
                keys=ordered,
                names=tuple(names.get(key, key) for key in ordered),
                roles=tuple(role_class(key, names.get(key, "")) for key in ordered),
                old_profile="",
            )
        )
    return groups


# ===========================================================================
# Candidate selection
# ===========================================================================
def try_binding(
    result: Any, document: Any, bank: SoundProfileBank, instruments: Mapping[str, str]
) -> Tuple[bool, str]:
    """Apply a partial binding and report whether it applies, and why not if it does not.

    No exception escapes: a refusal is data here, because which candidates are *possible* is itself a
    measurement this stage reports rather than an opinion it forms.
    """
    binding = load_profile_binding(
        {"schema": "atari-music/sound-profile-binding/1", "instruments": dict(instruments)}
    )
    try:
        apply_profile_binding(result, binding, bank, composition=document)
    except SoundProfileError as error:
        return False, str(getattr(error, "code", "") or type(error).__name__)
    except Exception as error:  # pragma: no cover - defensive
        return False, type(error).__name__
    return True, ""


def _audio_distinct(old: Evidence, candidate: Evidence) -> bool:
    """Would binding *candidate* change the sound the song makes?

    Two profiles whose Stage 9C stimulus audio is byte-identical write the same six IR values, so they
    must render the same song. Substituting one for the other is not an experiment.
    """
    return audio_key(candidate) != audio_key(old)


def audio_key(item: Evidence) -> str:
    """The identity of the *sound*, not of the document.

    ``audio_group`` is Stage 9D's index over profiles whose rendered stimulus audio is byte-identical;
    ``None`` means the profile sounds like nothing else in the library. Two profiles with the same key
    are the same sound in any song, so a programme that gives two channels the same key has given them
    one timbre.
    """
    return f"group:{item.audio_group}" if item.audio_group is not None else f"unique:{item.profile_id}"


def replacement_rule(old: Evidence, candidate: Evidence) -> Tuple[str, str]:
    """Whether the listener's own ratings justify this replacement, and the sentence saying why.

    Three conditions, in order, and no others:

    1. **floor** — the candidate must be rated at least neutral on Atari character, because a sound
       the listener heard as *not* Atari-like cannot be the improvement in an Atari composition;
    2. **no regression** — the candidate must be rated no lower than the old profile on usefulness,
       distinctiveness and Atari character. Nothing is traded: in particular distinctiveness is never
       bought with character, because the listener's own scales put those two in opposition
       (Spearman −0.57 over the library);
    3. **a clear gain** — either one scale improves by ``MARGIN`` (2) or more, which is outside the
       disagreement the listener showed against themselves on byte-identical sounds, or two scales
       improve together. A single one-point gain is not evidence.
    """
    if not candidate.has_ratings:
        return "", "the listener did not rate this profile, so it carries no evidence"
    if not old.has_ratings:
        return "", "the listener did not rate the profile being replaced"

    use, dis, char = candidate.usefulness, candidate.distinctiveness, candidate.character
    o_use, o_dis, o_char = old.usefulness, old.distinctiveness, old.character
    assert use is not None and dis is not None and char is not None
    assert o_use is not None and o_dis is not None and o_char is not None

    if char < CHARACTER_FLOOR:
        return "", (
            f"the listener rated its Atari character {char:g}, below the floor of "
            f"{CHARACTER_FLOOR:g}: it does not feel like a useful POKEY sound"
        )

    deltas = OrderedDict(
        (
            ("usefulness", use - o_use),
            ("distinctiveness", dis - o_dis),
            ("atari_character", char - o_char),
        )
    )
    lower = [name for name, delta in deltas.items() if delta < 0]
    if lower:
        return "", (
            "it is rated lower than the profile it would replace on "
            + ", ".join(lower)
            + ", and distinctiveness and Atari character oppose each other in the listener's own "
            f"ratings ({DISTINCTIVENESS_CHARACTER_RHO:+.2f}), so a trade like this is not an "
            "improvement to make on evidence"
        )

    gains = OrderedDict((name, delta) for name, delta in deltas.items() if delta > 0)
    if not gains:
        return "", (
            "the listener rated it identically to the profile it would replace, so it would change "
            "the sound without improving anything"
        )
    described = " and ".join(
        f"{name} {_rating(name, old):g} -> {_rating(name, candidate):g}" for name in gains
    )
    if max(deltas.values()) >= MARGIN:
        return RULE_MARGIN, (
            f"{described}: a gain of {max(gains.values()):g}, at the threshold the listener's own "
            "repeatability requires, with no rating lower"
        )
    if len(gains) >= 2:
        return RULE_CONSISTENT, f"{described}: two ratings improve together with nothing lower"
    name = next(iter(gains))
    return "", (
        f"the only gain is {described}, a single one-point difference, which is inside the "
        "disagreement the listener showed against themselves on identical sounds"
    )


def _rating(name: str, item: Evidence) -> float:
    """One listener rating by name, for the sentences above."""
    value = {
        "usefulness": item.usefulness,
        "distinctiveness": item.distinctiveness,
        "atari_character": item.character,
    }[name]
    assert value is not None
    return value


@dataclass
class Candidate:
    """One plausible replacement, with everything needed to judge and to explain it."""

    profile_id: str
    evidence: Evidence
    applies: bool
    refusal_code: str
    rule: str
    reason: str

    def as_dict(self) -> Dict[str, Any]:
        return {
            "profile_id": self.profile_id,
            "scope": self.evidence.scope,
            "generator_family": self.evidence.generator_family,
            "audio_group": self.evidence.audio_group,
            "usefulness": self.evidence.usefulness,
            "distinctiveness": self.evidence.distinctiveness,
            "atari_character": self.evidence.character,
            "confidence": self.evidence.confidence,
            "comment": self.evidence.comment,
            "tags": list(self.evidence.tags),
            "status": self.evidence.status,
            "blocking_codes": list(self.evidence.blocking_codes),
            "applies": self.applies,
            "refusal_code": self.refusal_code,
            "rule": self.rule,
            "reason": self.reason,
        }


def _rank_key(candidate: Candidate) -> Tuple[Any, ...]:
    """The brief's own order: usefulness first, then Atari character, then distinctiveness.

    The profile id breaks ties so the order never depends on dictionary iteration, and a candidate
    the renderer refuses sinks to the bottom of every pool.
    """
    evidence = candidate.evidence
    return (
        not candidate.applies,
        -(evidence.usefulness or 0.0),
        -(evidence.character or 0.0),
        -(evidence.distinctiveness or 0.0),
        candidate.profile_id,
    )


def candidate_pool(
    group: ChannelGroup,
    result: Any,
    document: Any,
    bank: SoundProfileBank,
    evidence: Mapping[str, Evidence],
) -> List[Candidate]:
    """Every plausible replacement for one channel group, with its measured compatibility.

    Plausible means: the same scope as the old profile, heard by the listener the way the role needs,
    rated, renderable, with no blocking limitation, and audibly distinct from the old profile.
    Compatible means ``apply_profile_binding`` accepts it — which is why every candidate is *applied*
    rather than discussed.
    """
    old = evidence[group.old_profile]
    wanted = role_tag("PITCHED" if group.pitched else "UNPITCHED")
    pool: List[Candidate] = []
    for profile_id, candidate in evidence.items():
        if candidate.scope != old.scope:
            continue
        if wanted not in candidate.tags:
            continue
        if not candidate.has_ratings:
            continue
        if candidate.blocking_codes:
            continue
        if not _audio_distinct(old, candidate):
            continue
        applies, code = try_binding(result, document, bank, {key: profile_id for key in group.keys})
        rule, reason = replacement_rule(old, candidate)
        if not applies:
            rule, reason = "", f"the binding layer refuses it ({code})"
        pool.append(
            Candidate(
                profile_id=profile_id,
                evidence=candidate,
                applies=applies,
                refusal_code=code,
                rule=rule,
                reason=reason,
            )
        )
    pool.sort(key=_rank_key)
    return pool


# ===========================================================================
# Decisions
# ===========================================================================
@dataclass
class Decision:
    """One channel group's outcome: kept, or replaced, with the reason recorded."""

    song: str
    trial_id: str
    channel: int
    keys: Tuple[str, ...]
    names: Tuple[str, ...]
    roles: Tuple[str, ...]
    old_profile: str
    new_profile: str
    rule: str
    reason: str
    human_evidence: Dict[str, Any]
    technical: Dict[str, Any]
    candidates: List[Candidate] = field(default_factory=list)

    @property
    def changed(self) -> bool:
        return self.new_profile != self.old_profile

    def as_dict(self) -> Dict[str, Any]:
        return {
            "song": self.song,
            "trial_id": self.trial_id,
            "channel": self.channel,
            "instruments": list(self.keys),
            "instrument_names": list(self.names),
            "role_classes": list(self.roles),
            "old_profile": self.old_profile,
            "new_profile": self.new_profile,
            "changed": self.changed,
            "rule": self.rule,
            "reason": self.reason,
            "human_evidence": self.human_evidence,
            "technical": self.technical,
            "candidates": [candidate.as_dict() for candidate in self.candidates],
        }


def decide_group(
    song: SongPlan,
    group: ChannelGroup,
    pool: Sequence[Candidate],
    evidence: Mapping[str, Evidence],
    used: Counter,
    other_channels: frozenset,
) -> Decision:
    """Pick the replacement for one channel group, or keep the old profile.

    Eligible candidates are ordered by the brief's criteria — usefulness, then Atari character, then
    distinctiveness — and two preferences are applied before that order is read: a candidate whose
    sound another channel *of this song* already has is avoided, because giving two channels one
    timbre adds nothing; and among the rest, one no other channel of the programme has taken is
    preferred, so the six songs do not converge on a single sound. Both are experimental choices
    rather than inferences from the ratings, and each decision records whether they applied.
    """
    old = evidence[group.old_profile]
    eligible = [item for item in pool if item.applies and item.rule]
    chosen: Optional[Candidate] = None
    avoided_collision = False
    preferred_unused = False
    if eligible:
        free = [item for item in eligible if audio_key(item.evidence) not in other_channels]
        avoided_collision = bool(free)
        ranked = free or eligible
        unused = [item for item in ranked if used[audio_key(item.evidence)] == 0]
        preferred_unused = bool(unused)
        chosen = unused[0] if unused else ranked[0]

    if chosen is None:
        return Decision(
            song=song.song,
            trial_id=song.trial_id,
            channel=group.channel,
            keys=group.keys,
            names=group.names,
            roles=group.roles,
            old_profile=group.old_profile,
            new_profile=group.old_profile,
            rule="kept",
            reason=(
                "no compatible replacement is rated at least as highly as this profile on every "
                "scale the listener used, so this channel keeps the sound Stage 9C already bound"
            ),
            human_evidence={"old": _human_block(old)},
            technical=_technical_block(song, group, old, _best_refusal(pool)),
            candidates=list(pool),
        )

    used[audio_key(chosen.evidence)] += 1
    notes: List[str] = [f"adopted by the {chosen.rule} rule"]
    if avoided_collision:
        notes.append("no other channel of this song already uses this sound")
    if preferred_unused:
        notes.append("no other channel of the programme had taken it yet")
    else:
        notes.append(
            "every eligible alternative was already taken elsewhere in the programme, so this "
            "channel takes the best of them"
        )
    return Decision(
        song=song.song,
        trial_id=song.trial_id,
        channel=group.channel,
        keys=group.keys,
        names=group.names,
        roles=group.roles,
        old_profile=group.old_profile,
        new_profile=chosen.profile_id,
        rule=chosen.rule,
        reason=chosen.reason + " (" + "; ".join(notes) + ")",
        human_evidence={
            "old": _human_block(old),
            "new": _human_block(chosen.evidence),
            "rule": chosen.rule,
            "preferred_unused_candidate": preferred_unused,
            "avoided_same_song_sound": avoided_collision,
        },
        technical=_technical_block(song, group, chosen.evidence, ""),
        candidates=list(pool),
    )


def _best_refusal(pool: Sequence[Candidate]) -> str:
    """The most informative refusal among the candidates that could not be applied."""
    refused = [item for item in pool if not item.applies]
    if not refused:
        return ""
    code, count = Counter(item.refusal_code for item in refused).most_common(1)[0]
    return f"{count} of {len(pool)} candidates were refused, most often {code}"


def _human_block(item: Evidence) -> Dict[str, Any]:
    return {
        "usefulness": item.usefulness,
        "distinctiveness": item.distinctiveness,
        "atari_character": item.character,
        "confidence": item.confidence,
        "comment": item.comment,
        "tags": list(item.tags),
    }


def _technical_block(
    song: SongPlan, group: ChannelGroup, item: Evidence, refusal: str
) -> Dict[str, Any]:
    block: Dict[str, Any] = {
        "scope": item.scope,
        "generator_family": item.generator_family,
        "audctl_mode": item.audctl_mode,
        "status": item.status,
        "pool": item.pool,
        "channel": group.channel,
        "instruments_sharing_the_channel": list(group.keys),
        "source_binding": song.old_binding_path.name,
    }
    if refusal:
        block["refusals"] = refusal
    return block


@dataclass
class RebindingPlan:
    """The experiment's whole profile assignment, song by song."""

    decisions: List[Decision]
    used: Counter

    @property
    def changed(self) -> List[Decision]:
        return [decision for decision in self.decisions if decision.changed]

    def binding_for(self, song: SongPlan) -> Dict[str, str]:
        """The new binding's ``instruments`` map for one song."""
        binding = dict(song.old_profiles)
        for decision in self.decisions:
            if decision.trial_id != song.trial_id:
                continue
            for key in decision.keys:
                binding[key] = decision.new_profile
        return binding

    def as_dict(self) -> Dict[str, Any]:
        return {
            "analysis_version": ANALYSIS_VERSION,
            "rule": {
                "floor": (
                    f"the candidate must be rated at least {CHARACTER_FLOOR:g} on Atari character: a "
                    "sound the listener heard as not Atari-like cannot be the improvement"
                ),
                "no_regression": (
                    "the candidate must be rated no lower than the old profile on usefulness, "
                    "distinctiveness and Atari character - nothing is traded"
                ),
                RULE_MARGIN: f"one rating improves by >= {MARGIN:g} with nothing lower",
                RULE_CONSISTENT: "two ratings improve together with nothing lower",
                "kept": "no compatible candidate satisfied all three conditions",
                "distinctiveness_is_not_a_criterion": (
                    "distinctiveness and Atari character oppose each other in the listener's own "
                    f"ratings (Spearman {DISTINCTIVENESS_CHARACTER_RHO:+.2f}, n=60), so "
                    "distinctiveness never justifies a replacement on its own"
                ),
            },
            "decisions": [decision.as_dict() for decision in self.decisions],
            "changed_channels": len(self.changed),
            "changed_roles": sum(len(decision.keys) for decision in self.changed),
            "songs_changed": sorted({decision.song for decision in self.changed}),
            "songs_unchanged": sorted(
                {decision.song for decision in self.decisions if not decision.changed}
                - {decision.song for decision in self.changed}
            ),
            "profiles_used_more_than_once": {
                profile_id: count for profile_id, count in sorted(self.used.items()) if count > 1
            },
        }


def build_plan(
    songs: Sequence[SongPlan], bank: SoundProfileBank, evidence: Mapping[str, Evidence]
) -> Tuple[RebindingPlan, Dict[str, Any]]:
    """Decide every channel group, in programme order, on the human evidence alone."""
    used: Counter = Counter()
    decisions: List[Decision] = []
    contexts: Dict[str, Dict[str, Any]] = {}
    for song in songs:
        document = load_song(song.song_path)
        result = generate_music_from_composition(document)
        contexts[song.trial_id] = {"document": document, "result": result}
        groups = channel_groups(result.pokey_ir, document, list(song.old_profiles))
        covered = {key for group in groups for key in group.keys}
        missing = set(song.old_profiles) - covered
        if missing:
            raise Stage10AError(
                f"{song.song}: {sorted(missing)} are bound but sound on no channel, so the "
                "rebinding cannot leave them unbound and still claim one profile per channel"
            )
        song_sounds = {audio_key(evidence[profile]) for profile in song.old_profiles.values()}
        for group in groups:
            group.old_profile = song.old_profiles[group.keys[0]]
            others = {song.old_profiles[key] for key in group.keys}
            if len(others) != 1:
                raise Stage10AError(
                    f"{song.song} binds different profiles to instruments sharing channel "
                    f"{group.channel} ({sorted(others)}); one POKEY channel carries one generator"
                )
            pool = candidate_pool(group, result, document, bank, evidence)
            decisions.append(
                decide_group(
                    song,
                    group,
                    pool,
                    evidence,
                    used,
                    frozenset(song_sounds - {audio_key(evidence[group.old_profile])}),
                )
            )
            song_sounds.discard(audio_key(evidence[group.old_profile]))
            song_sounds.add(audio_key(evidence[decisions[-1].new_profile]))
    return RebindingPlan(decisions=decisions, used=used), contexts


# ===========================================================================
# Rendering
# ===========================================================================
@dataclass
class Render:
    """One version of one song: the audio the listener may hear, and how it got its level."""

    kind: str
    samples: np.ndarray
    frames: np.ndarray
    audctl: int
    clipped: int
    features: Dict[str, float]

    @property
    def frames_sha256(self) -> str:
        return hashlib.sha256(np.ascontiguousarray(self.frames).tobytes()).hexdigest()

    @property
    def audio_sha256(self) -> str:
        return hashlib.sha256(self.samples.tobytes()).hexdigest()


def bound_result(
    document: Any, bank: Optional[SoundProfileBank], binding: Optional[Mapping[str, str]]
) -> Any:
    """The generation result for one version: the composer's own, or the one a binding realizes."""
    result = generate_music_from_composition(document)
    if binding is None:
        return result
    if bank is None:  # pragma: no cover - defensive
        raise Stage10AError("a binding needs the bank it refers to")
    return apply_profile_binding(
        result,
        load_profile_binding(
            {"schema": "atari-music/sound-profile-binding/1", "instruments": dict(binding)}
        ),
        bank,
        composition=document,
    )


def render_version(
    document: Any,
    bank: Optional[SoundProfileBank],
    binding: Optional[Mapping[str, str]],
    *,
    kind: str,
    gain: float,
    limit: int,
) -> Render:
    """Render one version and apply the song's *shared* gain.

    The gain is not decided here: it comes from the default render's excerpt peak, exactly as in
    Stage 9C, and is applied to all three versions of the song. That is what keeps a real loudness
    difference between the versions audible instead of normalizing it away, and it is why the level is
    never matched per side.
    """
    result = bound_result(document, bank, binding)
    frames = compile_ir_to_pokey_frames(result.pokey_ir)
    samples = render_pokey_samples(frames, SAMPLE_RATE, 50.0)
    scaled = samples[:limit].astype(np.float64) * gain
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


def shared_gain(default_samples: np.ndarray, limit: int) -> float:
    """The one gain a song's three versions share, derived from the default render."""
    peak = float(np.max(np.abs(default_samples[:limit].astype(np.float64)))) / 32768.0
    return TARGET_PEAK / peak if peak > 0.0 else 1.0


def _dbfs(amplitude: float) -> float:
    return 20.0 * math.log10(amplitude) if amplitude > 0 else -120.0


def _level_of(render: Render) -> Dict[str, float]:
    """The level and spectrum of one version, so the report can print all three side by side."""
    audio = render.samples.astype(np.float64) / 32768.0
    peak = float(np.max(np.abs(audio))) if audio.size else 0.0
    rms = float(np.sqrt(np.mean(audio**2))) if audio.size else 0.0
    return {
        "peak_dbfs": round(_dbfs(peak), 3),
        "rms_dbfs": round(_dbfs(rms), 3),
        "centroid_hz": round(render.features["centroid_hz"], 3),
        "bandwidth_hz": round(render.features["bandwidth_hz"], 3),
        "flatness": round(render.features["flatness"], 6),
    }


# ===========================================================================
# Machine comparison
# ===========================================================================
def frame_differences(frames: Mapping[str, np.ndarray]) -> Dict[str, Any]:
    """Per-column register differences between two versions — reported, never interpreted.

    Columns are named by :data:`atari_music.ir.FRAME_COLUMN_NAMES`; the row is interleaved as
    ``AUDF1, AUDC1, AUDF2, AUDC2, …``, so column order is not the AUDF block followed by the AUDC
    block.

    A differing AUDF column means the versions place the same notes at different dividers, which is a
    consequence of the profile's clock rather than of the music, and §7 of the report says so.
    """
    columns = FRAME_COLUMN_NAMES
    out: Dict[str, Any] = {}
    for left, right in (("default", "old"), ("default", "new"), ("old", "new")):
        a, b = frames[left], frames[right]
        rows = min(a.shape[0], b.shape[0])
        per_column = {
            name: int(np.count_nonzero(a[:rows, index] != b[:rows, index]))
            for index, name in enumerate(columns)
        }
        out[f"{left}_vs_{right}"] = {
            "identical": bool(a.shape == b.shape and np.array_equal(a, b)),
            "frames_differing": int(np.count_nonzero((a[:rows] != b[:rows]).any(axis=1))),
            "frames_compared": rows,
            "columns_differing": {name: count for name, count in per_column.items() if count},
            "audctl": {
                "left": int(a[0, 8]) if a.shape[0] else None,
                "right": int(b[0, 8]) if b.shape[0] else None,
            },
            "left": left,
            "right": right,
        }
    return out


def compare_renders(left: Render, right: Render, shared_gain_db: float) -> Dict[str, Any]:
    """Everything §12 of the brief asks to measure between two versions of one song."""
    peak = {
        kind: float(np.max(np.abs(render.samples.astype(np.float64)))) / 32768.0
        for kind, render in ((left.kind, left), (right.kind, right))
    }
    rms = {
        kind: float(np.sqrt(np.mean((render.samples.astype(np.float64) / 32768.0) ** 2)))
        for kind, render in ((left.kind, left), (right.kind, right))
    }
    return {
        "audio_identical": bool(left.samples.tobytes() == right.samples.tobytes()),
        "sha256": {left.kind: left.audio_sha256, right.kind: right.audio_sha256},
        "frames_identical": left.frames_sha256 == right.frames_sha256,
        "left": left.kind,
        "right": right.kind,
        "audctl": {"left": left.audctl, "right": right.audctl},
        "shared_gain_db": round(shared_gain_db, 4),
        "peak_dbfs": {kind: round(_dbfs(value), 3) for kind, value in peak.items()},
        "peak_delta_db": round(_dbfs(peak[right.kind]) - _dbfs(peak[left.kind]), 3),
        "rms_dbfs": {kind: round(_dbfs(value), 3) for kind, value in rms.items()},
        "rms_delta_db": round(_dbfs(rms[right.kind]) - _dbfs(rms[left.kind]), 3),
        "duration_seconds": round(len(left.samples) / SAMPLE_RATE, 4),
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
        "spectral_distance": round(spectral_distance(left.features, right.features), 6),
    }


# ===========================================================================
# The blinded programme
# ===========================================================================
@dataclass(frozen=True)
class Trial:
    """One blinded pair: two versions of one song under two neutral labels."""

    trial_id: str
    song_trial_id: str
    song: str
    trial_kind: str
    a: str
    b: str

    @property
    def sides(self) -> Dict[str, str]:
        """Which version is behind each neutral label. ``a`` and ``b`` already hold the versions."""
        return {"a": self.a, "b": self.b}

    @property
    def compared(self) -> Dict[str, str]:
        left, right = TRIAL_KIND_LOOKUP[self.trial_kind]
        return {"left": left, "right": right}

    @property
    def caption(self) -> str:
        """What the interface says about the pair: never more than 'two versions of one piece'.

        The three kinds are worded identically on purpose. A caption that distinguished "the
        composer's own instruments" from "the library" would tell the listener which side to
        prefer, which is exactly what Stage 9C was built to avoid.
        """
        return "Two versions of the same piece of music."

    def side_file(self, side: str) -> str:
        return f"audio/{self.trial_id}_{side}.wav"

    def as_dict(self) -> Dict[str, Any]:
        return {
            "trial_id": self.trial_id,
            "song": self.song,
            "song_trial_id": self.song_trial_id,
            "trial_kind": self.trial_kind,
            "compared": self.compared,
            "sides": self.sides,
            "files": {side: self.side_file(side) for side in ("a", "b")},
        }


def build_trials(songs: Sequence[SongPlan], rng: random.Random) -> List[Trial]:
    """The blinded pairs: default-vs-new, old-vs-new, and the default-vs-old control.

    Each song contributes all three, in an order the seed shuffles, so the listener never learns which
    comparison is which. The orientation of every pair is randomized too, and nothing about the
    mapping reaches the interface: the two sides are ``a`` and ``b``, and only the package's manifest
    holds the key.
    """
    trials: List[Trial] = []
    for song in songs:
        order = list(TRIAL_KINDS)
        rng.shuffle(order)
        for index, (kind, left, right) in enumerate(order, start=1):
            a, b = (left, right) if rng.random() < 0.5 else (right, left)
            trials.append(
                Trial(
                    trial_id=f"{song.trial_id}_t{index}",
                    song_trial_id=song.trial_id,
                    song=song.song,
                    trial_kind=kind,
                    a=a,
                    b=b,
                )
            )
    return trials


# ===========================================================================
# The stage as a whole
# ===========================================================================
def build_package(
    package_dir: Path = DEFAULT_PACKAGE_DIR,
    *,
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
    """Prepare the whole experiment: bindings, renders, machine comparison, blinded package.

    Read-only with respect to everything it is about. The bank, the six songs, the Stage 9C package
    and the Stage 9D analysis are inputs; no profile is edited, renamed or removed and no production
    module is touched.
    """
    say = log or (lambda message: None)
    package_dir = Path(package_dir)
    stage9c_package = Path(stage9c_package)
    songs_dir = Path(songs_dir)
    bank_dir = Path(bank_dir)
    bank = load_sound_profile_bank(bank_dir)
    evidence = load_human_evidence(Path(reports_dir))

    say("Recovering the six Stage 9C Part C songs…")
    songs, stage9c = recover_songs(stage9c_package, songs_dir)
    before = _input_state(songs, stage9c_package)

    say("Deciding each channel from the human evidence…")
    plan, contexts = build_plan(songs, bank, evidence)
    for song in songs:
        binding = plan.binding_for(song)
        applies, code = try_binding(
            contexts[song.trial_id]["result"], contexts[song.trial_id]["document"], bank, binding
        )
        if not applies:
            raise Stage10AError(
                f"the new binding for {song.song} does not apply as a whole ({code}); the "
                "experiment must not ship a binding the renderer refuses"
            )

    say("Rendering DEFAULT, OLD and NEW for every song…")
    limit = int(round(SONG_EXCERPT_SECONDS * SAMPLE_RATE))
    audio_dir = package_dir / "audio"
    binding_dir = package_dir / "bindings"
    audio_dir.mkdir(parents=True, exist_ok=True)
    binding_dir.mkdir(parents=True, exist_ok=True)

    song_records: List[Dict[str, Any]] = []
    comparison: Dict[str, Any] = {}
    verified: Dict[str, Any] = {}
    for song in songs:
        document = contexts[song.trial_id]["document"]
        binding = plan.binding_for(song)
        _write_binding(binding_dir / f"{song.song}.binding.json", bank_dir, binding)

        default_samples = render_pokey_samples(
            compile_ir_to_pokey_frames(
                bound_result(document, None, None).pokey_ir
            ),
            SAMPLE_RATE,
            50.0,
        )
        gain = shared_gain(default_samples, limit)
        gain_db = _dbfs(gain)
        versions = {
            "default": render_version(document, None, None, kind="default", gain=gain, limit=limit),
            "old": render_version(
                document, bank, song.old_profiles, kind="old", gain=gain, limit=limit
            ),
            "new": render_version(document, bank, binding, kind="new", gain=gain, limit=limit),
        }
        verified[song.trial_id] = _verify_against_stage9c(song, versions, stage9c_package)
        for kind, render in versions.items():
            write_wav(audio_dir / f"{song.trial_id}_{kind}.wav", render.samples, SAMPLE_RATE)

        comparison[song.trial_id] = {
            "song": song.song,
            "shared_gain_db": round(gain_db, 4),
            "old_binding": song.old_binding_path.name,
            "new_binding": f"bindings/{song.song}.binding.json",
            "old_profiles": dict(song.old_profiles),
            "new_profiles": dict(binding),
            "clipped_samples": {kind: render.clipped for kind, render in versions.items()},
            "full_samples": {kind: int(render.frames.shape[0]) for kind, render in versions.items()},
            "levels": {kind: _level_of(render) for kind, render in versions.items()},
            "sha256": {kind: render.audio_sha256 for kind, render in versions.items()},
            "duration_seconds": round(limit / SAMPLE_RATE, 4),
            "default_vs_old": compare_renders(versions["default"], versions["old"], gain_db),
            "default_vs_new": compare_renders(versions["default"], versions["new"], gain_db),
            "old_vs_new": compare_renders(versions["old"], versions["new"], gain_db),
            "register_frames": frame_differences(
                {
                    "default": versions["default"].frames,
                    "old": versions["old"].frames,
                    "new": versions["new"].frames,
                }
            ),
        }
        song_records.append(
            {
                "trial_id": song.trial_id,
                "song": song.song,
                "old_binding": song.old_binding_path.name,
                "new_binding": f"bindings/{song.song}.binding.json",
                "old_profiles": dict(song.old_profiles),
                "new_profiles": dict(binding),
                "excerpt_seconds": round(limit / SAMPLE_RATE, 3),
                "shared_gain_db": round(gain_db, 4),
                "files": {
                    kind: f"audio/{song.trial_id}_{kind}.wav" for kind in ("default", "old", "new")
                },
            }
        )
        say(f"  {song.trial_id} {song.song}: {len(binding)} instruments rendered")

    trials = build_trials(songs, random.Random(seed))
    for trial in trials:
        for side, kind in trial.sides.items():
            write_wav(
                audio_dir / f"{trial.trial_id}_{side}.wav",
                _read_pcm(audio_dir / f"{trial.song_trial_id}_{kind}.wav"),
                SAMPLE_RATE,
            )

    after = _input_state(songs, stage9c_package)
    if before != after:
        raise Stage10AError(
            "a read-only input changed while the experiment was being prepared; the experiment must "
            "not modify the Stage 9C package, the compositions or the old bindings"
        )

    created = now or datetime.now(timezone.utc)
    manifest: Dict[str, Any] = {
        "manifest_version": MANIFEST_VERSION,
        "experiment": EXPERIMENT,
        "private": True,
        "warning": (
            "This file is the private answer key: it maps blinded sides to versions. Do not open it "
            "while listening."
        ),
        "created_utc": created.isoformat(),
        "seed": seed,
        "sample_rate": SAMPLE_RATE,
        "excerpt_seconds": round(limit / SAMPLE_RATE, 3),
        "source_package": str(stage9c_package),
        "source_package_manifest_sha256": before["stage9c_manifest"],
        "profile_bank": str(bank_dir),
        "human_evidence": str(Path(reports_dir) / "profile_scores.json"),
        "normalization": {
            "method": "peak",
            "gain_only": True,
            "target_peak_linear": TARGET_PEAK,
            "clipping": "none (gain chosen so the peak equals the target)",
            "notes": (
                "One gain per song, derived from the default render's excerpt peak and applied to "
                "all three versions, exactly as in Stage 9C. No compression, no EQ and no per-side "
                "level matching, so a real loudness difference between the versions is preserved."
            ),
        },
        "limitations": [
            {
                "code": "GESTURE_NOT_RENDERED",
                "detail": (
                    "the player has no per-channel macro, so a profile is heard as a static tone "
                    "shaped by its generator, clock and envelope. Stage 9E measured what that "
                    "discards; nothing here changes it."
                ),
            },
            {
                "code": "ONE_PROFILE_PER_CHANNEL",
                "detail": (
                    "a POKEY channel carries one generator, so instruments sharing a channel share "
                    "a profile. Where a channel carries both pitched and percussive roles no "
                    "assignment can satisfy both."
                ),
            },
            {
                "code": "RATINGS_CAME_FROM_ONE_PHRASE",
                "detail": (
                    "the ratings were given for isolated profiles playing one bright-lead phrase, "
                    "so they speak to character in that context, not to how a profile behaves "
                    "inside a particular arrangement."
                ),
            },
            {
                "code": "THE_SAME_SONG_APPEARS_THREE_TIMES",
                "detail": (
                    "each song contributes three pairs, so the listener may recognize it and anchor "
                    "on an earlier answer; the order and the orientations are randomized to limit "
                    "the effect."
                ),
            },
        ],
        "songs": song_records,
        "trials": [trial.as_dict() for trial in trials],
        "profile_assignments": plan.as_dict(),
        "changed_assignments": len(plan.changed),
    }

    (package_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    _write_answer_template(package_dir, trials)
    (package_dir / "index.html").write_text(render_index_html(manifest), encoding="utf-8")
    (package_dir / "README.md").write_text(render_readme(manifest), encoding="utf-8")

    bundle: Dict[str, Any] = {
        "manifest": manifest,
        "songs": songs,
        "song_records": [_song_record(song, contexts, evidence) for song in songs],
        "plan": plan,
        "comparison": comparison,
        "trials": trials,
        "verification": {
            "analysis_version": ANALYSIS_VERSION,
            "stage9c_default_and_old_byte_identical": {
                trial_id: record["byte_identical"] for trial_id, record in verified.items()
            },
            "stage9c_bytes_compared": {
                trial_id: record["bytes_compared"] for trial_id, record in verified.items()
            },
            "compositions_unchanged": before["compositions"] == after["compositions"],
            "old_bindings_unchanged": before["old_bindings"] == after["old_bindings"],
            "stage9c_package_unchanged": (
                before["stage9c_manifest"] == after["stage9c_manifest"]
                and before["stage9c_audio"] == after["stage9c_audio"]
            ),
            "new_bindings_apply_whole": sorted(
                f"bindings/{song.song}.binding.json" for song in songs
            ),
            "source_hashes": after,
        },
    }

    written: Dict[str, Path] = {
        "manifest": package_dir / "manifest.json",
        "index": package_dir / "index.html",
        "readme": package_dir / "README.md",
        "answers": package_dir / "evaluation_rebinding_10a.csv",
    }
    if analysis_dir is not None:
        analysis_dir = Path(analysis_dir)
        analysis_dir.mkdir(parents=True, exist_ok=True)
        for name, payload in (
            ("songs.json", {"analysis_version": ANALYSIS_VERSION, "songs": bundle["song_records"]}),
            ("rebinding.json", plan.as_dict()),
            ("machine_comparison.json", comparison),
            ("verification.json", bundle["verification"]),
        ):
            path = analysis_dir / name
            path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            written[name] = path
    if docs_dir is not None:
        docs_dir = Path(docs_dir)
        docs_dir.mkdir(parents=True, exist_ok=True)
        path = docs_dir / "stage10a_rebinding_experiment.md"
        path.write_text(render_report(bundle), encoding="utf-8")
        written["report"] = path

    for name, path in written.items():
        say(f"  wrote {name}: {path}")
    bundle["written"] = written
    return bundle


def _input_state(songs: Sequence[SongPlan], stage9c_package: Path) -> Dict[str, Any]:
    """Digests of every read-only input, so "nothing changed" is a measurement."""
    return {
        "stage9c_manifest": hashlib.sha256(
            (stage9c_package / "manifest.json").read_bytes()
        ).hexdigest(),
        "stage9c_audio": _dir_digest(stage9c_package / "audio"),
        "compositions": {song.song: song_digest(song.song_path) for song in songs},
        "old_bindings": {
            song.song: hashlib.sha256(song.old_binding_path.read_bytes()).hexdigest()
            for song in songs
        },
    }


def _song_record(
    song: SongPlan, contexts: Mapping[str, Any], evidence: Mapping[str, Evidence]
) -> Dict[str, Any]:
    """One row of §2/§3 of the report: the song, its roles, its channels and its old assignment."""
    document = contexts[song.trial_id]["document"]
    ir_song = contexts[song.trial_id]["result"].pokey_ir
    names = {inst.id: inst.name for inst in ir_song.instruments}
    instruments: List[Dict[str, Any]] = []
    for key, profile_id in song.old_profiles.items():
        item = evidence[profile_id]
        targets = _resolve_targets(ir_song, key, document)
        spoken = _instrument_channels(ir_song, targets[0]) if targets else ()
        instruments.append(
            {
                "instrument": key,
                "name": names.get(key, key),
                "role_class": role_class(key, names.get(key, "")),
                "channels": list(spoken),
                "old_profile": profile_id,
                "scope": item.scope,
                "generator_family": item.generator_family,
                "audctl_mode": item.audctl_mode,
                "usefulness": item.usefulness,
                "distinctiveness": item.distinctiveness,
                "atari_character": item.character,
                "comment": item.comment,
                "tags": list(item.tags),
                "audio_group": item.audio_group,
                "pool": item.pool,
                "selection_reason": _selection_reason(item),
            }
        )
    return {
        "trial_id": song.trial_id,
        "song": song.song,
        "source": song.song_path.as_posix(),
        "source_sha256": song_digest(song.song_path),
        "old_binding": song.old_binding_path.name,
        "channel_occupancy": {
            str(channel): sorted(ids)
            for channel, ids in _channels_with_notes(ir_song).items()
        },
        "instruments": instruments,
    }


def _selection_reason(item: Evidence) -> str:
    """Why the old strategy put this profile here, in the strategy's own terms."""
    for name, label, why in SELECTION_POOLS:
        if name in (f"{item.scope}/{item.generator_family}", item.scope):
            return f"{label}: {why}"
    return "no pool recorded"


def _verify_against_stage9c(
    song: SongPlan, versions: Mapping[str, Render], stage9c_package: Path
) -> Dict[str, Any]:
    """The default and old sides must be the audio the Stage 9C listener heard.

    Not a formality: had the excerpt, the gain or the old binding drifted, this comparison would not
    be comparable with the 5-0 it re-tests, and the drift would be invisible in every number the
    stage reports.
    """
    entry = song.stage9c_entry
    sides = entry["uses_profile_side"]
    record: Dict[str, Any] = {"byte_identical": {}, "bytes_compared": {}}
    for kind, key in (("default", "default"), ("old", "profile")):
        side = sides[key]
        reference = (stage9c_package / entry["files"][side]).read_bytes()[44:]
        mine = versions[kind].samples.tobytes()
        record["bytes_compared"][kind] = len(reference)
        record["byte_identical"][kind] = reference == mine
        if reference != mine:
            raise Stage10AError(
                f"{song.trial_id}: the {kind.upper()} side does not reproduce the Stage 9C stimulus "
                "byte for byte, so this experiment would not be comparable with the listening it "
                "re-tests"
            )
    return record


def _read_pcm(path: Path) -> np.ndarray:
    """The samples of a mono 16-bit WAV this module or Stage 9C wrote."""
    return np.frombuffer(path.read_bytes()[44:], dtype=np.int16)


def _dir_digest(root: Path) -> str:
    """A digest over every file under *root*, so "nothing changed" is a measurement."""
    digest = hashlib.sha256()
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        digest.update(str(path.relative_to(root)).encode("utf-8"))
        digest.update(path.read_bytes())
    return digest.hexdigest()


def _write_binding(path: Path, bank_dir: Path, instruments: Mapping[str, str]) -> None:
    """Write one new binding document, with the bank path relative to where it lands."""
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
    with (package_dir / "evaluation_rebinding_10a.csv").open(
        "w", encoding="utf-8", newline=""
    ) as handle:
        writer = csv.writer(handle)
        writer.writerow(ANSWER_HEADER)
        for trial in trials:
            writer.writerow([trial.trial_id] + [""] * (len(ANSWER_HEADER) - 1))


# ===========================================================================
# The interface and the package README
# ===========================================================================
def render_index_html(manifest: Mapping[str, Any]) -> str:
    """The listening interface: one self-contained page, no server and no Python.

    It carries two audio players per pair and neutral labels. Nothing on the page names a version, a
    profile, a generator, a scope or a song: the mapping lives only in the package's manifest.
    """
    payload = {
        "experiment": manifest["experiment"],
        "trials": [
            {
                "trial_id": trial["trial_id"],
                "a": trial["files"]["a"],
                "b": trial["files"]["b"],
            }
            for trial in manifest["trials"]
        ],
    }
    return _INDEX_HTML.replace("__PACKAGE__", json.dumps(payload, sort_keys=True))


def render_readme(manifest: Mapping[str, Any]) -> str:
    """How to listen, what is asked, and what the package contains."""
    songs = len(manifest["songs"])
    trials = len(manifest["trials"])
    per_song = trials // songs if songs else 0
    assignments = manifest["profile_assignments"]
    changed = manifest["changed_assignments"]
    songs_changed = len(assignments["songs_changed"])
    songs_kept = len(assignments["songs_unchanged"])
    return f"""# Whole-song comparison after rebinding (Stage 10A)

Two versions of the same piece of music, built from the same composition, the same notes, the same
tempo, the same channel allocation and the same renderer. Only the sound profiles differ — the sounds
the POKEY channels use.

**You need nothing installed.** Open `index.html`, listen, answer, and download the CSV at the end. If
the browser refuses to play local audio, serve the folder instead:

```bash
python -m http.server 8731 --directory examples/sound_profile_rebinding_10a
```

## What is in here

| file | what it is |
| :--- | :--- |
| `index.html` | the listening interface — **the only file you need to open** |
| `audio/` | three renders per song, and the blinded pairs the page plays |
| `bindings/` | the new profile assignment, one file per song |
| `evaluation_rebinding_10a.csv` | the empty answer template the interface fills in |
| `manifest.json` | the private answer key and the full machine record — **do not open it while listening** |

Do not inspect the `audio/` folder while listening either: the three named renders sit next to the
blinded pairs, so comparing file sizes or hashes would break the blinding.

## Method

* **{songs} songs × {per_song} pairs = {trials} comparisons.** Each song appears {per_song} times
  against a different opponent each time, so the same piece is heard from several angles without the
  listener ever being told which side is which.
* **Everything except the profile assignment is held fixed**: the composition bytes, the tempo, the
  notes, the durations, the velocities, the channel allocation, the renderer, the sample rate, the
  excerpt window and the gain.
* **One gain per song**, taken from the default render's peak and applied to all three versions,
  exactly as in the Stage 9C experiment. Nothing is compressed, EQ'd or level-matched per side, so a
  real loudness difference between the versions stays audible.
* **{changed} channels in {songs_changed} songs were reassigned**;
  {songs_kept} song{"" if songs_kept == 1 else "s"} left
  untouched. Each change is one the listener's own ratings support: the new sound is rated no lower
  than the old one on usefulness, distinctiveness and Atari character, and higher on at least one —
  by two points on a single scale, or by one point on two scales together. A single one-point gain
  was not treated as evidence. `bindings/` shows every change, and `manifest.json` records why.

## What is asked

For each pair: which version sounds **better overall**, which sounds **more convincing as Atari
music**, which has the **more interesting or appropriate sound character**, and how different the two
versions sound (1–5). A comment box is there for anything else you notice.

There are no right answers and no technical knowledge is needed. If a difference is audible to you,
that is the result; if it is not, that is also the result.
"""


_INDEX_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>POKEY whole-song comparison</title>
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
  <strong>Your ears are the instrument here.</strong> Each pair plays the same music twice. The two
  sides differ in the <em>sounds</em> the Atari channels use — the music itself is identical. Nothing
  on this page says which side is which, and there is no expected answer.
</div>
<div class="note">
  <strong>Set your volume once and leave it alone.</strong> Both sides of a pair are presented at the
  same gain, but one may still sound quieter or louder by nature — that is a property of the sound and
  it is being measured separately. Please judge character rather than loudness.
</div>
<div class="note">
  <strong>Some pairs may sound identical to you.</strong> That is a result, not a mistake: answer
  "no clear difference" and move on.
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
const STORE = "stage10a-answers-v1";
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

function choiceRow(key, field, question) {
  const current = get(key, field);
  const inputs = ["a", "b", "none"].map((value, index) => {
    const label = ["A", "B", "No clear difference"][index];
    const checked = String(current) === value ? " checked" : "";
    return `<label><input type="radio" name="${key}-${field}" value="${value}"${checked}
      onchange="set('${key}','${field}','${value}')">${label}</label>`;
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

const FIELDS = ["better_overall", "more_convincing_atari", "more_interesting_character"];
function isDone(key) {
  return FIELDS.every(field => get(key, field) !== "") && get(key, "difference_1_5") !== "";
}

document.getElementById("trials").innerHTML = PACKAGE.trials.map((trial, index) => {
  const id = trial.trial_id;
  const body = `<div class="ab">
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
  download("evaluation_rebinding_10a.csv",
    ["trial_id","better_overall","more_convincing_atari","more_interesting_character",
     "difference_1_5","comment"],
    PACKAGE.trials.map(trial => [trial.trial_id, get(trial.trial_id,"better_overall"),
      get(trial.trial_id,"more_convincing_atari"),
      get(trial.trial_id,"more_interesting_character"),
      get(trial.trial_id,"difference_1_5"), get(trial.trial_id,"comment")]));
}

refresh();
</script>
</main>
</body>
</html>
"""


# ===========================================================================
# The report
# ===========================================================================
def render_report(bundle: Mapping[str, Any]) -> str:
    """`docs/stage10a_rebinding_experiment.md`: ten sections, three kinds of statement kept apart.

    **Observed** is what the existing data says. **Inference** is what follows from it. **Experimental
    choice** is what this experiment decided to do, which nobody's evidence forces. Blurring the three
    is how a preparation stage quietly becomes a result.
    """
    manifest = bundle["manifest"]
    plan: RebindingPlan = bundle["plan"]
    comparison = bundle["comparison"]
    verification = bundle["verification"]
    songs = bundle["song_records"]
    lines: List[str] = []
    add = lines.append

    add("# Stage 10A — evidence-based profile rebinding experiment")
    add("")
    add("Can better *profile assignment* improve whole-song output, with the renderer untouched?")
    add("")
    add("| | |")
    add("| :--- | :--- |")
    add(f"| songs | **{len(songs)}** — exactly the Stage 9C Part C set |")
    add(f"| channels decided | **{len(plan.decisions)}** across the six songs |")
    add(f"| assignments changed | **{len(plan.changed)}** channels "
        f"({plan.as_dict()['changed_roles']} roles) |")
    add(f"| songs left unchanged | **{len(plan.as_dict()['songs_unchanged'])}** |")
    add(f"| blinded comparisons | **{len(bundle['trials'])}** "
        f"({len(bundle['trials']) // len(songs)} per song) |")
    add(f"| default and old sides byte-identical to Stage 9C | "
        f"**{'yes' if all(verification['stage9c_default_and_old_byte_identical'].values()) else 'NO'}** |")
    add(f"| Stage 9C package, compositions and old bindings untouched | "
        f"**{'yes' if verification['stage9c_package_unchanged'] and verification['compositions_unchanged'] and verification['old_bindings_unchanged'] else 'NO'}** |")
    add("")
    add("No profile, fingerprint, schema, WAV of the library, composition, DSL rule, player, "
        "renderer or Composer source was modified. The only thing that changed is which profile is "
        "bound to which existing instrument — and only in the new package.")
    add("")
    add("---")
    add("")

    # ----------------------------------------------------------------- 1
    add("## 1. Objective")
    add("")
    add("Stage 9C's Part C compared six songs and the profile-bound side lost **5–0** (one tie). Stage")
    add("9E then found that the bindings used there were drawn from **generator-family pools**, not from")
    add("anything the listener said, and that this is a *musical interpretation* gap rather than a")
    add("rendering defect. So the 5–0 result does not yet separate two very different readings:")
    add("")
    add("* **Reading A** — the profile mechanism itself is worse for whole songs.")
    add("* **Reading B** — the mechanism is fine, but the wrong profile was put on each role.")
    add("")
    add("This stage prepares the experiment that tells them apart. It changes nothing else:")
    add("")
    add("```text")
    add("same composition   same profiles   same renderer   same gain   same duration")
    add("                              |")
    add("                              v")
    add("                   different profile ASSIGNMENT only")
    add("```")
    add("")
    add("**What the outcome will mean** (stated before the listening, so it cannot be reinterpreted")
    add("afterwards):")
    add("")
    add("| outcome | supports | does **not** mean |")
    add("| :--- | :--- | :--- |")
    add("| the new assignment wins | Reading B: the 5–0 was at least partly the assignment | that the "
        "current profile *representation* is sufficient (Stage 9E's representation gap stands) |")
    add("| the new assignment does not win | Reading A for this mechanism: assignment alone is not "
        "enough | that sound profiles are useless — only that selection is not the whole problem |")
    add("| mixed | nothing yet: some roles benefit and some do not, and §9 says which | — |")
    add("")
    add("This stage does **not** test whether the Sound Profile concept is right, and it does not")
    add("attempt to improve the library, the gesture model or the player.")
    add("")

    # ----------------------------------------------------------------- 2
    add("## 2. The six songs")
    add("")
    add("**Observed.** Taken from `examples/sound_profile_listening/manifest.json` — the record of what")
    add("the listener actually heard — rather than from a filename convention. Each song's binding file")
    add("is re-read and must agree with that manifest profile-by-profile, or the stage refuses to run:")
    add("a binding edited since the experiment would silently change what *old* means.")
    add("")
    add("| # | song | source | old binding | instruments (role → channel) |")
    add("| ---: | :--- | :--- | :--- | :--- |")
    for index, record in enumerate(songs, start=1):
        roles = ", ".join(
            f"`{item['instrument']}` → ch {','.join(str(c) for c in item['channels']) or '?'}"
            for item in record["instruments"]
        )
        add(f"| {index} | `{record['song']}` | `{record['source']}` | `{record['old_binding']}` | {roles} |")
    add("")
    add("Every instrument sounds on exactly one channel, and no composition was touched. Their hashes")
    add("before and after the run are equal, and `reports/stage10a/verification.json` records them:")
    add("")
    add("| song | composition sha256 (first 16) |")
    add("| :--- | :--- |")
    for record in songs:
        add(f"| `{record['song']}` | `{record['source_sha256'][:16]}` |")
    add("")
    add("**Inference.** The six songs are not a population and cannot support a general claim about")
    add("profile binding. They are the same six songs the 5–0 was measured on, which is exactly what")
    add("makes a re-run comparable — and nothing more.")
    add("")

    # ----------------------------------------------------------------- 3
    add("## 3. The old binding")
    add("")
    add("**Observed.** The strategy the old bindings followed is documented in")
    add("[profile_integration.md](profile_integration.md) §13.1: a pool per *generator family* — noise")
    add("for percussion, poly4 for bass, pure tone for melody — and within a pool, a stable rotation")
    add("over the song list. The table below reads each old assignment through that strategy. The rating")
    add("columns are the Stage 9C/9D listener's own words and numbers, not a re-rating.")
    add("")
    add("| song | instrument / role | channel | old profile | pool | listener says (U / D / C) | comment |")
    add("| :--- | :--- | ---: | :--- | :--- | :--- | :--- |")
    for record in songs:
        for item in record["instruments"]:
            channels = ",".join(str(c) for c in item["channels"]) or "?"
            add(
                f"| `{record['song']}` | `{item['instrument']}` ({item['name']}) | {channels} | "
                f"`{item['old_profile']}` | {item['pool']} | "
                f"{_num(item['usefulness'])} / {_num(item['distinctiveness'])} / "
                f"{_num(item['atari_character'])} | {item['comment']!r} |"
            )
    add("")
    add("U = usefulness, D = distinctiveness, C = Atari character, each 1–5 as the listener gave them.")
    add("")
    add("**Inference.** Three things stand out, and all three are visible in the numbers above rather")
    add("than argued from theory:")
    add("")
    add("1. **The strategy did assign the right *kind* of generator.** Every percussion role got a noise")
    add("   generator and every pitched role a pitched one, so nothing here is structurally absurd.")
    add("2. **Within the pools it was indifferent to the listener.** The six songs draw on only a handful")
    add("   of distinct sounds, and they share them across roles and across songs:")
    add("")
    add("| sound (Stage 9D audio group) | bound to these roles |")
    add("| :--- | :--- |")
    for key, roles in _sound_usage(songs).items():
        add(f"| `{key}` | {roles} |")
    add("")
    shared = {
        key: roles for key, roles in _sound_usage(songs).items() if "," in roles
    }
    add(f"So **{len(_sound_usage(songs))} distinct sounds cover all "
        f"{sum(len(record['instruments']) for record in songs)} bound roles**, and the "
        f"{len(shared)} shared ones cover "
        f"{sum(len(roles.split(',')) for roles in shared.values())} of them. The library is heard")
    add("through a much smaller set of sounds than it has profiles.")
    add("")
    add("3. **The listener's ratings for the profiles actually used in songs are not the library's")
    add("   best.** The clearest cases are in §6.")
    add("")

    # ----------------------------------------------------------------- 4
    add("## 4. Candidate selection")
    add("")
    add("**Observed / method.** For every channel, the pool of plausible replacements is built by rule,")
    add("not by preference:")
    add("")
    add("* the **same scope** as the old profile (a `VOICE` channel stays `VOICE`; swapping the scope")
    add("  would change AUDCTL and the hardware configuration, which is not this experiment);")
    add("* the listener must have **heard it the way the role needs**: a pitched role accepts only")
    add("  profiles tagged `lead_tonal` (the profile followed the melody in the audition), an unpitched")
    add("  role only profiles tagged `percussive_noisy` — the listener's own vocabulary, not a")
    add("  generator table;")
    add("* it must be **rated** (an unrated profile has no evidence and is never chosen), **renderable**")
    add("  with no blocking limitation, and **audibly distinct** from the old profile — two profiles")
    add("  whose Stage 9C audio is byte-identical write the same six IR values, so swapping one for the")
    add("  other would not even be a change;")
    add("* and it must **apply**: every candidate is put through `apply_profile_binding` and any refusal")
    add("  removes it. Compatibility is measured, never assumed.")
    add("")
    add("**The decision rule.** Stage 9D measured the listener against themselves on byte-identical")
    add("pairs — usefulness ICC(1,1) 0.76, distinctiveness 0.73, Atari character 0.92 — so the rule is")
    add("built on what that noise allows:")
    add("")
    add("| condition | requirement |")
    add("| :--- | :--- |")
    add("| **floor** | Atari character ≥ 3 (the listener's neutral point). A sound they heard as *not* "
        "Atari-like cannot be the improvement in an Atari composition |")
    add("| **no regression** | rated **no lower** than the old profile on usefulness, distinctiveness "
        "and Atari character — nothing is traded |")
    add(f"| **a clear gain** | either one rating improves by ≥ {MARGIN:g} (outside the disagreement the "
        f"listener showed against themselves), or two ratings improve together |")
    add("")
    add("Anything else keeps the old profile, and a candidate that wins on none of these is not a")
    add("replacement, however much better it looks on one number.")
    add("")
    add("**Why distinctiveness is not a criterion.** *Observed:* across the whole library the")
    add(f"listener's distinctiveness and Atari-character ratings oppose each other — Spearman "
        f"**{DISTINCTIVENESS_CHARACTER_RHO:+.2f}** (n=60) — and usefulness tracks character "
        "(+0.57) while it *anti*-tracks distinctiveness (−0.24). *Inference:* a rule that bought")
    add("distinctiveness with character would be moving against the dimension the questionnaire asks")
    add("about, so this experiment does not do it. That is also why several channels whose old profile")
    add("is the listener's *least* distinctive (\"typical atari lead tone\", distinctiveness 1) are")
    add("**kept**: those profiles are simultaneously the most Atari-like ones in the library (character")
    add("5), and no replacement is rated at least as highly on every scale.")
    add("")
    add("**The pools, as measured.** Every candidate that reached the shortlist of its channel, with the")
    add("ratings the decision was made on. A candidate marked **ok** satisfies the three conditions;")
    add("`applies` is the renderer's answer, not a prediction:")
    add("")
    add("| song | ch | role | old | candidates considered, best first (U/D/C) |")
    add("| :--- | ---: | :--- | :--- | :--- |")
    for decision in plan.decisions:
        candidates = ", ".join(
            f"`{item.profile_id}` ({_num(item.evidence.usefulness)}/{_num(item.evidence.distinctiveness)}/"
            f"{_num(item.evidence.character)}"
            f"{' **ok**' if item.applies and item.rule else ''}"
            f"{'' if item.applies else ', refused'})"
            for item in decision.candidates[:5]
        ) or "none"
        add(
            f"| `{decision.song}` | {decision.channel} | "
            f"{' + '.join(decision.keys)} | `{decision.old_profile}` | {candidates} |"
        )
    add("")
    add("(At most five are listed per channel, best first by the rule's own order — usefulness, then")
    add("Atari character, then distinctiveness. The full pool, including every refusal and its code, is")
    add("in [rebinding.json](../reports/stage10a/rebinding.json).)")
    add("")

    # ----------------------------------------------------------------- 5
    add("## 5. The final experimental rebinding")
    add("")
    add("**Experimental choice.** What changed, and by which rule. (Deltas are the listener's own, from")
    add("Stage 9D; `kept` means nothing was rated at least as highly on every scale.)")
    add("")
    add("| song | channel | role(s) | old → new | rule |")
    add("| :--- | ---: | :--- | :--- | :--- |")
    for decision in plan.decisions:
        roles = " + ".join(f"`{key}`" for key in decision.keys)
        arrow = (
            f"`{decision.old_profile}` → `{decision.new_profile}`"
            if decision.changed
            else f"`{decision.old_profile}` (kept)"
        )
        add(f"| `{decision.song}` | {decision.channel} | {roles} | {arrow} | {decision.rule} |")
    add("")
    add("**{0} of {1} channels changed**, covering {2} roles in {3} songs:".format(
        len(plan.changed),
        len(plan.decisions),
        plan.as_dict()["changed_roles"],
        len(plan.as_dict()["songs_changed"]),
    ))
    add("")
    for song in plan.as_dict()["songs_changed"]:
        changed = [decision for decision in plan.changed if decision.song == song]
        add(f"* `{song}` — {len(changed)} channel(s):")
        for decision in changed:
            roles = " + ".join(f"`{key}`" for key in decision.keys)
            add(f"  * channel {decision.channel}: {roles} → `{decision.new_profile}`")
    add("")
    add("**Left untouched, deliberately:**")
    add("")
    for song in plan.as_dict()["songs_unchanged"]:
        kept = [decision for decision in plan.decisions if decision.song == song]
        add(f"* `{song}` — {len(kept)} channel(s):")
        for decision in kept:
            roles = " + ".join(f"`{key}`" for key in decision.keys)
            add(
                f"  * channel {decision.channel} ({roles}): keeps `{decision.old_profile}` — "
                f"{decision.reason}"
            )
    add("")
    add("A kept channel is a result, not an omission: it says the listening evidence does not justify")
    add("a better profile for that role, and inventing one would make this experiment a redesign")
    add("instead of a test.")
    add("")
    add("**How equal candidates were separated.** Where several eligible candidates tied on all three")
    add("ratings, the experiment preferred one no other channel had taken, so the six songs do not")
    add("converge on one timbre. That preference is an experimental choice, not an inference — the")
    add("ratings cannot separate those profiles — and every decision records whether it applied.")
    add("")

    # ----------------------------------------------------------------- 6
    add("## 6. Evidence for each changed assignment")
    add("")
    add("One block per changed channel, in the form the brief asks for. `human_evidence` is quoted from")
    add("Stage 9D; `technical` is what the binding layer and the composition impose.")
    add("")
    changed_any = False
    for decision in plan.changed:
        changed_any = True
        old = decision.human_evidence["old"]
        new = decision.human_evidence["new"]
        technical = decision.technical
        add(f"### `{decision.song}` — channel {decision.channel}: "
            f"{' + '.join('`' + key + '`' for key in decision.keys)}")
        add("")
        add("```text")
        add(f"song          = {decision.song}")
        add(f"instrument    = {', '.join(decision.keys)} (channel {decision.channel}, "
            f"{' + '.join(decision.roles)})")
        add(f"old_profile   = {decision.old_profile}")
        add(f"new_profile   = {decision.new_profile}")
        add("")
        add("reason:")
        add(f"  {decision.reason}.")
        add("")
        add("human_evidence:")
        add(f"  old: usefulness {_num(old['usefulness'])}, distinctiveness "
            f"{_num(old['distinctiveness'])}, Atari character {_num(old['atari_character'])}, "
            f"comment {old['comment']!r}")
        add(f"  new: usefulness {_num(new['usefulness'])}, distinctiveness "
            f"{_num(new['distinctiveness'])}, Atari character {_num(new['atari_character'])}, "
            f"comment {new['comment']!r}")
        add(f"  rule: {decision.rule}")
        add("")
        add("technical:")
        add(f"  scope {technical['scope']}, generator {technical['generator_family']}, "
            f"AUDCTL {technical['audctl_mode']}, status {technical['status']}")
        add(f"  channel {technical['channel']} carries "
            f"{', '.join(technical['instruments_sharing_the_channel'])}: one profile for the channel")
        add(f"  applies as a whole binding: yes (measured, not assumed)")
        add("```")
        add("")
    if not changed_any:
        add("No channel was changed: no candidate anywhere passed a rule.")
        add("")

    # ----------------------------------------------------------------- 7
    add("## 7. Machine-level differences")
    add("")
    add("**Observed.** Diagnostics, not a verdict. §13 of the brief is explicit that a higher spectral")
    add("distance, a wider bandwidth or a higher RMS does **not** mean a better sound, and nothing below")
    add("is used to prefer a version.")
    add("")
    add("**First, the comparability check.** The *default* and *old* sides were compared byte for byte")
    add("with the Stage 9C package's own stimuli, and the shared gain was compared with the gain that")
    add("package recorded:")
    add("")
    add("| song | gain (dB) | default identical | old identical | bytes compared |")
    add("| :--- | ---: | :--- | :--- | ---: |")
    for record in bundle["song_records"]:
        trial_id = record["trial_id"]
        record_verification = verification["stage9c_default_and_old_byte_identical"][trial_id]
        bytes_compared = verification["stage9c_bytes_compared"][trial_id]
        add(
            f"| `{record['song']}` | {comparison[trial_id]['shared_gain_db']:+.4f} | "
            f"{'yes' if record_verification['default'] else 'NO'} | "
            f"{'yes' if record_verification['old'] else 'NO'} | "
            f"{bytes_compared['default']} / {bytes_compared['old']} |"
        )
    add("")
    add("**Inference.** The comparison the listener will make is comparable with the 5–0 it re-tests:")
    add("same excerpts, same gain, same renderer, and the old side is the old audio. Stage 9C's own")
    add("*default vs old* result can therefore be treated as a control measured in a different session,")
    add("which is why the package repeats it (§8).")
    add("")
    add("**Levels and spectra per version.** One shared gain per song, applied to all three versions:")
    add("")
    add("| song | version | peak dBFS | RMS dBFS | centroid Hz | bandwidth Hz | flatness |")
    add("| :--- | :--- | ---: | ---: | ---: | ---: | ---: |")
    for record in bundle["song_records"]:
        trial_id = record["trial_id"]
        levels = comparison[trial_id]["levels"]
        for kind in ("default", "old", "new"):
            level = levels[kind]
            add(
                f"| `{record['song']}` | {kind} | {level['peak_dbfs']:.2f} | "
                f"{level['rms_dbfs']:.2f} | {level['centroid_hz']:.0f} | "
                f"{level['bandwidth_hz']:.0f} | {level['flatness']:.4f} |"
            )
    add("")
    add("**Hashes and duration.** One SHA-256 per rendered version, and the excerpt's length, so a")
    add("rerun can be compared against this document rather than against a description of it:")
    add("")
    add("| song | version | duration (s) | sha256 (first 16) |")
    add("| :--- | :--- | ---: | :--- |")
    for record in bundle["song_records"]:
        trial_id = record["trial_id"]
        block = comparison[trial_id]
        for kind in ("default", "old", "new"):
            add(
                f"| `{record['song']}` | {kind} | {block['duration_seconds']:.3f} | "
                f"`{block['sha256'][kind][:16]}` |"
            )
    add("")
    add("All three versions of a song have the same frame count and the same duration: the profile")
    add("changes what each channel sounds like, never what or when it plays.")
    add("")
    add("**Pairwise differences.** `audio identical` compares the two rendered WAV payloads byte for")
    add("byte; `frames identical` compares the register streams; `spectral distance` is the Stage 9C")
    add("band-energy cosine distance between the two versions:")
    add("")
    add("| song | pair | audio identical | frames identical | spectral distance | RMS Δ (dB) | AUDCTL |")
    add("| :--- | :--- | :--- | :--- | ---: | ---: | :--- |")
    for record in bundle["song_records"]:
        trial_id = record["trial_id"]
        for name in ("default_vs_old", "default_vs_new", "old_vs_new"):
            block = comparison[trial_id][name]
            audctl = (
                f"{block['left']} ${block['audctl']['left']:02X} → "
                f"{block['right']} ${block['audctl']['right']:02X}"
            )
            add(
                f"| `{record['song']}` | {name.replace('_', ' ')} | "
                f"{'yes' if block['audio_identical'] else 'no'} | "
                f"{'yes' if block['frames_identical'] else 'no'} | "
                f"{block['spectral_distance']:.4f} | {block['rms_delta_db']:+.2f} | {audctl} |"
            )
    add("")
    add("**Register-frame differences.** How many frames differ, and in which columns, between the")
    add("versions. Columns are named in row order (`AUDF1, AUDC1, AUDF2, AUDC2, …, AUDCTL`). An AUDF")
    add("column differing means the same notes sit at different dividers — a consequence of the")
    add("profile's clock, not of the music; a differing AUDC column is a different generator or a")
    add("different per-frame volume:")
    add("")
    add("| song | pair | frames differing | columns differing (frames) | AUDCTL |")
    add("| :--- | :--- | ---: | :--- | :--- |")
    for record in bundle["song_records"]:
        trial_id = record["trial_id"]
        for name in ("default_vs_old", "default_vs_new", "old_vs_new"):
            block = comparison[trial_id]["register_frames"][name]
            columns = ", ".join(
                f"{column}×{count}" for column, count in block["columns_differing"].items()
            ) or "—"
            audctl = (
                f"{block['left']} ${block['audctl']['left']:02X} → "
                f"{block['right']} ${block['audctl']['right']:02X}"
            )
            add(
                f"| `{record['song']}` | {name.replace('_', ' ')} | "
                f"{block['frames_differing']} / {block['frames_compared']} | {columns} | {audctl} |"
            )
    add("")
    add("**Clipping.** The peak is normalized to the target from the default side and the same gain is")
    add("applied to all three, so a louder timbre could clip. Every version's clipped-sample count is")
    add("recorded rather than hidden:")
    add("")
    add("| song | default | old | new |")
    add("| :--- | ---: | ---: | ---: |")
    for record in bundle["song_records"]:
        clipped = comparison[record["trial_id"]]["clipped_samples"]
        add(
            f"| `{record['song']}` | {clipped['default']} | {clipped['old']} | {clipped['new']} |"
        )
    add("")

    # ----------------------------------------------------------------- 8
    add("## 8. The listening experiment")
    add("")
    add("**Experimental choice.** A new, blinded package in `examples/sound_profile_rebinding_10a/`.")
    add("Nothing from Stage 9C is reused or overwritten.")
    add("")
    add("| | |")
    add("| :--- | :--- |")
    add(f"| pairs | **{len(bundle['trials'])}** — `default vs new`, `old vs new` and the "
        f"`default vs old` control, once per song |")
    add("| excerpt | 15.0 s from the start of the render, identical window for both sides |")
    add("| gain | one per song, from the default side, applied to all three versions |")
    add("| labels | `A` and `B` only; orientation randomized from seed 20261006 |")
    add("| order | the three comparisons of a song are shuffled per song |")
    add("| questions | better overall · more convincing Atari · more interesting character · "
        "how different (1–5) · comment |")
    add("| answers | `evaluation_rebinding_10a.csv`, filled in the browser and downloaded |")
    add("")
    add("The control pair re-asks the Stage 9C question inside this session. It is included because")
    add("Stage 9D measured a session effect — Atari character and confidence correlated with presentation")
    add(f"position at Pearson {SESSION_DRIFT_RHO['atari_character']:+.2f} and "
        f"{SESSION_DRIFT_RHO['confidence']:+.2f} — so without it a change in the `default vs new`")
    add("result could not be separated from the session the listener was in.")
    add("**The twelve primary comparisons are the `default vs new` and `old vs new` pairs**; the six")
    add("control pairs are analysed separately, against Stage 9C's own 5–0, and are not counted as")
    add("evidence for or against the new assignment.")
    add("")
    add("**What the interface does not say.** No version name, profile id, generator family, scope, "
        "source song or technical description appears on the page, and the three comparisons are")
    add("captioned identically, so nothing hints which side is the library. The mapping exists only in")
    add("`manifest.json`, which the README tells the listener not to open while listening.")
    add("")
    add("**What is asked, exactly:**")
    add("")
    add("1. Which version sounds better overall? (`A` / `B` / no clear difference)")
    add("2. Which sounds more convincing as Atari music? (`A` / `B` / no clear difference)")
    add("3. Which has the more interesting or appropriate sound character? (`A` / `B` / no clear "
        "difference)")
    add("4. How different do the two versions sound? (1–5)")
    add("5. Comment (free text, optional)")
    add("")
    add("How to listen:")
    add("")
    add("```bash")
    add("# open examples/sound_profile_rebinding_10a/index.html, or serve the folder:")
    add("python -m http.server 8731 --directory examples/sound_profile_rebinding_10a")
    add("```")
    add("")

    # ----------------------------------------------------------------- 9
    add("## 9. Limitations")
    add("")
    add("**Observed and structural.** These are properties of the material, not of the preparation:")
    add("")
    add("* **Six songs are not a population.** A win or a loss here is a direction, not a rate.")
    add("* **The same song is heard three times**, so a listener may recognize it and anchor on an")
    add("  earlier answer. The order and orientations are randomized to limit this, not to remove it.")
    add("* **The ratings came from one phrase.** Every profile was auditioned playing one bright-lead")
    add("  line, so `lead_tonal` really means \"this followed that melody\" and `percussive_noisy` means")
    add("  \"this did not\". They are evidence about character in that context, not about behaviour")
    add("  inside a particular arrangement.")
    add("* **One profile per channel.** `dziki2.json` puts a bell, a counter and a drum on channel 4, so")
    add("  one profile must serve all three. No assignment can be right for all of them, and the")
    add("  experiment does not pretend otherwise.")
    add("* **The library's top tier is a tie.** Several tonal profiles share the listener's highest")
    add("  ratings, so which one a song received is partly an experimental choice (§5).")
    add("* **Gestures are still not rendered.** Stage 9E measured that the binding carries six values")
    add("  and that every gesture series is discarded before the audio. Rebinding cannot change that,")
    add("  and it is the main reason a positive result here would not mean the representation is")
    add("  sufficient.")
    add("")
    add("**What this experiment therefore cannot show:** whether a *better library* would beat the")
    add("composer's own instruments, whether gesture rendering would, or whether the listener's")
    add("preferences generalise beyond these six songs and this sitting.")
    add("")

    # ----------------------------------------------------------------- 10
    add("## 10. STOP condition")
    add("")
    add("**STOP.** The experiment is prepared and nothing else is done:")
    add("")
    add("* no gesture rendering, no player change, no POKEY IR change;")
    add("* no change to `SoundProfile`, `PlayableSoundProfile`, the bank, a fingerprint or a profile")
    add("  document;")
    add("* no change to the DSL, the composer, the generator, the prompts or the MML/MADS exporters;")
    add("* no library selection, no profile removed, no rename;")
    add("* the Stage 9C package, its stimuli, its answers and its results are untouched (digested")
    add("  before and after, and the digests are equal);")
    add("* the six compositions and the six old bindings are byte-identical to what they were.")
    add("")
    add("Waiting for: the filled-in `evaluation_rebinding_10a.csv`.")
    add("")
    add("The next decision, in the brief's own terms:")
    add("")
    add("| result | next step |")
    add("| :--- | :--- |")
    add("| **A** — rebinding improves whole songs | investigate role-aware profile selection, and only "
        "then any automatic binding |")
    add("| **B** — rebinding does not improve them | profile selection is not the main problem; proceed "
        "to the minimal renderer capability experiment Stage 9E scoped |")
    add("| **C** — mixed | inspect which roles benefit and which do not |")
    add("")
    add("The next stage is not started here.")
    add("")
    return "\n".join(lines) + "\n"


def _num(value: Optional[float]) -> str:
    """Ratings as the listener gave them, with an explicit gap for the one they did not."""
    return "—" if value is None else f"{value:g}"


def _sound_usage(songs: Sequence[Mapping[str, Any]]) -> Dict[str, str]:
    """The distinct sounds the six songs use, and which roles use each — read off the old bindings."""
    usage: Dict[str, List[str]] = {}
    for record in songs:
        for item in record["instruments"]:
            key = (
                f"group {item['audio_group']} ({item['generator_family']}, {item['scope']})"
                if item["audio_group"] is not None
                else f"{item['old_profile']} — unlike anything else in the library"
            )
            usage.setdefault(key, []).append(f"`{record['song']}` `{item['instrument']}`")
    return {key: ", ".join(roles) for key, roles in sorted(usage.items())}

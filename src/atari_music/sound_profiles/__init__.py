"""Sound profile integration: POKEY hardware realization, external to the composition.

The composition describes musical intent. The profile describes POKEY realization.

Nothing in this package is reachable from the composition language, the AI schema or
the DSL. A profile is attached to an already-compiled POKEY IR (``IRSong``), by
``profile_id``, from a bank directory that lives outside this repository.

Modules
-------
``bank``
    Loading, validating and looking up a portable sound profile bank
    (``registry.json`` + ``profiles/``, written by the POKEY Sound Archaeology
    project).
``binding``
    The external binding document and the application of profiles to an ``IRSong``.
"""

from __future__ import annotations

from atari_music.sound_profiles.bank import (
    KNOWN_STATUSES,
    RENDERABLE_STATUSES,
    STATUS_MEASUREMENT_ONLY,
    STATUS_PLAYABLE,
    STATUS_PLAYABLE_WITH_LIMITATION,
    SoundProfile,
    SoundProfileBank,
    SoundProfileError,
    load_sound_profile_bank,
    parse_audctl,
    parse_hex_nibble,
)
from atari_music.sound_profiles.binding import (
    BINDING_SCHEMA,
    ProfileBinding,
    apply_profile_binding,
    describe_binding,
    load_profile_binding,
)

__all__ = [
    "BINDING_SCHEMA",
    "KNOWN_STATUSES",
    "RENDERABLE_STATUSES",
    "STATUS_MEASUREMENT_ONLY",
    "STATUS_PLAYABLE",
    "STATUS_PLAYABLE_WITH_LIMITATION",
    "ProfileBinding",
    "SoundProfile",
    "SoundProfileBank",
    "SoundProfileError",
    "apply_profile_binding",
    "describe_binding",
    "load_profile_binding",
    "load_sound_profile_bank",
    "parse_audctl",
    "parse_hex_nibble",
]

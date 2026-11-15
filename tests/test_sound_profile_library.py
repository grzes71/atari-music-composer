"""Stage 9B: the full POKEY Sound Archaeology library in the Composer bank.

The bank that shipped with Stage 9 held four profiles chosen to prove the integration. This
module locks the properties of the **full published library** — all 67 profiles — and the two
things that must not change when the library grows:

* the Stage 9 example still renders byte-identically, and
* a profile the publishing audit says describes no sound is refused rather than rendered as
  silence that looks like a working instrument.

Grouped by scope and by audited status, as the stage brief asks: every profile must be
loadable, parseable, fingerprint-valid and registry-addressable; only the renderable ones are
required to render.
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List

import numpy as np
import pytest
from click.testing import CliRunner

from atari_music.ai.client import generate_music_from_composition, load_composition_dsl
from atari_music.cli import cli
from atari_music.ir import compile_ir_to_pokey_frames, resolve_audctl_mode
from atari_music.mads_exporter import export_mads_asm
from atari_music.sound_profiles import (
    KNOWN_STATUSES,
    RENDERABLE_STATUSES,
    STATUS_MEASUREMENT_ONLY,
    STATUS_PLAYABLE,
    STATUS_PLAYABLE_WITH_LIMITATION,
    SoundProfileError,
    apply_profile_binding,
    describe_binding,
    load_profile_binding,
    load_sound_profile_bank,
)
from atari_music.sound_profiles.bank import (
    KNOWN_SCOPES,
    SCOPE_PAIR,
    SCOPE_VOICE,
    STATUS_INTERNALLY_CONTRADICTORY,
    STATUS_UNPLAYABLE,
    playable_fingerprint_of,
)
from atari_music.sound_profiles.binding import (
    PROFILE_STATUS_NOT_RENDERABLE,
    PROFILE_STATUS_UNKNOWN,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = REPO_ROOT / "tests" / "data" / "sound_profiles"
BANK_DIR = DATA_DIR / "bank"
VAULTS_DSL = DATA_DIR / "vaults_of_nhyrmeth.dsl"
VAULTS_BINDING = DATA_DIR / "vaults_binding.json"
SONGS_DIR = REPO_ROOT / "examples" / "songs"

#: The library the archaeology project published.
EXPECTED_PROFILES = 67
EXPECTED_VOICE = 49
EXPECTED_PAIR = 18
EXPECTED_RENDERABLE = 61
EXPECTED_STATUS_TOTALS = {
    STATUS_PLAYABLE: 22,
    STATUS_PLAYABLE_WITH_LIMITATION: 39,
    STATUS_MEASUREMENT_ONLY: 6,
}

#: The two profiles the Stage 9 example binds, and every artefact that render produces.
#: These hashes are the Stage 9 baseline, recorded so the regression test needs no
#: pre-existing output files on disk.
#:
#: Re-baselined twice: first for the C1 per-channel modulation (song data format version 1,
#: which touched the instrument table layout), and second for Phase 1 ADSR & muting fixes
#: (which fixed the Attack/Decay/Release envelope math in ``pokey_hw.player_envelope_volumes``
#: and grew ``player.asm`` by 128 bytes to 1144 bytes, leaving the exported ``.asm`` data hashes
#: unchanged).
STAGE9_BINDING_PROFILES = ("pokey_ref_a8c81a84", "pokey_ref_3627798b")
STAGE9_BASELINE = {
    "vaults_profile.wav": "56e1938cc374368d7360d0f5dc71878f5c9e3230432e9209193b2ce8e5eb9c00",
    "vaults_profile.asm": "31abd33b1e82ae83462296148e233935479461992791c3137bb21ba7e997466e",
    "vaults_default.wav": "17bf1ac570148650c1aa3b1f4819394ae2be29d8176d5c935d2b0b018b9dd1f7",
    "vaults_default.asm": "8971a9d89b937b57760f64daf9b529c1f09156dc723c56662609e301638a0190",
}
#: The XEX baseline needs the real MADS assembler, which a fresh checkout does not have.
#: Re-baselined with the Phase 1 WAV/player changes: the XEX embeds ``player.asm``, which grew
#: from 1016 to 1144 bytes for the ADSR & muting fixes.
STAGE9_XEX_BASELINE = "0d7214f142fbfad3948535abdb83161e8b4fdddb1fefc1fc48f6d89a706d48fc"


@pytest.fixture(scope="module")
def bank():
    return load_sound_profile_bank(BANK_DIR)


@pytest.fixture(scope="module")
def vaults_doc():
    return load_composition_dsl(VAULTS_DSL)


@pytest.fixture(scope="module")
def vaults_result(vaults_doc):
    return generate_music_from_composition(vaults_doc)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _registry() -> Dict[str, Any]:
    return json.loads((BANK_DIR / "registry.json").read_text(encoding="utf-8"))


def _one_note(instrument: str, note: str = "D2") -> Any:
    from atari_music.ai.schema import (
        AICompositionDoc,
        AICompositionMetadata,
        AIHardwareConfig,
        AIInstrumentDef,
        AIPatternChannelEvent,
        AIPatternDef,
    )

    return AICompositionDoc(
        metadata=AICompositionMetadata(title="Profile Status", bpm=120, key="C", mode="minor"),
        hardware=AIHardwareConfig(channels=4, use_16bit_bass=False),
        instruments=[AIInstrumentDef(id=instrument, name=instrument, character="bright_lead")],
        patterns=[
            AIPatternDef(
                id="A",
                length_steps=16,
                channels={
                    "1": [
                        AIPatternChannelEvent(
                            step=0, note=note, instrument=instrument, duration=8, volume=12
                        )
                    ]
                },
            )
        ],
        sequence=["A", "A"],
        loop_point=0,
    )


# ===========================================================================
# Inventory — the published library
# ===========================================================================
def test_the_bank_holds_the_full_published_library(bank) -> None:
    assert len(bank.ids()) == EXPECTED_PROFILES
    assert len(bank.of_scope(SCOPE_VOICE)) == EXPECTED_VOICE
    assert len(bank.of_scope(SCOPE_PAIR)) == EXPECTED_PAIR
    assert bank.schema == "pokey-sound-profile-registry-1.0"


def test_the_registry_agrees_with_the_profiles_on_disk(bank) -> None:
    registry = _registry()
    assert registry["profile_count"] == EXPECTED_PROFILES
    assert len(registry["profiles"]) == EXPECTED_PROFILES

    entries = {entry["profile_id"]: entry for entry in registry["profiles"]}
    assert set(entries) == set(bank.ids())

    files = {path.stem for path in (BANK_DIR / "profiles").glob("*.json")}
    assert files == set(entries), "no profile file may be unreferenced or missing"


def test_every_profile_is_loadable_parseable_and_fingerprint_valid(bank) -> None:
    for profile_id in bank.ids():
        profile = bank.get(profile_id)
        document = profile.document
        # parseable with the schema the artefact declares
        assert document["schema"] == "pokey-playable-sound-profile-1.0", profile_id
        assert document["profile_id"] == profile_id
        # fingerprint valid in both directions: the document hashes to the registry value,
        # and to its own embedded value
        assert profile.fingerprint, profile_id
        assert playable_fingerprint_of(document) == profile.fingerprint, profile_id
        assert document["playable_fingerprint"] == profile.fingerprint, profile_id
        # registry-addressable and structurally complete
        assert profile.scope in KNOWN_SCOPES, profile_id
        assert profile.audctl_mode is not None, profile_id
        assert profile.distortion_byte is not None, profile_id
        assert profile.divider_bits in (8, 16), profile_id
        assert profile.audible_channel in (1, 2, 3, 4), profile_id


def test_the_registry_publishes_an_audited_status_for_every_profile(bank) -> None:
    for profile_id in bank.ids():
        profile = bank.get(profile_id)
        assert profile.status in KNOWN_STATUSES, profile_id
        assert profile.status_known, profile_id
        # A profile that is not renderable must say why.
        if not profile.renderable:
            assert profile.blocking_codes, f"{profile_id} is refused without a reason"


def test_the_status_totals_are_the_audited_ones(bank) -> None:
    assert bank.status_totals() == EXPECTED_STATUS_TOTALS
    assert len(bank.renderable()) == EXPECTED_RENDERABLE
    # The non-renderable profiles are exactly the silent ones, and none is quietly dropped.
    refused = {pid for pid in bank.ids() if not bank.get(pid).renderable}
    assert len(refused) == EXPECTED_PROFILES - EXPECTED_RENDERABLE
    for profile_id in refused:
        assert bank.get(profile_id).status in KNOWN_STATUSES
        assert "SILENT_PROFILE" in bank.get(profile_id).blocking_codes or (
            bank.get(profile_id).status == STATUS_MEASUREMENT_ONLY
        )


def test_no_profile_was_modified_by_publication() -> None:
    """The bank is a copy of the library, not a re-derivation of it.

    Every profile's ``source_profile.profile_fingerprint`` still names the Stage 5
    ``SoundProfile`` it came from, and the bank's own producer block records which library it
    was published from.
    """
    registry = _registry()
    assert registry["producer"]["tool"] == "pokey-sound-archaeology"
    assert registry["producer"]["library_profiles"] == EXPECTED_PROFILES

    seen_source_ids = set()
    for path in sorted((BANK_DIR / "profiles").glob("*.json")):
        document = json.loads(path.read_text(encoding="utf-8"))
        source = document["source_profile"]
        assert source["schema_version"] == "2.0", path.name
        assert len(source["profile_fingerprint"]) == 64, path.name
        seen_source_ids.add(source["profile_id"])
    assert len(seen_source_ids) == EXPECTED_PROFILES


def test_the_audited_limitations_are_preserved_in_the_registry() -> None:
    """Limitations travel with the profile so a consumer can report them without the audit."""
    registry = _registry()
    with_gaps = [
        entry for entry in registry["profiles"] if entry.get("consumer_gap_codes")
    ]
    with_limits = [entry for entry in registry["profiles"] if entry.get("limitation_codes")]
    assert len(with_gaps) == 60, "60 profiles carry a consumer-side gap"
    assert with_limits, "the audited limitations must be preserved"
    codes = {code for entry in registry["profiles"] for code in entry.get("consumer_gap_codes", ())}
    assert "GESTURE_NOT_RENDERABLE_BY_CONSUMER" in codes
    assert "VOLUME_MODULATION_NOT_REPRODUCIBLE" in codes
    # The profiles the audit found reaching AUDF $FF keep that recorded.
    export_limited = {
        entry["profile_id"]
        for entry in registry["profiles"]
        if "AUDF_FF_EXPORT_BOUNDARY" in entry.get("consumer_gap_codes", ())
    }
    assert len(export_limited) == 5


# ===========================================================================
# VOICE profiles
# ===========================================================================
def test_every_voice_profile_is_single_channel_and_8_bit(bank) -> None:
    for profile in bank.of_scope(SCOPE_VOICE):
        assert profile.divider_bits == 8, profile.profile_id
        assert profile.companion_channel is None, profile.profile_id
        assert profile.requires_simultaneous_channels is False, profile.profile_id
        assert profile.audible_channel in (1, 2, 3, 4), profile.profile_id


def test_renderable_voice_profiles_declare_a_configuration_the_composer_can_carry(bank) -> None:
    """A VOICE profile must be realizable as an ordinary 8-bit channel somewhere.

    The four joined-AUDCTL VOICE profiles are excluded by their status (all four are silent
    ``MEASUREMENT_ONLY``), which is why the check can be stated this simply.
    """
    for profile in bank.of_scope(SCOPE_VOICE):
        if not profile.renderable:
            continue
        # A 64 kHz profile needs no AUDCTL bits of its own; a $50 one is the F8 family.
        if profile.audctl_mode == 0x00:
            assert profile.distortion_byte in range(0, 0x100), profile.profile_id
        else:
            assert profile.audctl_mode & 0x10, profile.profile_id

    joined_voice = [p for p in bank.of_scope(SCOPE_VOICE) if p.audctl_mode != 0x00]
    assert len(joined_voice) == 4
    assert all(not p.renderable for p in joined_voice)


def test_a_renderable_voice_profile_can_be_bound_and_changes_the_registers(bank) -> None:
    """Every renderable VOICE profile either changes the registers, or is refused for a
    recorded reason.

    Two profiles in the library measured an envelope attack longer than the composer's
    ``0..15`` frame field, so the existing envelope validation refuses them on a composition
    that does not declare its own envelope. That refusal is correct — it is asserted here
    rather than worked around, and it is cross-checked against the audited consumer gap.
    """
    doc = _one_note("lead")
    result = generate_music_from_composition(doc)
    base_frames = compile_ir_to_pokey_frames(result.pokey_ir)

    checked = 0
    refused_for_envelope = []
    for profile in bank.of_scope(SCOPE_VOICE):
        if not profile.renderable:
            continue
        binding = load_profile_binding(
            {
                "schema": "atari-music/sound-profile-binding/1",
                "instruments": {"lead": profile.profile_id},
            }
        )
        try:
            bound = apply_profile_binding(result, binding, bank, composition=doc)
        except SoundProfileError as err:
            assert err.code == "PROFILE_ENVELOPE_OUT_OF_RANGE", (profile.profile_id, err.code)
            assert "ENVELOPE_FRAME_ABOVE_CONSUMER_MAX" in profile.consumer_gap_codes, profile.profile_id
            refused_for_envelope.append(profile.profile_id)
            continue

        frames = compile_ir_to_pokey_frames(bound.pokey_ir)
        # channel 1 (1-based) is column 1
        generators = set((frames[:, 1] & 0xE0).tolist()) - {0x00}
        if profile.distortion_byte != 0x00:
            assert generators == {profile.distortion_byte}, profile.profile_id
        assert set(frames[:, 8].tolist()) == {profile.audctl_mode}, profile.profile_id
        checked += 1

    # 43 of the 49 VOICE profiles are renderable: six are refused by status, all of them the
    # silent ones (the four joined-AUDCTL F8 profiles plus two ordinary-looking VOICE ones).
    assert checked + len(refused_for_envelope) == 43, "every VOICE profile with a renderable status"
    assert sorted(refused_for_envelope) == ["pokey_ref_686d2070", "pokey_ref_d172d15e"]
    assert checked == 41


# ===========================================================================
# PAIR profiles
# ===========================================================================
def test_every_pair_profile_is_a_16_bit_1_2_pair(bank) -> None:
    for profile in bank.of_scope(SCOPE_PAIR):
        assert profile.divider_bits == 16, profile.profile_id
        assert profile.pair == "1+2", profile.profile_id
        assert profile.audible_channel == 2, profile.profile_id
        assert profile.companion_channel == 1, profile.profile_id
        assert profile.requires_simultaneous_channels is True, profile.profile_id
        # The pair's clock: the join bit, and (for this library) the 1.79 MHz bit too.
        assert profile.audctl_mode & 0x10, profile.profile_id


def test_pair_profiles_keep_their_1_79mhz_clock_and_are_not_read_as_the_composer_s_16bit(bank) -> None:
    """``$50`` must not become ``$10``: same join, different clock, different divider offset."""
    doc = _one_note("bass", note="D2")
    doc.hardware.use_16bit_bass = True
    result = generate_music_from_composition(doc)
    base_frames = compile_ir_to_pokey_frames(result.pokey_ir)
    assert set(base_frames[:, 8].tolist()) == {0x10}, "the composer's own BASS 16BIT is $10"

    checked = 0
    for profile in bank.of_scope(SCOPE_PAIR):
        if not profile.renderable:
            continue
        assert profile.audctl_mode == 0x50, profile.profile_id
        binding = load_profile_binding(
            {"schema": "atari-music/sound-profile-binding/1", "instruments": {"bass": profile.profile_id}}
        )
        bound = apply_profile_binding(result, binding, bank, composition=doc)
        frames = compile_ir_to_pokey_frames(bound.pokey_ir)

        # The profile's own byte is written, unchanged.
        assert set(frames[:, 8].tolist()) == {0x50}, profile.profile_id
        # Both registers of the pair carry a divider, and channel 1 is the muted low byte.
        assert frames[0, 1] == 0, profile.profile_id
        generators = set((frames[:, 3] & 0xE0).tolist()) - {0x00}
        if profile.distortion_byte != 0x00:
            assert generators == {profile.distortion_byte}, profile.profile_id
        # The same note yields a different divider under 64 kHz (+1) than under 1.79 MHz (+7).
        assert (base_frames[0, 0], base_frames[0, 2]) != (frames[0, 0], frames[0, 2]), profile.profile_id
        checked += 1
    assert checked == 18, "every PAIR profile is renderable"


def test_a_pair_profile_still_refuses_an_independent_voice_on_channel_two(bank) -> None:
    """The channel-conflict rule is unchanged by the larger bank."""
    from atari_music.ai.schema import (
        AICompositionDoc,
        AICompositionMetadata,
        AIHardwareConfig,
        AIInstrumentDef,
        AIPatternChannelEvent,
        AIPatternDef,
    )

    pair = next(p for p in bank.of_scope(SCOPE_PAIR) if p.renderable)
    doc = AICompositionDoc(
        metadata=AICompositionMetadata(title="Pair Conflict", bpm=120, key="C", mode="minor"),
        hardware=AIHardwareConfig(channels=4, use_16bit_bass=True),
        instruments=[
            AIInstrumentDef(id="bass", name="Bass", character="bass"),
            AIInstrumentDef(id="harm", name="Harmony", character="soft_pad"),
        ],
        patterns=[
            AIPatternDef(
                id="A",
                length_steps=16,
                channels={
                    "1": [AIPatternChannelEvent(step=0, note="D2", instrument="bass", duration=8)],
                    "2": [AIPatternChannelEvent(step=0, note="A3", instrument="harm", duration=8)],
                },
            )
        ],
        sequence=["A", "A"],
        loop_point=0,
    )
    result = generate_music_from_composition(doc)
    with pytest.raises(SoundProfileError) as err:
        apply_profile_binding(
            result,
            load_profile_binding(
                {
                    "schema": "atari-music/sound-profile-binding/1",
                    "instruments": {"bass": pair.profile_id},
                }
            ),
            bank,
            composition=doc,
        )
    assert err.value.code == "PROFILE_PAIR_CHANNEL_CONFLICT"


# ===========================================================================
# MEASUREMENT_ONLY — published, but not renderable
# ===========================================================================
def test_measurement_only_profiles_are_refused_with_a_clear_error(bank) -> None:
    """No silent fallback: a profile of silence is never rendered as an instrument."""
    doc = _one_note("lead")
    result = generate_music_from_composition(doc)
    refused = bank.of_status(STATUS_MEASUREMENT_ONLY)
    assert len(refused) == 6

    for profile in refused:
        binding = load_profile_binding(
            {
                "schema": "atari-music/sound-profile-binding/1",
                "instruments": {"lead": profile.profile_id},
            }
        )
        with pytest.raises(SoundProfileError) as err:
            apply_profile_binding(result, binding, bank, composition=doc)
        assert err.value.code == PROFILE_STATUS_NOT_RENDERABLE, profile.profile_id
        assert err.value.detail["status"] == STATUS_MEASUREMENT_ONLY
        assert err.value.detail["profile_id"] == profile.profile_id
        # The error names a reason, so the user can act on it.
        assert err.value.detail["blocking_codes"]

        # ...and the report refuses it too rather than describing a render that cannot happen.
        with pytest.raises(SoundProfileError):
            describe_binding(result, binding, bank, composition=doc)


def test_a_measurement_only_profile_is_still_loadable_and_addressable(bank) -> None:
    """Publishing it is the point: it can be inspected, it just cannot be played."""
    for profile in bank.of_status(STATUS_MEASUREMENT_ONLY):
        assert bank.get(profile.profile_id).profile_id == profile.profile_id
        assert profile.document["schema"] == "pokey-playable-sound-profile-1.0"
        assert profile.renderable is False
        assert profile.status_known is True


def test_an_unknown_status_is_refused_rather_than_assumed(tmp_path: Path) -> None:
    """A future verdict cannot pass silently through an older consumer."""
    import shutil
    from atari_music.sound_profiles.bank import playable_fingerprint_of as recompute

    copied = tmp_path / "bank"
    shutil.copytree(BANK_DIR, copied)
    registry_path = copied / "registry.json"
    registry = json.loads(registry_path.read_text(encoding="utf-8"))
    target = next(entry for entry in registry["profiles"] if entry["status"] == STATUS_PLAYABLE)
    target["status"] = "SOMETHING_NEW"
    registry_path.write_text(json.dumps(registry, indent=2, sort_keys=True), encoding="utf-8")

    unknown_bank = load_sound_profile_bank(copied)
    assert unknown_bank.get(target["profile_id"]).status_known is False

    doc = _one_note("lead")
    result = generate_music_from_composition(doc)
    binding = load_profile_binding(
        {
            "schema": "atari-music/sound-profile-binding/1",
            "instruments": {"lead": target["profile_id"]},
        }
    )
    with pytest.raises(SoundProfileError) as err:
        apply_profile_binding(result, binding, unknown_bank, composition=doc)
    assert err.value.code == PROFILE_STATUS_UNKNOWN


def test_a_renderable_profile_that_carries_limitations_is_still_rendered(bank) -> None:
    """``PLAYABLE_WITH_LIMITATION`` is published and usable; the limitation is reported."""
    doc = _one_note("lead")
    result = generate_music_from_composition(doc)
    limited = next(
        p
        for p in bank.of_status(STATUS_PLAYABLE_WITH_LIMITATION)
        if p.consumer_gap_codes and p.scope == SCOPE_VOICE
    )
    binding = load_profile_binding(
        {"schema": "atari-music/sound-profile-binding/1", "instruments": {"lead": limited.profile_id}}
    )
    bound = apply_profile_binding(result, binding, bank, composition=doc)
    assert bound.pokey_ir.instruments[0].profile_id == limited.profile_id

    report = describe_binding(result, binding, bank, composition=doc)
    entry = report["instruments"][0]
    assert entry["status"] == STATUS_PLAYABLE_WITH_LIMITATION
    assert entry["consumer_gap_codes"], "the limitation must be reported, not hidden"
    assert entry["blocking_issues"] == []


# ===========================================================================
# Determinism
# ===========================================================================
def test_the_bank_loads_identically_twice() -> None:
    first = load_sound_profile_bank(BANK_DIR)
    second = load_sound_profile_bank(BANK_DIR)
    assert first.ids() == second.ids()
    assert first.status_totals() == second.status_totals()
    for profile_id in first.ids():
        assert first.get(profile_id).fingerprint == second.get(profile_id).fingerprint


def test_rendering_with_the_full_bank_is_deterministic(tmp_path: Path) -> None:
    baseline = None
    for index in range(2):
        out = tmp_path / f"run{index}.wav"
        asm = tmp_path / f"run{index}.asm"
        result = CliRunner().invoke(
            cli,
            [
                "import-dsl",
                str(VAULTS_DSL),
                "--sound-bank",
                str(BANK_DIR),
                "--profile-bindings",
                str(VAULTS_BINDING),
                "--output-wav",
                str(out),
                "--output-asm",
                str(asm),
            ],
        )
        assert result.exit_code == 0, result.output
        digest = (_sha256(out), _sha256(asm))
        if baseline is None:
            baseline = digest
        else:
            assert digest == baseline


# ===========================================================================
# The Stage 9 regression
# ===========================================================================
def test_the_stage_9_example_still_resolves_its_exact_profile_ids(bank) -> None:
    binding = load_profile_binding(VAULTS_BINDING)
    assert set(binding.instruments.values()) == set(STAGE9_BINDING_PROFILES)
    for profile_id in STAGE9_BINDING_PROFILES:
        assert bank.get(profile_id).fingerprint, profile_id


def test_the_stage_9_render_is_byte_identical_with_the_full_bank(tmp_path: Path) -> None:
    """Four profiles became sixty-seven, and the Stage 9 output did not move.

    The hashes are the Stage 9 baseline, frozen here so the check works without the
    (gitignored) ``examples/`` outputs on disk. ``--output-asm`` writes the song data
    (``export_mads_asm``); the XEX path writes its own harness assembly, which is a different
    file and is covered separately below.
    """
    runner = CliRunner()

    bound_wav = tmp_path / "vaults_profile.wav"
    bound_asm = tmp_path / "vaults_profile.asm"
    result = runner.invoke(
        cli,
        [
            "import-dsl",
            str(VAULTS_DSL),
            "--sound-bank",
            str(BANK_DIR),
            "--profile-bindings",
            str(VAULTS_BINDING),
            "--output-wav",
            str(bound_wav),
            "--output-asm",
            str(bound_asm),
        ],
    )
    assert result.exit_code == 0, result.output
    assert _sha256(bound_wav) == STAGE9_BASELINE["vaults_profile.wav"]
    assert _sha256(bound_asm) == STAGE9_BASELINE["vaults_profile.asm"]

    default_wav = tmp_path / "vaults_default.wav"
    default_asm = tmp_path / "vaults_default.asm"
    result = runner.invoke(
        cli,
        [
            "import-dsl",
            str(VAULTS_DSL),
            "--output-wav",
            str(default_wav),
            "--output-asm",
            str(default_asm),
        ],
    )
    assert result.exit_code == 0, result.output
    assert _sha256(default_wav) == STAGE9_BASELINE["vaults_default.wav"]
    assert _sha256(default_asm) == STAGE9_BASELINE["vaults_default.asm"]


def test_the_stage_9_xex_is_byte_identical_with_the_full_bank(tmp_path: Path) -> None:
    import subprocess

    from unittest.mock import MagicMock

    mads = REPO_ROOT / "tools" / "mads" / "mads.exe"
    player = REPO_ROOT / "player.asm"
    if not mads.exists() or not player.exists():
        pytest.skip("MADS assembler or player.asm not present in this checkout")

    out = tmp_path / "vaults_profile.xex"
    result = CliRunner().invoke(
        cli,
        [
            "build-xex",
            str(VAULTS_DSL),
            "--format",
            "dsl",
            "-o",
            str(out),
            "--mads",
            str(mads),
            "--player-asm",
            str(player),
            "--sound-bank",
            str(BANK_DIR),
            "--profile-bindings",
            str(VAULTS_BINDING),
        ],
    )
    assert result.exit_code == 0, result.output
    assert _sha256(out) == STAGE9_XEX_BASELINE


def test_the_composition_is_untouched_by_the_binding(vaults_doc, vaults_result, bank) -> None:
    """The Stage 9 boundary still holds with the full library loaded."""
    bound = apply_profile_binding(
        vaults_result, load_profile_binding(VAULTS_BINDING), bank, composition=vaults_doc
    )
    assert bound.music_ir == vaults_result.music_ir
    assert bound.pokey_ir.patterns == vaults_result.pokey_ir.patterns
    assert bound.pokey_ir.sequence == vaults_result.pokey_ir.sequence
    assert resolve_audctl_mode(bound.pokey_ir) == 0x50


# ===========================================================================
# The per-song bindings in examples/songs
# ===========================================================================
def _song_bindings() -> List[Path]:
    if not SONGS_DIR.is_dir():
        pytest.skip("examples/songs is not present in this checkout")
    bindings = sorted(SONGS_DIR.glob("*.binding.json"))
    if not bindings:
        pytest.skip("no per-song bindings in examples/songs")
    return bindings


def test_every_song_has_a_binding_next_to_it() -> None:
    songs = sorted(
        path
        for path in SONGS_DIR.iterdir()
        if path.suffix in (".dsl", ".json") and not path.name.endswith(".binding.json")
    )
    bindings = _song_bindings()
    assert len(songs) == len(bindings)
    for song in songs:
        assert (SONGS_DIR / f"{song.name}.binding.json").is_file(), song.name


def test_every_song_binding_applies_without_conflict(tmp_path: Path) -> None:
    """Each binding is proved by applying it, not by inspecting it."""
    from atari_music.ai.client import load_composition_json

    bank = load_sound_profile_bank(BANK_DIR)
    for binding_path in _song_bindings():
        song_path = SONGS_DIR / binding_path.name[: -len(".binding.json")]
        doc = (
            load_composition_dsl(song_path)
            if song_path.suffix == ".dsl"
            else load_composition_json(song_path)
        )
        result = generate_music_from_composition(doc)
        binding = load_profile_binding(binding_path)
        # The bank path inside the binding is relative to the binding file itself.
        assert binding.bank_path().resolve() == BANK_DIR.resolve(), binding_path.name

        bound = apply_profile_binding(result, binding, bank, composition=doc)
        frames = compile_ir_to_pokey_frames(bound.pokey_ir)
        assert frames.shape[1] == 9
        assert frames.shape[0] > 0

        # Every bound instrument exists in the composition.
        declared = {inst.id for inst in doc.instruments}
        assert set(binding.instruments) <= declared, binding_path.name
        # The composition's music is untouched.
        assert bound.music_ir == result.music_ir
        assert bound.pokey_ir.patterns == result.pokey_ir.patterns
        # Every bound profile is renderable, and its byte is what the frames carry.
        for profile_id in binding.instruments.values():
            assert bank.get(profile_id).renderable, profile_id


def test_song_bindings_are_deterministic() -> None:
    digests = [
        hashlib.sha256(path.read_bytes()).hexdigest() for path in _song_bindings()
    ]
    assert digests == [
        hashlib.sha256(path.read_bytes()).hexdigest() for path in _song_bindings()
    ]


def test_the_song_bindings_cover_both_bank_scopes_and_all_three_statuses() -> None:
    """The set exercises the library rather than repeating one profile."""
    used = []
    for binding_path in _song_bindings():
        used.extend(load_profile_binding(binding_path).instruments.values())
    assert used, "bindings must name profiles"
    assert len(set(used)) > 10, "the songs should exercise more than a handful of profiles"

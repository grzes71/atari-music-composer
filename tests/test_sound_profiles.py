"""Stage 9: POKEY sound profile integration.

Three levels, as the stage brief asks for:

* **Level 1** — bank loading: registry, exact lookup, fingerprint verification, and every
  refusal path;
* **Level 2** — composition interpretation: what a binding does to the POKEY IR, and every
  conflict it refuses;
* **Level 3** — end to end: WAV and XEX produced through the real CLI, agreement between
  the two output paths, and determinism.

The composition-side tests assert the *negative* direction too — that a binding never
touches a pitch, a duration, a velocity, a pattern or a role.
"""

from __future__ import annotations

import json
import shutil
import struct
import subprocess
import sys
import wave
from pathlib import Path
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock

import numpy as np
import pytest
from click.testing import CliRunner
from atari_music import pokey_hw
from atari_music.ai.client import generate_music_from_composition, load_composition_dsl
from atari_music.ai.schema import (
    AICompositionDoc,
    AICompositionMetadata,
    AIHardwareConfig,
    AIInstrumentDef,
    AIPatternChannelEvent,
    AIPatternDef,
)
from atari_music.cli import cli
from atari_music.ir import compile_ir_to_pokey_frames, resolve_audctl_mode
from conftest import fake_xex_bytes
from atari_music.mads_exporter import export_mads_asm
from atari_music.sound_profiles import (
    BINDING_SCHEMA,
    SoundProfile,
    SoundProfileError,
    apply_profile_binding,
    describe_binding,
    load_profile_binding,
    load_sound_profile_bank,
)
from atari_music.sound_profiles.bank import (
    PROFILE_BANK_MISSING,
    PROFILE_BANK_SCHEMA_UNSUPPORTED,
    PROFILE_FILE_MISSING,
    PROFILE_FINGERPRINT_MISMATCH,
    PROFILE_INVALID,
    PROFILE_NOT_FOUND,
    playable_fingerprint_of,
)
from atari_music.sound_profiles.binding import (
    PROFILE_AUDCTL_CONFLICT,
    PROFILE_CHANNEL_REQUIREMENT,
    PROFILE_DISTORTION_CONFLICT,
    PROFILE_ENVELOPE_OUT_OF_RANGE,
    PROFILE_PAIR_CHANNEL_CONFLICT,
    PROFILE_BINDING_INVALID,
    PROFILE_BINDING_UNKNOWN_INSTRUMENT,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
#: The example lives in a tracked directory: ``examples/`` is gitignored in this
#: repository (it holds generated artefacts), so fixtures must not live there.
EXAMPLE_DIR = REPO_ROOT / "tests" / "data" / "sound_profiles"
BANK_DIR = EXAMPLE_DIR / "bank"
VAULTS_DSL = EXAMPLE_DIR / "vaults_of_nhyrmeth.dsl"
VAULTS_BINDING = EXAMPLE_DIR / "vaults_binding.json"

#: The example bank's ids, so a test failure names what changed.
VOICE_PROFILE = "pokey_ref_a8c81a84"      # VOICE, $00, generator nibble $8, envelope confidence 0.9
VOICE_PURE_PROFILE = "pokey_ref_048db11d"  # VOICE, $00, generator nibble $A
PAIR_PROFILE = "pokey_ref_3627798b"       # PAIR 1+2, $50, generator nibble $C
PAIR_PROFILE_ALT = "pokey_ref_050170ef"   # PAIR 1+2, $50, generator nibble $8


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _composition(
    *,
    channels: Dict[str, List[AIPatternChannelEvent]],
    instruments: Optional[List[AIInstrumentDef]] = None,
    use_16bit_bass: bool = False,
    title: str = "Profile Test",
) -> AICompositionDoc:
    return AICompositionDoc(
        metadata=AICompositionMetadata(title=title, bpm=120, key="C", mode="minor"),
        hardware=AIHardwareConfig(channels=4, use_16bit_bass=use_16bit_bass),
        instruments=instruments
        or [
            AIInstrumentDef(id="lead", name="Lead", character="bright_lead"),
            AIInstrumentDef(id="bass", name="Bass", character="bass"),
            AIInstrumentDef(id="harm", name="Harmony", character="soft_pad"),
            AIInstrumentDef(id="perc", name="Drums", character="percussion"),
        ],
        patterns=[
            AIPatternDef(id="A", length_steps=16, channels=channels),
        ],
        sequence=["A", "A"],
        loop_point=0,
    )


def _one_note(instrument: str, note: str = "D2", volume: int = 12) -> List[AIPatternChannelEvent]:
    return [AIPatternChannelEvent(step=0, note=note, instrument=instrument, duration=8, volume=volume)]


def _binding(mapping: Dict[str, str]) -> Any:
    return load_profile_binding({"schema": BINDING_SCHEMA, "instruments": mapping})


def _copy_bank(destination: Path) -> Path:
    target = destination / "bank"
    shutil.copytree(BANK_DIR, target)
    return target


def _rewrite_registry(bank_dir: Path, mutate) -> None:
    path = bank_dir / "registry.json"
    registry = json.loads(path.read_text(encoding="utf-8"))
    mutate(registry)
    path.write_text(json.dumps(registry, indent=2, sort_keys=True), encoding="utf-8")


def _rewrite_profile(bank_dir: Path, profile_id: str, mutate) -> None:
    """Edit a profile document and keep its registry fingerprint valid."""
    profile_path = bank_dir / "profiles" / f"{profile_id}.json"
    document = json.loads(profile_path.read_text(encoding="utf-8"))
    mutate(document)
    document["playable_fingerprint"] = playable_fingerprint_of(document)
    profile_path.write_text(json.dumps(document, indent=2, sort_keys=True), encoding="utf-8")

    def fix(registry: Dict[str, Any]) -> None:
        for entry in registry["profiles"]:
            if entry["profile_id"] == profile_id:
                entry["playable_fingerprint"] = document["playable_fingerprint"]

    _rewrite_registry(bank_dir, fix)


@pytest.fixture(scope="module")
def bank():
    return load_sound_profile_bank(BANK_DIR)


@pytest.fixture(scope="module")
def vaults_doc() -> AICompositionDoc:
    return load_composition_dsl(VAULTS_DSL)


@pytest.fixture(scope="module")
def vaults_result(vaults_doc):
    return generate_music_from_composition(vaults_doc)


def _wav_samples(path: Path) -> tuple:
    with wave.open(str(path), "rb") as handle:
        raw = handle.readframes(handle.getnframes())
    return struct.unpack(f"<{len(raw) // 2}h", raw)


# ===========================================================================
# Level 1 — profile loading
# ===========================================================================
@pytest.mark.core
@pytest.mark.audio
def test_bank_loads_and_verifies_every_profile(bank) -> None:
    assert bank.schema == "pokey-sound-profile-registry-1.0"
    # Stage 9B published the full library; the four profiles of the Stage 9 demo bank are in
    # it unchanged, under the same ids.
    assert len(bank.ids()) == 67
    assert bank.ids() == tuple(sorted(bank.ids()))
    for demo_id in (
        "pokey_ref_048db11d",
        "pokey_ref_050170ef",
        "pokey_ref_3627798b",
        "pokey_ref_a8c81a84",
    ):
        assert demo_id in bank.ids()
    assert bank.status == "experimental"
    # The bank's own note is a statement about itself, not a recommendation; a consumer
    # must not present membership as a judgement about sound.
    assert "not a recommended library" in bank.note
    for profile in bank.profiles.values():
        assert profile.fingerprint, profile.profile_id
        assert profile.document["playable_fingerprint"] == profile.fingerprint


@pytest.mark.core
@pytest.mark.audio
def test_recomputed_fingerprint_matches_the_registry(bank) -> None:
    for profile in bank.profiles.values():
        assert playable_fingerprint_of(profile.document) == profile.fingerprint


@pytest.mark.core
@pytest.mark.audio
def test_bank_exposes_the_hardware_facts_of_both_scopes(bank) -> None:
    voice = bank.get(VOICE_PROFILE)
    assert voice.scope == "VOICE"
    assert voice.divider_bits == 8
    assert voice.audctl_mode == 0x00
    assert voice.audible_channel == 3
    assert voice.companion_channel is None
    assert voice.requires_simultaneous_channels is False

    pair = bank.get(PAIR_PROFILE)
    assert pair.scope == "PAIR"
    assert pair.divider_bits == 16
    assert pair.audctl_mode == 0x50
    assert pair.pair == "1+2"
    assert pair.audible_channel == 2
    assert pair.companion_channel == 1
    assert pair.requires_simultaneous_channels is True


def _profile_with_volume_gesture(volume: Any, *, playability: Any = None) -> SoundProfile:
    """A synthetic profile carrying one ``gesture.volume`` block. Nothing here touches a real bank."""
    document: Dict[str, Any] = {"gesture": {"volume": volume}}
    if playability is not None:
        document["playability"] = {"gesture": {"volume": playability}}
    return SoundProfile(
        profile_id="pokey_ref_synthetic",
        scope="VOICE",
        fingerprint="synthetic",
        document=document,
    )


@pytest.mark.experimental
def test_the_volume_contour_is_the_measured_series_expanded_verbatim() -> None:
    profile = _profile_with_volume_gesture(
        {"present": True, "static": False, "runs": [[4, 3], [8, 2]], "unit": "audc_volume_level_0_15"}
    )
    assert profile.volume_gesture["present"] is True
    assert profile.volume_contour == (4, 4, 4, 8, 8)
    assert profile.volume_levels_outside_the_nibble == ()


@pytest.mark.experimental
def test_a_static_or_absent_contour_is_still_the_measured_series() -> None:
    """The accessor reports what was measured; whether it is useful is the consumer's call."""
    static = _profile_with_volume_gesture({"runs": [[6, 5]], "static": True})
    assert static.volume_contour == (6, 6, 6, 6, 6)
    assert _profile_with_volume_gesture({"present": False}).volume_contour is None
    assert _profile_with_volume_gesture({}).volume_contour is None
    assert _profile_with_volume_gesture({"runs": []}).volume_contour is None


@pytest.mark.experimental
def test_a_malformed_or_out_of_range_series_is_refused_not_repaired() -> None:
    """A level outside 0..15 is a corrupt reading, not a value to clamp."""
    assert _profile_with_volume_gesture({"runs": [[4, 3, 9]]}).volume_contour is None
    assert _profile_with_volume_gesture({"runs": [[4.5, 3]]}).volume_contour is None
    assert _profile_with_volume_gesture({"runs": [[True, 3]]}).volume_contour is None
    assert _profile_with_volume_gesture({"runs": [[4, -1]]}).volume_contour is None
    assert _profile_with_volume_gesture({"runs": "nonsense"}).volume_contour is None
    out_of_range = _profile_with_volume_gesture({"runs": [[20, 2], [4, 2]]})
    assert out_of_range.volume_contour is None
    assert out_of_range.volume_levels_outside_the_nibble == (20,)


@pytest.mark.experimental
def test_the_declared_gesture_availability_is_what_the_profile_says() -> None:
    profile = _profile_with_volume_gesture(
        {"runs": [[4, 3]]}, playability={"available": True, "enabled": False}
    )
    assert profile.volume_contour_declared == {"available": True, "enabled": False}
    assert _profile_with_volume_gesture({"runs": [[4, 3]]}).volume_contour_declared == {}


@pytest.mark.core
@pytest.mark.audio
def test_exact_lookup_and_unknown_id_refusal(bank) -> None:
    assert bank.get(VOICE_PROFILE).profile_id == VOICE_PROFILE
    with pytest.raises(SoundProfileError) as err:
        bank.get("pokey_ref_ffffffff")
    assert err.value.code == PROFILE_NOT_FOUND
    # The message must name what the bank does have, so a typo is diagnosable.
    assert VOICE_PROFILE in str(err.value)


@pytest.mark.core
@pytest.mark.audio
def test_missing_bank_directory_is_refused(tmp_path: Path) -> None:
    with pytest.raises(SoundProfileError) as err:
        load_sound_profile_bank(tmp_path / "nope")
    assert err.value.code == PROFILE_BANK_MISSING


@pytest.mark.core
@pytest.mark.audio
def test_unsupported_registry_schema_is_refused(tmp_path: Path) -> None:
    bank_dir = _copy_bank(tmp_path)
    _rewrite_registry(bank_dir, lambda registry: registry.__setitem__("schema", "something/9"))
    with pytest.raises(SoundProfileError) as err:
        load_sound_profile_bank(bank_dir)
    assert err.value.code == PROFILE_BANK_SCHEMA_UNSUPPORTED


@pytest.mark.core
@pytest.mark.audio
def test_tampered_profile_fails_fingerprint_verification(tmp_path: Path) -> None:
    """A profile whose content changed must be refused, not silently rendered."""
    bank_dir = _copy_bank(tmp_path)
    profile_path = bank_dir / "profiles" / f"{VOICE_PROFILE}.json"
    document = json.loads(profile_path.read_text(encoding="utf-8"))
    document["pokey"]["hardware"]["distortion"] = "$C"  # tampered, fingerprint left alone
    profile_path.write_text(json.dumps(document, indent=2), encoding="utf-8")

    with pytest.raises(SoundProfileError) as err:
        load_sound_profile_bank(bank_dir)
    assert err.value.code == PROFILE_FINGERPRINT_MISMATCH
    assert VOICE_PROFILE in str(err.value)

    # The same bank loads fine when the fingerprint is recomputed — proving the check,
    # not the file, was the reason.
    bank = load_sound_profile_bank(bank_dir, verify_fingerprints=False)
    assert bank.get(VOICE_PROFILE).distortion_nibble == 0xC


@pytest.mark.core
@pytest.mark.audio
def test_registry_entry_pointing_at_a_missing_file_is_refused(tmp_path: Path) -> None:
    bank_dir = _copy_bank(tmp_path)
    _rewrite_registry(bank_dir, lambda registry: registry["profiles"][0].__setitem__("file", "profiles/absent.json"))
    with pytest.raises(SoundProfileError) as err:
        load_sound_profile_bank(bank_dir)
    assert err.value.code == PROFILE_FILE_MISSING


@pytest.mark.core
@pytest.mark.audio
def test_profile_id_mismatch_between_registry_and_file_is_refused(tmp_path: Path) -> None:
    bank_dir = _copy_bank(tmp_path)
    _rewrite_registry(
        bank_dir, lambda registry: registry["profiles"][0].__setitem__("profile_id", "pokey_ref_00000000")
    )
    with pytest.raises(SoundProfileError) as err:
        load_sound_profile_bank(bank_dir)
    assert err.value.code in (PROFILE_FILE_MISSING, PROFILE_INVALID)


@pytest.mark.core
@pytest.mark.audio
def test_only_restriction_is_exact(bank) -> None:
    narrowed = load_sound_profile_bank(BANK_DIR, only=(VOICE_PROFILE,))
    assert narrowed.ids() == (VOICE_PROFILE,)
    with pytest.raises(SoundProfileError) as err:
        load_sound_profile_bank(BANK_DIR, only=(VOICE_PROFILE, "pokey_ref_deadbeef"))
    assert err.value.code == PROFILE_NOT_FOUND


@pytest.mark.core
@pytest.mark.audio
@pytest.mark.parametrize(
    ("nibble", "expected"),
    [("$A", 0xA0), ("$8", 0x80), ("$C", 0xC0), ("$0", 0x00), ("$6", 0x60), (0xA, 0xA0), ("A", 0xA0)],
)
def test_distortion_nibble_becomes_the_generator_byte(nibble, expected) -> None:
    """The Stage 8B F2 regression: a nibble is not a byte."""
    document = {
        "schema": "pokey-playable-sound-profile-1.0",
        "profile_id": "x",
        "scope": "VOICE",
        "pokey": {"hardware": {"distortion": nibble}, "channels": {"divider_bits": 8}},
    }
    profile = SoundProfile(profile_id="x", scope="VOICE", fingerprint="f", document=document)
    assert profile.distortion_nibble is not None
    assert profile.distortion_byte == expected


@pytest.mark.core
@pytest.mark.audio
def test_a_verbatim_nibble_copy_is_not_the_generator_byte() -> None:
    """``"$A"`` read as ``0x0A`` would be AUDC $0A: volume only, not pure tone."""
    document = {
        "schema": "pokey-playable-sound-profile-1.0",
        "profile_id": "x",
        "scope": "VOICE",
        "pokey": {"hardware": {"distortion": "$A"}, "channels": {"divider_bits": 8}},
    }
    profile = SoundProfile(profile_id="x", scope="VOICE", fingerprint="f", document=document)
    assert profile.distortion_byte == 0xA0
    assert profile.distortion_nibble == 0x0A
    # The trap: the raw parse of "$A" is $0A, which as AUDC is "volume only" (silence
    # with a zero volume nibble). The generator byte is the nibble in bits 7..5.
    assert profile.distortion_byte != profile.distortion_nibble
    assert (profile.distortion_byte >> 4) == profile.distortion_nibble


@pytest.mark.core
@pytest.mark.audio
def test_loading_a_bank_does_not_need_the_archaeology_project() -> None:
    """The bank is self-sufficient: a bank directory, and nothing else."""
    assert not any(
        name == "pokey_sound_archaeology" or name.startswith("pokey_sound_archaeology.")
        for name in sys.modules
    )
    bank = load_sound_profile_bank(BANK_DIR)
    # Stage 9B replaced the four-profile demo bank with the full published library; the
    # self-sufficiency property is what this test is about, not the bank's size.
    assert len(bank.profiles) == 67
    assert not any(
        name == "pokey_sound_archaeology" or name.startswith("pokey_sound_archaeology.")
        for name in sys.modules
    )


# ===========================================================================
# Level 2 — composition interpretation
# ===========================================================================
@pytest.mark.core
@pytest.mark.audio
def test_binding_document_loads_and_resolves_its_bank_relative_to_itself() -> None:
    binding = load_profile_binding(VAULTS_BINDING)
    assert binding.schema == BINDING_SCHEMA
    assert binding.instruments == {"bass": PAIR_PROFILE, "lead": VOICE_PROFILE}
    # "bank" is relative to the binding file, so the pair can be moved together.
    assert binding.bank_path() == BANK_DIR.resolve()
    # ...and the bank is not looked for relative to the process working directory.
    assert binding.bank_path(None).is_dir()


@pytest.mark.core
@pytest.mark.audio
def test_binding_schema_is_enforced(tmp_path: Path) -> None:
    path = tmp_path / "b.json"
    path.write_text(json.dumps({"schema": "wrong", "instruments": {"lead": VOICE_PROFILE}}), encoding="utf-8")
    with pytest.raises(SoundProfileError) as err:
        load_profile_binding(path)
    assert err.value.code == PROFILE_BINDING_INVALID


@pytest.mark.core
@pytest.mark.audio
def test_binding_without_an_instruments_object_is_invalid() -> None:
    with pytest.raises(SoundProfileError) as err:
        load_profile_binding({"schema": BINDING_SCHEMA})
    assert err.value.code == PROFILE_BINDING_INVALID


@pytest.mark.core
@pytest.mark.audio
def test_an_empty_binding_changes_nothing(vaults_result) -> None:
    same = apply_profile_binding(vaults_result, _binding({}), load_sound_profile_bank(BANK_DIR))
    assert same is vaults_result


@pytest.mark.core
@pytest.mark.audio
def test_a_voice_profile_changes_only_hardware_realization(vaults_doc, vaults_result, bank) -> None:
    bound = apply_profile_binding(vaults_result, _binding({"lead": VOICE_PROFILE}), bank, composition=vaults_doc)

    before = {inst.id: inst for inst in vaults_result.pokey_ir.instruments}
    after = {inst.id: inst for inst in bound.pokey_ir.instruments}
    assert set(before) == set(after)

    # The bound instrument's hardware realization is the profile's.
    lead = after[1]
    assert lead.name == "Lead"
    assert lead.distortion == bank.get(VOICE_PROFILE).distortion_byte == 0x80
    assert lead.audctl == bank.get(VOICE_PROFILE).audctl_mode == 0x00
    assert lead.profile_id == VOICE_PROFILE
    assert lead.profile_fingerprint == bank.get(VOICE_PROFILE).fingerprint

    # Nothing musical moved: same notes, same timings, same roles, same arrangement.
    assert bound.pokey_ir.patterns == vaults_result.pokey_ir.patterns
    assert bound.pokey_ir.sequence == vaults_result.pokey_ir.sequence
    assert bound.pokey_ir.tempo_bpm == vaults_result.pokey_ir.tempo_bpm
    assert bound.pokey_ir.frames_per_tick == vaults_result.pokey_ir.frames_per_tick
    assert bound.pokey_ir.key == vaults_result.pokey_ir.key
    assert bound.pokey_ir.mode == vaults_result.pokey_ir.mode
    assert bound.music_ir == vaults_result.music_ir  # Music IR untouched

    # An unbound instrument is untouched too.
    assert after[0] == before[0]
    assert after[2] == before[2]


@pytest.mark.core
@pytest.mark.audio
def test_the_composition_velocity_remains_authoritative(vaults_doc, vaults_result, bank) -> None:
    """``volume.peak_level`` is evidence about the source, never the note's velocity.

    The envelope's *shape* is the profile's (contract C-5.2), so the sustain level does
    move. What must not move is the level the envelope peaks at, which comes from the
    note's velocity: the composition's dynamics survive.
    """
    bound = apply_profile_binding(vaults_result, _binding({"lead": VOICE_PROFILE}), bank, composition=vaults_doc)

    for original, updated in zip(vaults_result.pokey_ir.patterns, bound.pokey_ir.patterns):
        for channel in original.tracks:
            before = [(note.volume, note.duration, note.midi_pitch) for note in original.tracks[channel]]
            after = [(note.volume, note.duration, note.midi_pitch) for note in updated.tracks[channel]]
            assert before == after

    profile = bank.get(VOICE_PROFILE)
    declared_peak = profile.document["volume"]["peak_level"]
    assert declared_peak != 13, "the fixture must make this distinction observable"

    base_frames = compile_ir_to_pokey_frames(vaults_result.pokey_ir)
    bound_frames = compile_ir_to_pokey_frames(bound.pokey_ir)
    lead_audc = 2 * 3 - 1  # 1-based channel 3 -> column 5
    assert not np.array_equal(base_frames[:, lead_audc], bound_frames[:, lead_audc])

    # The peak level is the note's velocity (V13 in the composition) in both renderings;
    # the profile's own peak_level of 12 was not substituted.
    base_volumes = [int(value) & 0x0F for value in base_frames[:, lead_audc] if value]
    bound_volumes = [int(value) & 0x0F for value in bound_frames[:, lead_audc] if value]
    assert max(base_volumes) == max(bound_volumes) == 13
    assert declared_peak != max(bound_volumes)


@pytest.mark.core
@pytest.mark.audio
def test_a_pair_profile_keeps_the_composition_pitch_and_uses_the_profile_clock(vaults_doc, vaults_result, bank) -> None:
    """The note is the composer's; the profile supplies the clock, not the pitch."""
    bound = apply_profile_binding(vaults_result, _binding({"bass": PAIR_PROFILE}), bank, composition=vaults_doc)
    profile = bank.get(PAIR_PROFILE)

    frames = compile_ir_to_pokey_frames(bound.pokey_ir)
    assert set(frames[:, 8].tolist()) == {0x50}

    # D-2 is the composition's note (midi 38); the divider must be the 1.79 MHz pair
    # arithmetic with the +7 offset, for that note.
    frequency = 440.0 * 2.0 ** ((38 - 69) / 12.0)
    divider = pokey_hw.audf16_from_hz(frequency, profile.audctl_mode, 1)
    low, high = pokey_hw.split_audf16(divider)
    assert frames[0, 0] == low
    assert frames[0, 2] == high

    # The profile's own reference pitch is not the note, and its base divider is evidence.
    assert divider != profile.document["pitch"]["base_divider"]
    assert abs(frequency - float(profile.document["pitch"]["base_hz"])) > 1.0

    # The default (unbound) rendering uses the 64 kHz +1 arithmetic for the same note, so
    # the profile provably changed the divider stream.
    base_frames = compile_ir_to_pokey_frames(vaults_result.pokey_ir)
    assert base_frames[0, 0] != frames[0, 0]
    assert base_frames[0, 2] != frames[0, 2]
    assert base_frames[0, 2] == pokey_hw.split_audf16(
        pokey_hw.audf16_from_hz(frequency, 0, 1)
    )[1]


@pytest.mark.core
@pytest.mark.audio
def test_unbound_channels_are_untouched_by_a_binding(vaults_doc, vaults_result, bank) -> None:
    bound = apply_profile_binding(
        vaults_result, _binding({"bass": PAIR_PROFILE, "lead": VOICE_PROFILE}), bank, composition=vaults_doc
    )
    base_frames = compile_ir_to_pokey_frames(vaults_result.pokey_ir)
    bound_frames = compile_ir_to_pokey_frames(bound.pokey_ir)

    # Channel 4 (percussion) is not bound: neither its divider nor its generator moved.
    np.testing.assert_array_equal(base_frames[:, 6], bound_frames[:, 6])
    np.testing.assert_array_equal(base_frames[:, 7], bound_frames[:, 7])


@pytest.mark.core
@pytest.mark.audio
def test_the_provenance_is_recorded_on_the_result(vaults_doc, vaults_result, bank) -> None:
    bound = apply_profile_binding(
        vaults_result, _binding({"bass": PAIR_PROFILE, "lead": VOICE_PROFILE}), bank, composition=vaults_doc
    )
    recorded = {entry["instrument"]: entry for entry in bound.metadata.sound_profiles}
    assert set(recorded) == {"bass", "lead"}
    assert recorded["bass"]["profile_id"] == PAIR_PROFILE
    assert recorded["bass"]["profile_fingerprint"] == bank.get(PAIR_PROFILE).fingerprint
    assert recorded["bass"]["scope"] == "PAIR"
    assert recorded["lead"]["profile_id"] == VOICE_PROFILE
    assert bound.metadata.uses_16bit_bass is True
    # The unbound result carries no provenance at all.
    assert vaults_result.metadata.sound_profiles == []


@pytest.mark.core
@pytest.mark.audio
def test_binding_is_deterministic(vaults_doc, vaults_result, bank) -> None:
    binding = _binding({"bass": PAIR_PROFILE, "lead": VOICE_PROFILE})
    first = apply_profile_binding(vaults_result, binding, bank, composition=vaults_doc)
    second = apply_profile_binding(vaults_result, binding, bank, composition=vaults_doc)
    assert first.pokey_ir.model_dump() == second.pokey_ir.model_dump()
    assert np.array_equal(
        compile_ir_to_pokey_frames(first.pokey_ir), compile_ir_to_pokey_frames(second.pokey_ir)
    )


@pytest.mark.core
@pytest.mark.audio
def test_unknown_instrument_is_refused(vaults_result, bank) -> None:
    with pytest.raises(SoundProfileError) as err:
        apply_profile_binding(
            vaults_result, _binding({"trumpet": VOICE_PROFILE}), bank, composition=None
        )
    assert err.value.code == PROFILE_BINDING_UNKNOWN_INSTRUMENT


@pytest.mark.core
@pytest.mark.audio
def test_unknown_profile_id_is_refused(vaults_doc, vaults_result, bank) -> None:
    with pytest.raises(SoundProfileError) as err:
        apply_profile_binding(
            vaults_result, _binding({"lead": "pokey_ref_00000000"}), bank, composition=vaults_doc
        )
    assert err.value.code == PROFILE_NOT_FOUND


@pytest.mark.core
@pytest.mark.audio
def test_a_pair_profile_needs_the_pair_s_low_channel(bank) -> None:
    """A PAIR profile is driven from channel 1; notes on any other channel are refused."""
    doc = _composition(
        channels={"2": _one_note("harm")},
        use_16bit_bass=True,
    )
    result = generate_music_from_composition(doc)
    with pytest.raises(SoundProfileError) as err:
        apply_profile_binding(result, _binding({"harm": PAIR_PROFILE}), bank, composition=doc)
    assert err.value.code == PROFILE_CHANNEL_REQUIREMENT
    assert "channel" in str(err.value)


@pytest.mark.core
@pytest.mark.audio
def test_a_pair_profile_refuses_independent_notes_on_channel_two(bank) -> None:
    """Channel 2 becomes the pair's high byte, so nothing else may live there."""
    doc = _composition(
        channels={"1": _one_note("bass"), "2": _one_note("harm")},
        use_16bit_bass=True,
    )
    result = generate_music_from_composition(doc)
    with pytest.raises(SoundProfileError) as err:
        apply_profile_binding(result, _binding({"bass": PAIR_PROFILE}), bank, composition=doc)
    assert err.value.code == PROFILE_PAIR_CHANNEL_CONFLICT
    # The composition validator already has a code for exactly this collision.
    assert err.value.detail.get("existing_code") == "BASS16_CHANNEL_CONFLICT"


@pytest.mark.core
@pytest.mark.audio
def test_two_pair_profiles_cannot_share_one_pair(bank) -> None:
    """The composer has exactly one joined pair, so two PAIR profiles cannot coexist.

    Both instruments must sound on channel 1 for the pair check to be the one that fires,
    which is what alternating patterns produce here.
    """
    doc = AICompositionDoc(
        metadata=AICompositionMetadata(title="Two Pairs", bpm=120, key="C", mode="minor"),
        hardware=AIHardwareConfig(channels=4, use_16bit_bass=True),
        instruments=[
            AIInstrumentDef(id="bass", name="Bass", character="bass"),
            AIInstrumentDef(id="harm", name="Harmony", character="soft_pad"),
        ],
        patterns=[
            AIPatternDef(id="A", length_steps=16, channels={"1": _one_note("bass")}),
            AIPatternDef(id="B", length_steps=16, channels={"1": _one_note("harm")}),
        ],
        sequence=["A", "B"],
        loop_point=0,
    )
    result = generate_music_from_composition(doc)
    with pytest.raises(SoundProfileError) as err:
        apply_profile_binding(
            result, _binding({"bass": PAIR_PROFILE, "harm": PAIR_PROFILE_ALT}), bank, composition=doc
        )
    assert err.value.code == PROFILE_PAIR_CHANNEL_CONFLICT
    assert "one joined pair" in str(err.value)


@pytest.mark.core
@pytest.mark.audio
def test_audctl_conflict_is_refused_when_the_channel_cannot_carry_the_profile(bank) -> None:
    """A 64 kHz VOICE profile on a channel the song joins as a 16-bit pair is a conflict."""
    doc = _composition(channels={"1": _one_note("bass")}, use_16bit_bass=True)
    result = generate_music_from_composition(doc)
    with pytest.raises(SoundProfileError) as err:
        apply_profile_binding(result, _binding({"bass": VOICE_PROFILE}), bank, composition=doc)
    assert err.value.code == PROFILE_AUDCTL_CONFLICT
    assert "join bit" in str(err.value)


@pytest.mark.core
@pytest.mark.audio
def test_a_voice_profile_on_an_unaffected_channel_is_fine(bank, vaults_doc, vaults_result) -> None:
    """Channel 3 is untouched by a 1+2 join, so a 64 kHz profile is satisfiable there."""
    bound = apply_profile_binding(
        vaults_result, _binding({"bass": PAIR_PROFILE, "lead": VOICE_PROFILE}), bank, composition=vaults_doc
    )
    assert resolve_audctl_mode(bound.pokey_ir) == 0x50
    frames = compile_ir_to_pokey_frames(bound.pokey_ir)
    # Channel 3 is not joined, so it keeps the 64 kHz arithmetic.
    base_frames = compile_ir_to_pokey_frames(vaults_result.pokey_ir)
    np.testing.assert_array_equal(base_frames[:, 4], frames[:, 4])


@pytest.mark.core
@pytest.mark.audio
def test_explicit_distortion_that_disagrees_is_refused(bank) -> None:
    doc = _composition(
        channels={"1": _one_note("lead")},
        instruments=[AIInstrumentDef(id="lead", name="Lead", character="bright_lead", distortion=0xA0)],
    )
    result = generate_music_from_composition(doc)
    with pytest.raises(SoundProfileError) as err:
        apply_profile_binding(result, _binding({"lead": VOICE_PROFILE}), bank, composition=doc)
    assert err.value.code == PROFILE_DISTORTION_CONFLICT
    assert "$80" in str(err.value)


@pytest.mark.core
@pytest.mark.audio
def test_explicit_distortion_that_agrees_is_accepted(bank) -> None:
    doc = _composition(
        channels={"1": _one_note("lead")},
        instruments=[AIInstrumentDef(id="lead", name="Lead", character="bright_lead", distortion=0x80)],
    )
    result = generate_music_from_composition(doc)
    bound = apply_profile_binding(result, _binding({"lead": VOICE_PROFILE}), bank, composition=doc)
    assert bound.pokey_ir.instruments[0].distortion == 0x80
    report = describe_binding(result, _binding({"lead": VOICE_PROFILE}), bank, composition=doc)
    assert report["instruments"][0]["distortion_source"].startswith("profile (agrees")


@pytest.mark.core
@pytest.mark.audio
def test_an_explicit_composition_envelope_wins_over_the_profile(bank) -> None:
    """Contract C-5.2: the composition's explicit envelope is never overwritten."""
    doc = _composition(
        channels={"1": _one_note("lead")},
        instruments=[
            AIInstrumentDef(
                id="lead", name="Lead", character="bright_lead", attack_frames=7, sustain_vol=2
            )
        ],
    )
    result = generate_music_from_composition(doc)
    binding = _binding({"lead": VOICE_PROFILE})
    bound = apply_profile_binding(result, binding, bank, composition=doc)
    envelope = bound.pokey_ir.instruments[0].envelope
    profile_frames = bank.get(VOICE_PROFILE).envelope_frames

    assert envelope.attack_frames == 7  # explicit, despite the profile measuring 0
    assert envelope.attack_frames != profile_frames["attack"]
    assert envelope.sustain_vol == 2

    report = describe_binding(result, binding, bank, composition=doc)["instruments"][0]["envelope"]
    assert report["attack_frames"]["source"] == "composition"
    assert report["decay_frames"]["source"] == "profile"  # not declared, so the profile fills it
    assert report["decay_frames"]["value"] == profile_frames["decay"]


@pytest.mark.core
@pytest.mark.audio
def test_an_unexpressible_profile_envelope_is_refused(tmp_path: Path) -> None:
    """Rather than clamp a requested envelope, the binding refuses it."""
    bank_dir = _copy_bank(tmp_path)
    _rewrite_profile(bank_dir, VOICE_PROFILE, lambda doc: doc["envelope"]["frames"].__setitem__("attack", 25))
    peak_bank = load_sound_profile_bank(bank_dir)

    doc = _composition(channels={"1": _one_note("lead")})
    result = generate_music_from_composition(doc)
    with pytest.raises(SoundProfileError) as err:
        apply_profile_binding(result, _binding({"lead": VOICE_PROFILE}), peak_bank, composition=doc)
    assert err.value.code == PROFILE_ENVELOPE_OUT_OF_RANGE
    assert "25" in str(err.value)


@pytest.mark.core
@pytest.mark.audio
def test_describe_binding_reports_the_same_configuration_it_applies(vaults_doc, vaults_result, bank) -> None:
    binding = _binding({"bass": PAIR_PROFILE, "lead": VOICE_PROFILE})
    report = describe_binding(vaults_result, binding, bank, composition=vaults_doc)
    applied = apply_profile_binding(vaults_result, binding, bank, composition=vaults_doc)

    assert report["audctl"] == resolve_audctl_mode(applied.pokey_ir) == 0x50
    assert report["uses_16bit_bass"] is True
    entries = {entry["instrument"]: entry for entry in report["instruments"]}
    assert entries["bass"]["divider_bits"] == 16
    assert entries["lead"]["divider_bits"] == 8
    # The reported generator byte is the one the frames actually carry on the audible channel.
    frames = compile_ir_to_pokey_frames(applied.pokey_ir)
    assert entries["bass"]["distortion_audc"] == "$C0"
    assert set((frames[:, 3] & 0xE0).tolist()) == {0xC0}
    assert entries["lead"]["distortion_audc"] == "$80"
    # Silent frames carry AUDC 0, so compare only the sounding ones.
    assert set((frames[:, 5] & 0xE0).tolist()) - {0x00} == {0x80}


@pytest.mark.core
@pytest.mark.audio
def test_a_bank_without_a_binding_does_not_need_a_path(vaults_result, bank) -> None:
    """A binding that carries its own bank path needs no --sound-bank argument."""
    binding = load_profile_binding(VAULTS_BINDING)
    assert binding.bank_path(None) == BANK_DIR.resolve()


# ===========================================================================
# Level 3 — end to end
# ===========================================================================
@pytest.mark.core
@pytest.mark.audio
def test_import_dsl_with_a_binding_renders_a_profile_bound_wav(tmp_path: Path) -> None:
    runner = CliRunner()
    out = tmp_path / "bound.wav"
    result = runner.invoke(
        cli,
        [
            "import-dsl",
            str(VAULTS_DSL),
            "--output-wav",
            str(out),
            "--sound-bank",
            str(BANK_DIR),
            "--profile-bindings",
            str(VAULTS_BINDING),
        ],
    )
    assert result.exit_code == 0, result.output
    assert "Applying sound profile binding" in result.output
    assert PAIR_PROFILE in result.output
    assert "effective AUDCTL $50" in result.output
    assert out.exists()

    samples = _wav_samples(out)
    assert max(abs(sample) for sample in samples) > 0, "the rendered WAV must not be silent"


@pytest.mark.core
@pytest.mark.audio
def test_the_bound_wav_differs_from_the_unbound_wav(tmp_path: Path) -> None:
    """The A/B proof that a profile is not decorative metadata."""
    runner = CliRunner()
    default_wav = tmp_path / "default.wav"
    bound_wav = tmp_path / "bound.wav"

    assert runner.invoke(cli, ["import-dsl", str(VAULTS_DSL), "--output-wav", str(default_wav)]).exit_code == 0
    assert (
        runner.invoke(
            cli,
            [
                "import-dsl",
                str(VAULTS_DSL),
                "--output-wav",
                str(bound_wav),
                "--sound-bank",
                str(BANK_DIR),
                "--profile-bindings",
                str(VAULTS_BINDING),
            ],
        ).exit_code
        == 0
    )

    default_samples = _wav_samples(default_wav)
    bound_samples = _wav_samples(bound_wav)
    assert len(default_samples) == len(bound_samples)
    assert default_samples != bound_samples
    differing = sum(1 for left, right in zip(default_samples, bound_samples) if left != right)
    assert differing > len(default_samples) // 2


@pytest.mark.core
@pytest.mark.audio
def test_the_exported_assembly_matches_the_frame_stream(vaults_doc, vaults_result, bank) -> None:
    """WAV and XEX must derive from one profile-aware representation."""
    bound = apply_profile_binding(
        vaults_result, _binding({"bass": PAIR_PROFILE, "lead": VOICE_PROFILE}), bank, composition=vaults_doc
    )
    frames = compile_ir_to_pokey_frames(bound.pokey_ir)
    asm = export_mads_asm(bound.pokey_ir)

    audctl_lines = [line for line in asm.splitlines() if "audctl_mode" in line]
    assert audctl_lines, "the exported header must publish the AUDCTL it writes"
    published = int(audctl_lines[0].split(";")[0].strip().lstrip(".byte").strip().lstrip("$"), 16)
    assert published == resolve_audctl_mode(bound.pokey_ir) == 0x50
    assert set(frames[:, 8].tolist()) == {published}

    # The instrument table publishes the same generator the frame stream carries.
    table = [line for line in asm.splitlines() if line.strip().startswith(".byte $c0")]
    assert table, asm[:400]
    ch2_audc = set((frames[:, 3] & 0xE0).tolist())
    assert ch2_audc == {0xC0}
    assert "$c0" in table[0]


@pytest.mark.core
@pytest.mark.audio
def test_the_assembly_header_no_longer_misreports_the_audctl(vaults_result) -> None:
    """The header used to claim ``$50`` for a song that writes ``$10``."""
    asm = export_mads_asm(vaults_result.pokey_ir)
    mode_line = next(line for line in asm.splitlines() if line.startswith("; Mode:"))
    assert "$10" in mode_line
    assert "$50" not in mode_line
    assert "64 kHz" in mode_line
    data_line = next(line for line in asm.splitlines() if "audctl_mode" in line)
    assert "$10" in data_line


@pytest.mark.core
@pytest.mark.audio
def test_build_xex_applies_the_binding_to_the_exported_data(tmp_path: Path, monkeypatch) -> None:
    """The XEX path uses the same profile-aware IR as the WAV path."""
    from atari_music.ai import client as client_module

    captured: Dict[str, Any] = {}
    real_export = client_module.export_mads_asm

    def capturing_export(result, *args, **kwargs):
        song = result.pokey_ir if hasattr(result, "pokey_ir") else result
        captured["audctl"] = resolve_audctl_mode(song)
        captured["instruments"] = [(inst.distortion, inst.audctl, inst.profile_id) for inst in song.instruments]
        return real_export(result, *args, **kwargs)

    monkeypatch.setattr(client_module, "export_mads_asm", capturing_export)

    dummy_mads = tmp_path / "mads.exe"
    dummy_mads.write_text("dummy", encoding="utf-8")

    def fake_run(cmd, capture_output=True, text=True, **kwargs):
        for arg in cmd:
            if arg.startswith("-o:"):
                Path(arg[3:]).write_bytes(fake_xex_bytes())
        proc = MagicMock()
        proc.returncode = 0
        proc.stdout = "OK"
        proc.stderr = ""
        return proc

    monkeypatch.setattr(subprocess, "run", fake_run)

    runner = CliRunner()
    out_xex = tmp_path / "bound.xex"
    result = runner.invoke(
        cli,
        [
            "build-xex",
            str(VAULTS_DSL),
            "--format",
            "dsl",
            "-o",
            str(out_xex),
            "--mads",
            str(dummy_mads),
            "--player-asm",
            str(REPO_ROOT / "player.asm"),
            "--sound-bank",
            str(BANK_DIR),
            "--profile-bindings",
            str(VAULTS_BINDING),
        ],
    )
    assert result.exit_code == 0, result.output
    assert out_xex.exists()
    assert captured["audctl"] == 0x50, "the exported data must carry the profile's AUDCTL"
    assert (0xC0, 0x50, PAIR_PROFILE) in captured["instruments"]
    # The intermediate assembly the XEX was built from is written next to the output.
    asm = out_xex.with_suffix(".asm").read_text(encoding="utf-8")
    assert ".byte $50" in asm
    assert "$50" in next(line for line in asm.splitlines() if line.startswith("; Mode:"))


@pytest.mark.core
@pytest.mark.audio
def test_sound_bank_without_bindings_is_refused(tmp_path: Path) -> None:
    runner = CliRunner()
    result = runner.invoke(
        cli,
        ["import-dsl", str(VAULTS_DSL), "--output-wav", str(tmp_path / "x.wav"), "--sound-bank", str(BANK_DIR)],
    )
    assert result.exit_code != 0
    assert "--profile-bindings" in result.output


@pytest.mark.core
@pytest.mark.audio
def test_an_unknown_profile_id_fails_the_cli_with_its_code(tmp_path: Path) -> None:
    binding_path = tmp_path / "bad.json"
    binding_path.write_text(
        json.dumps({"schema": BINDING_SCHEMA, "bank": str(BANK_DIR), "instruments": {"lead": "pokey_ref_00000000"}}),
        encoding="utf-8",
    )
    runner = CliRunner()
    result = runner.invoke(
        cli,
        [
            "import-dsl",
            str(VAULTS_DSL),
            "--output-wav",
            str(tmp_path / "x.wav"),
            "--profile-bindings",
            str(binding_path),
        ],
    )
    assert result.exit_code != 0
    assert PROFILE_NOT_FOUND in result.output


@pytest.mark.core
@pytest.mark.audio
def test_a_tampered_bank_fails_the_cli(tmp_path: Path) -> None:
    bank_dir = _copy_bank(tmp_path)
    profile_path = bank_dir / "profiles" / f"{VOICE_PROFILE}.json"
    document = json.loads(profile_path.read_text(encoding="utf-8"))
    document["pokey"]["hardware"]["distortion"] = "$0"
    profile_path.write_text(json.dumps(document, indent=2), encoding="utf-8")

    binding_path = tmp_path / "b.json"
    binding_path.write_text(
        json.dumps({"schema": BINDING_SCHEMA, "bank": str(bank_dir), "instruments": {"lead": VOICE_PROFILE}}),
        encoding="utf-8",
    )
    runner = CliRunner()
    result = runner.invoke(
        cli,
        [
            "import-dsl",
            str(VAULTS_DSL),
            "--output-wav",
            str(tmp_path / "x.wav"),
            "--profile-bindings",
            str(binding_path),
        ],
    )
    assert result.exit_code != 0
    assert PROFILE_FINGERPRINT_MISMATCH in result.output


@pytest.mark.core
@pytest.mark.audio
def test_two_runs_with_the_same_inputs_are_byte_identical(tmp_path: Path) -> None:
    runner = CliRunner()
    outputs = []
    for name in ("first.wav", "second.wav"):
        out = tmp_path / name
        result = runner.invoke(
            cli,
            [
                "import-dsl",
                str(VAULTS_DSL),
                "--output-wav",
                str(out),
                "--output-asm",
                str(out.with_suffix(".asm")),
                "--sound-bank",
                str(BANK_DIR),
                "--profile-bindings",
                str(VAULTS_BINDING),
            ],
        )
        assert result.exit_code == 0, result.output
        outputs.append(out.read_bytes())
    assert outputs[0] == outputs[1]

    asm_first = (tmp_path / "first.asm").read_bytes()
    asm_second = (tmp_path / "second.asm").read_bytes()
    assert asm_first == asm_second


@pytest.mark.core
@pytest.mark.audio
def test_the_pokey_ir_json_round_trips_with_and_without_the_new_fields(tmp_path: Path, vaults_doc, vaults_result, bank) -> None:
    """The exported IR stays loadable, and a document from before this stage still loads.

    The "before" direction is checked on an **unbound** result: its new fields are ``None``
    anyway, so removing the keys must change nothing. (Removing them from a *bound*
    document would drop the profile's AUDCTL requirement while keeping its distortion —
    a lossy edit of the document, not a rendering bug.)
    """
    from atari_music.ir import IRSong

    bound = apply_profile_binding(
        vaults_result, _binding({"bass": PAIR_PROFILE}), bank, composition=vaults_doc
    )
    written = tmp_path / "bound_ir.json"
    bound.pokey_ir.to_json_file(written)
    assert IRSong.from_json_file(written).model_dump() == bound.pokey_ir.model_dump()
    assert '"audctl"' in written.read_text(encoding="utf-8")

    unbound_path = tmp_path / "unbound_ir.json"
    vaults_result.pokey_ir.to_json_file(unbound_path)
    legacy_data = json.loads(unbound_path.read_text(encoding="utf-8"))
    for instrument in legacy_data["instruments"]:
        for key in ("audctl", "profile_id", "profile_fingerprint"):
            assert instrument[key] is None
            instrument.pop(key)
    legacy_path = tmp_path / "legacy_ir.json"
    legacy_path.write_text(json.dumps(legacy_data), encoding="utf-8")

    legacy = IRSong.from_json_file(legacy_path)
    assert len(legacy.instruments) == len(vaults_result.pokey_ir.instruments)
    for instrument in legacy.instruments:
        assert (instrument.audctl, instrument.profile_id, instrument.profile_fingerprint) == (
            None,
            None,
            None,
        )
    np.testing.assert_array_equal(
        compile_ir_to_pokey_frames(legacy), compile_ir_to_pokey_frames(vaults_result.pokey_ir)
    )


@pytest.mark.core
@pytest.mark.audio
def test_real_mads_xex_build(tmp_path: Path) -> None:
    """The full XEX build with the real assembler, when this checkout has one."""
    mads = REPO_ROOT / "tools" / "mads" / "mads.exe"
    if not mads.exists():
        pytest.skip("MADS assembler not present in this checkout")
    player = REPO_ROOT / "player.asm"
    if not player.exists():
        pytest.skip("player.asm not present in this checkout")

    runner = CliRunner()
    out = tmp_path / "vaults.xex"
    result = runner.invoke(
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
    assert out.exists()
    assert out.stat().st_size > 0
    assert out.read_bytes().startswith(b"\xff\xff"), "an Atari XEX starts with the FFFF header"

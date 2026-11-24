"""CORE unit tests for Stage A SSOT Pydantic v2 models and JSON catalog loader."""

from __future__ import annotations

import json
import subprocess
import sys
from importlib import resources
from pathlib import Path
from typing import Any, Dict

import pytest
from pydantic import ValidationError

import atari_music.instruments.catalog as catalog_mod

from atari_music.instruments import (
    CATALOG_INTEGRITY_ERROR,
    CATALOG_JSON_INVALID,
    CATALOG_NOT_FOUND,
    CATALOG_SCHEMA_ID,
    CATALOG_SCHEMA_UNSUPPORTED,
    DEFAULT_CATALOG_PATH,
    INSTRUMENT_NOT_FOUND,
    CatalogError,
    EnvelopeSpec,
    HardwareConstraints,
    InstrumentBehavior,
    InstrumentProfile,
    InstrumentProvenance,
    PerformanceSpec,
    PitchEnvelopeSpec,
    TransientMacroSpec,
    TransientMacroStep,
    VibratoSpec,
    load_instrument_catalog,
    validate_instrument_catalog,
)

pytestmark = pytest.mark.core

REPO_ROOT = Path(__file__).resolve().parents[1]
BANK_DIR = REPO_ROOT / "tests" / "data" / "sound_profiles" / "bank"


def _minimal_raw_catalog() -> Dict[str, Any]:
    return {
        "schema_id": CATALOG_SCHEMA_ID,
        "catalog_version": "0.1.0",
        "behaviors": [
            {
                "behavior_id": "beh_static_v1",
                "version": 1,
                "required_runtime_tier": "core_v1",
                "modulation_mode": "none",
                "allow_per_note_switch": False,
            }
        ],
        "instruments": [
            {
                "instrument_id": "test_lead",
                "display_name": "Test Lead",
                "version": "1.0",
                "family": "lead",
                "intended_roles": ["melody"],
                "base_distortion": 0xA0,
                "envelope": {
                    "attack_frames": 0,
                    "decay_frames": 4,
                    "sustain_vol": 10,
                    "release_frames": 2,
                    "peak_vol": 15,
                },
                "waveform_family": "pure",
                "hardware_constraints": {
                    "divider_mode": "8bit",
                    "preferred_clock_hz": "64khz",
                    "required_audctl_bits": 0,
                    "forbidden_audctl_bits": 0,
                    "poly4_safe_tuning": False,
                    "midi_range": [48, 96],
                    "channels_allowed": [1, 2, 3, 4],
                },
                "behavior_id": "beh_static_v1",
                "provenance": {
                    "source_kind": "curated_preset",
                },
            }
        ],
    }


def test_package_import_has_no_io_or_non_core_side_effects() -> None:
    code = (
        "import sys; "
        "import atari_music.instruments as ins; "
        "bad = [m for m in sys.modules if any(k in m for k in ('stage15', 'composer_v2', 'generator'))]; "
        "assert not bad, bad; "
        "assert ins.CATALOG_SCHEMA_ID == 'atari-music/instrument-catalog/1'"
    )
    env = {"PYTHONPATH": str(REPO_ROOT / "src")}
    res = subprocess.run([sys.executable, "-c", code], env=env, capture_output=True, text=True, check=False)
    assert res.returncode == 0, res.stderr or res.stdout


def test_models_are_frozen_and_forbid_extra_fields() -> None:
    env = EnvelopeSpec(attack_frames=1, decay_frames=2, sustain_vol=8, release_frames=3)
    with pytest.raises(ValidationError):
        env.sustain_vol = 9  # type: ignore[misc]

    with pytest.raises(ValidationError):
        EnvelopeSpec(attack_frames=1, decay_frames=2, sustain_vol=8, release_frames=3, unknown=1)  # type: ignore[call-arg]

    assert PerformanceSpec is InstrumentBehavior


def test_model_range_and_bitmask_validations() -> None:
    # Bad distortion nibbles (low volume bits, DAC-only $10, or out of range)
    for bad_dist in (0xA5, 0x10, 0x100, -1):
        with pytest.raises(ValidationError):
            InstrumentProfile.model_validate(
                {**_minimal_raw_catalog()["instruments"][0], "base_distortion": bad_dist}
            )

    # Overlapping required and forbidden AUDCTL bits
    with pytest.raises(ValidationError):
        HardwareConstraints(required_audctl_bits=0x01, forbidden_audctl_bits=0x01)

    # Bad MIDI range / channel / 16-bit channel pairing mismatch
    with pytest.raises(ValidationError):
        HardwareConstraints(midi_range=(72, 48))
    with pytest.raises(ValidationError):
        HardwareConstraints(channels_allowed=(1, 5))
    with pytest.raises(ValidationError):
        HardwareConstraints(
            divider_mode="16bit_ch12",
            required_audctl_bits=0x10,
            channels_allowed=(2, 3),
        )
    with pytest.raises(ValidationError):
        HardwareConstraints(
            divider_mode="16bit_ch34",
            required_audctl_bits=0x08,
            channels_allowed=(1, 4),
        )

    # Valid 16-bit CH1+CH2 and CH3+CH4 declarations (preserving non-join AUDCTL bits)
    hc_12 = HardwareConstraints(
        divider_mode="16bit_ch12",
        required_audctl_bits=0x50,
        channels_allowed=(1,),
    )
    assert hc_12.required_audctl_bits == 0x50
    hc_34 = HardwareConstraints(
        divider_mode="16bit_ch34",
        required_audctl_bits=0x28,
        channels_allowed=(3,),
    )
    assert hc_34.required_audctl_bits == 0x28
    hc_8bit_clocked = HardwareConstraints(
        divider_mode="8bit",
        required_audctl_bits=0x41,
        channels_allowed=(1,),
    )
    assert hc_8bit_clocked.required_audctl_bits == 0x41

    # Contradictions between divider_mode and required_audctl_bits
    for bad_mode, bad_bits, chans in (
        ("8bit", 0x10, (1,)),
        ("8bit", 0x08, (3,)),
        ("16bit_ch12", 0x00, (1,)),
        ("16bit_ch12", 0x40, (1,)),
        ("16bit_ch12", 0x08, (1,)),
        ("16bit_ch12", 0x18, (1,)),
        ("16bit_ch34", 0x00, (3,)),
        ("16bit_ch34", 0x20, (3,)),
        ("16bit_ch34", 0x10, (3,)),
        ("16bit_ch34", 0x18, (3,)),
    ):
        with pytest.raises(ValidationError):
            HardwareConstraints(
                divider_mode=bad_mode,
                required_audctl_bits=bad_bits,
                channels_allowed=chans,
            )

    # Macro limits (>8 steps, ambiguous fixed_audf + audf_offset, bad distortion)
    step = TransientMacroStep(duration_frames=1, distortion_nibble=0xA0, audf_offset=0, volume=12)
    assert step.distortion_nibble == 0xA0
    with pytest.raises(ValidationError):
        TransientMacroStep(duration_frames=1, audf_offset=-2, fixed_audf=40)
    with pytest.raises(ValidationError):
        TransientMacroSpec(steps=(step,) * 9)

    # Pitch envelope & vibrato ranges
    PitchEnvelopeSpec(start_audf_delta=-20, duration_frames=4, step_delta=5)
    with pytest.raises(ValidationError):
        PitchEnvelopeSpec(start_audf_delta=0, duration_frames=16, step_delta=0)
    VibratoSpec(delay_frames=8, depth_audf=2, rate_frames=3)
    with pytest.raises(ValidationError):
        VibratoSpec(delay_frames=64, depth_audf=1, rate_frames=1)

    # Provenance constraints for bank references
    with pytest.raises(ValidationError):
        InstrumentProvenance(source_kind="sound_profile_bank", profile_id="pokey_ref_25f94201")
    with pytest.raises(ValidationError):
        InstrumentProvenance(
            source_kind="sound_profile_bank",
            profile_id="pokey_ref_25f94201",
            profile_fingerprint="not-sha256",
        )


def test_behavior_tier_and_static_profile_separation() -> None:
    # Transient macro cannot target core_v1, vibrato cannot target core_v2_iter1
    with pytest.raises(ValidationError):
        InstrumentBehavior(
            behavior_id="bad_v1_macro",
            required_runtime_tier="core_v1",
            transient_macro=TransientMacroSpec(steps=(TransientMacroStep(duration_frames=1),)),
        )
    with pytest.raises(ValidationError):
        InstrumentBehavior(
            behavior_id="bad_vib_iter1",
            required_runtime_tier="core_v2_iter1",
            vibrato=VibratoSpec(delay_frames=4, depth_audf=1, rate_frames=2),
        )
    # Static bell profile validates independently even if a behavior adds deferred arpeggio
    arp_beh = InstrumentBehavior(
        behavior_id="bell_arp",
        required_runtime_tier="experimental_deferred",
        arpeggio_offsets=(0, 4, 7),
    )
    assert arp_beh.required_runtime_tier == "experimental_deferred"


def test_default_catalog_loads_from_any_cwd_with_verified_provenance(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    catalog = load_instrument_catalog(bank_dir=BANK_DIR)
    assert catalog.schema_id == CATALOG_SCHEMA_ID
    assert 14 <= len(catalog.instruments) <= 22
    assert len(catalog.instruments) == 20
    assert len(catalog.behaviors) >= 8

    # Deterministic JSON serialization round-trip
    json_a = catalog.to_deterministic_json()
    json_b = load_instrument_catalog(DEFAULT_CATALOG_PATH).to_deterministic_json()
    assert json_a == json_b

    # Query helpers
    perc = catalog.list_profiles(family="percussion")
    assert len(perc) == 8
    kick, kick_beh = catalog.resolve_profile_behavior("perc_kick_tight")
    assert kick.hardware_constraints.channels_allowed == (4,)
    assert kick_beh is not None and kick_beh.allow_per_note_switch is True


def test_catalog_integrity_and_provenance_error_cases(tmp_path: Path) -> None:
    # Missing file
    with pytest.raises(CatalogError) as exc_missing:
        load_instrument_catalog(tmp_path / "missing.json")
    assert exc_missing.value.code == CATALOG_NOT_FOUND

    # Invalid JSON
    bad_json = tmp_path / "bad.json"
    bad_json.write_text("{broken", encoding="utf-8")
    with pytest.raises(CatalogError) as exc_json:
        load_instrument_catalog(bad_json)
    assert exc_json.value.code == CATALOG_JSON_INVALID

    # Wrong schema_id
    wrong_schema = _minimal_raw_catalog()
    wrong_schema["schema_id"] = "atari-music/instrument-catalog/999"
    with pytest.raises(CatalogError) as exc_schema:
        validate_instrument_catalog(wrong_schema)
    assert exc_schema.value.code == CATALOG_SCHEMA_UNSUPPORTED

    # Duplicate instrument_id
    dup_inst = _minimal_raw_catalog()
    dup_inst["instruments"].append(dict(dup_inst["instruments"][0]))
    with pytest.raises(CatalogError) as exc_dup:
        validate_instrument_catalog(dup_inst)
    assert exc_dup.value.code == CATALOG_INTEGRITY_ERROR

    # Duplicate behavior_id
    dup_beh = _minimal_raw_catalog()
    dup_beh["behaviors"].append(dict(dup_beh["behaviors"][0]))
    with pytest.raises(CatalogError) as exc_dup_beh:
        validate_instrument_catalog(dup_beh)
    assert exc_dup_beh.value.code == CATALOG_INTEGRITY_ERROR

    # Dangling behavior_id
    dangling = _minimal_raw_catalog()
    dangling["instruments"][0]["behavior_id"] = "nonexistent_beh"
    with pytest.raises(CatalogError) as exc_dangle:
        validate_instrument_catalog(dangling)
    assert exc_dangle.value.code == CATALOG_INTEGRITY_ERROR

    # Missing instrument lookup
    catalog = load_instrument_catalog()
    with pytest.raises(CatalogError) as exc_lookup:
        catalog.get_profile("no_such_instrument")
    assert exc_lookup.value.code == INSTRUMENT_NOT_FOUND

    # Bad provenance fingerprint against real read-only bank
    bad_prov = _minimal_raw_catalog()
    bad_prov["instruments"][0]["provenance"] = {
        "source_kind": "sound_profile_bank",
        "profile_id": "pokey_ref_25f94201",
        "profile_fingerprint": "0" * 64,
    }
    bad_prov_path = tmp_path / "bad_prov.json"
    bad_prov_path.write_text(json.dumps(bad_prov), encoding="utf-8")
    with pytest.raises(CatalogError) as exc_prov:
        validate_instrument_catalog(bad_prov_path, bank_dir=BANK_DIR)
    assert exc_prov.value.code == CATALOG_INTEGRITY_ERROR


def test_catalog_importlib_resources_fallback_without_repo_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(catalog_mod, "_REPO_ROOT", tmp_path / "no_repo")

    assert validate_instrument_catalog() == []
    assert validate_instrument_catalog(DEFAULT_CATALOG_PATH) == []

    cat_none = load_instrument_catalog()
    cat_default = load_instrument_catalog(DEFAULT_CATALOG_PATH)
    assert cat_none.to_deterministic_json() == cat_default.to_deterministic_json()
    assert len(cat_none.instruments) == 20

    with pytest.raises(CatalogError) as exc_missing:
        load_instrument_catalog(tmp_path / "missing.json")
    assert exc_missing.value.code == CATALOG_NOT_FOUND


def test_packaged_asm_player_accessible_via_importlib_resources() -> None:
    player_res = resources.files("atari_music").joinpath("asm", "player.asm")
    assert player_res.is_file()
    assert player_res.read_bytes() == (REPO_ROOT / "player.asm").read_bytes()

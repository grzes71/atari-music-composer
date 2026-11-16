"""CORE unit tests for the stateless POKEYRuntime resolver and target capabilities."""

from __future__ import annotations

import pytest

from atari_music.constants import AUDCTL_15KHZ, AUDCTL_CH1_179MHZ, AUDCTL_JOIN_1_2_16BIT
from atari_music.instruments import (
    CATALOG_SCHEMA_ID,
    TARGET_SAP_V1_PLANNED,
    TARGET_SAP_V2_ITER1_PLANNED,
    TARGET_V1_XEX,
    TARGET_V2_ITER1_XEX,
    TARGET_WAV_PREVIEW,
    ChannelAssignmentRequest,
    InstrumentBehavior,
    InstrumentCatalog,
    InstrumentCatalogDocument,
    InstrumentProfile,
    InvalidTargetCapabilityError,
    POKEYRuntime,
    TargetCapability,
)

pytestmark = pytest.mark.core


@pytest.fixture
def catalog() -> InstrumentCatalog:
    from atari_music.instruments import load_instrument_catalog

    return load_instrument_catalog()


def test_target_capability_rejects_inconsistent_or_unimplemented_configs() -> None:
    # xex_v1 cannot enable v2 or wav_only or claim song_format_version=2
    with pytest.raises(InvalidTargetCapabilityError):
        TargetCapability(backend="xex_v1", song_format_version=2, enabled_tiers=frozenset({"core_v1"}))
    with pytest.raises(InvalidTargetCapabilityError):
        TargetCapability(
            backend="xex_v1",
            song_format_version=1,
            enabled_tiers=frozenset({"core_v1", "core_v2_iter1"}),
        )
    with pytest.raises(InvalidTargetCapabilityError):
        TargetCapability(
            backend="xex_v1",
            song_format_version=1,
            enabled_tiers=frozenset({"core_v1", "wav_only"}),
        )

    # xex_v2 cannot pretend to be implemented in Stage A, nor claim v1 or deferred/iter2
    with pytest.raises(InvalidTargetCapabilityError):
        TargetCapability(
            backend="xex_v2",
            song_format_version=2,
            enabled_tiers=frozenset({"core_v1", "core_v2_iter1"}),
            is_implemented=True,
        )
    with pytest.raises(InvalidTargetCapabilityError):
        TargetCapability(
            backend="xex_v2",
            song_format_version=1,
            enabled_tiers=frozenset({"core_v1", "core_v2_iter1"}),
            is_implemented=False,
        )
    with pytest.raises(InvalidTargetCapabilityError):
        TargetCapability(
            backend="xex_v2",
            song_format_version=2,
            enabled_tiers=frozenset({"core_v1", "core_v2_iter1", "experimental_deferred"}),
            is_implemented=False,
        )

    # asap cannot be auto-equated with implemented XEX or wav_only in Stage A
    with pytest.raises(InvalidTargetCapabilityError):
        TargetCapability(
            backend="asap",
            song_format_version=1,
            enabled_tiers=frozenset({"core_v1"}),
            is_implemented=True,
        )
    with pytest.raises(InvalidTargetCapabilityError):
        TargetCapability(
            backend="asap",
            song_format_version=1,
            enabled_tiers=frozenset({"core_v1", "core_v2_iter1"}),
            is_implemented=False,
        )
    with pytest.raises(InvalidTargetCapabilityError):
        TargetCapability(
            backend="asap",
            song_format_version=2,
            enabled_tiers=frozenset({"core_v1", "wav_only"}),
            is_implemented=False,
        )

    # wav implemented supports only v1 + {core_v1, wav_only}; not v2_iter1 or deferred
    with pytest.raises(InvalidTargetCapabilityError):
        TargetCapability(
            backend="wav",
            song_format_version=2,
            enabled_tiers=frozenset({"core_v1", "core_v2_iter1"}),
            is_implemented=True,
        )
    with pytest.raises(InvalidTargetCapabilityError):
        TargetCapability(
            backend="wav",
            song_format_version=1,
            enabled_tiers=frozenset({"core_v1", "experimental_deferred"}),
            is_implemented=True,
        )

    # Planned presets carry explicit is_implemented=False
    assert TARGET_V1_XEX.is_implemented is True
    assert TARGET_WAV_PREVIEW.is_implemented is True
    assert TARGET_V2_ITER1_XEX.is_implemented is False
    assert TARGET_SAP_V1_PLANNED.is_implemented is False
    assert TARGET_SAP_V2_ITER1_PLANNED.is_implemented is False


def test_v1_valid_resolutions_and_audctl_computation(catalog: InstrumentCatalog) -> None:
    # 16-bit CH1+CH2 bass ($50) on CH1 + pure lead on CH3 + soft harmony on CH4
    report = POKEYRuntime.resolve(
        [
            ChannelAssignmentRequest(channel=1, instrument_ids=("bass_16bit_pure",)),
            ChannelAssignmentRequest(channel=3, instrument_ids=("lead_pure_sustain",)),
            ChannelAssignmentRequest(channel=4, instrument_ids=("harmony_soft_square",)),
        ],
        catalog,
        TARGET_V1_XEX,
    )
    assert report.is_compatible is True
    assert report.status == "FULL_HARDWARE_V1"
    assert report.effective_audctl == (AUDCTL_JOIN_1_2_16BIT | AUDCTL_CH1_179MHZ)
    assert report.target_implemented is True


def test_preferred_clock_is_non_blocking_while_hard_conflict_blocks_with_zero_audctl(
    catalog: InstrumentCatalog,
) -> None:
    # bass_15khz_pure hard-requires $01; lead_pure_sustain only prefers 64 kHz (no forbidden $01)
    report_ok = POKEYRuntime.resolve(
        [
            ChannelAssignmentRequest(channel=1, instrument_ids=("bass_15khz_pure",)),
            ChannelAssignmentRequest(channel=3, instrument_ids=("lead_pure_sustain",)),
        ],
        catalog,
        TARGET_V1_XEX,
    )
    assert report_ok.is_compatible is True
    assert report_ok.effective_audctl == AUDCTL_15KHZ

    # Now build a profile that hard-forbids $01 (AUDCTL_15KHZ) and pair it with bass_15khz_pure
    strict_64k_lead = InstrumentProfile.model_validate(
        {
            **catalog.get_profile("lead_pure_sustain").model_dump(mode="json"),
            "instrument_id": "strict_64khz_lead",
            "hardware_constraints": {
                "divider_mode": "8bit",
                "preferred_clock_hz": "64khz",
                "required_audctl_bits": 0,
                "forbidden_audctl_bits": AUDCTL_15KHZ,
                "poly4_safe_tuning": False,
                "midi_range": [60, 96],
                "channels_allowed": [1, 2, 3, 4],
            },
        }
    )
    custom_cat = InstrumentCatalog(
        InstrumentCatalogDocument(
            schema_id=CATALOG_SCHEMA_ID,
            catalog_version="0.1.0",
            behaviors=catalog.behaviors,
            instruments=(catalog.get_profile("bass_15khz_pure"), strict_64k_lead),
        )
    )
    report_conflict = POKEYRuntime.resolve(
        [
            ChannelAssignmentRequest(channel=1, instrument_ids=("bass_15khz_pure",)),
            ChannelAssignmentRequest(channel=3, instrument_ids=("strict_64khz_lead",)),
        ],
        custom_cat,
        TARGET_V1_XEX,
    )
    assert report_conflict.is_compatible is False
    assert report_conflict.status == "BLOCKED_CONFLICT"
    assert report_conflict.effective_audctl == 0
    assert any(d.code == "AUDCTL_CLOCK_CONFLICT" and d.severity == "ERROR" for d in report_conflict.diagnostics)


def test_hard_hardware_conflicts_always_zero_effective_audctl(catalog: InstrumentCatalog) -> None:
    # 1. Independent CH2 assignment while CH1 uses 16-bit CH1+CH2
    rep_pair = POKEYRuntime.resolve(
        [
            ChannelAssignmentRequest(channel=1, instrument_ids=("bass_16bit_pure",)),
            ChannelAssignmentRequest(channel=2, instrument_ids=("lead_pure_pluck",)),
        ],
        catalog,
        TARGET_V1_XEX,
    )
    assert rep_pair.is_compatible is False
    assert rep_pair.effective_audctl == 0
    assert any(d.code == "PAIR_16BIT_CHANNEL_CONFLICT" for d in rep_pair.diagnostics)

    # 2. Duplicate channel assignment (no auto-rerouting)
    rep_dup = POKEYRuntime.resolve(
        [
            ChannelAssignmentRequest(channel=3, instrument_ids=("lead_pure_sustain",)),
            ChannelAssignmentRequest(channel=3, instrument_ids=("lead_pure_pluck",)),
        ],
        catalog,
        TARGET_V1_XEX,
    )
    assert rep_dup.is_compatible is False
    assert rep_dup.effective_audctl == 0
    assert any(d.code == "DUPLICATE_CHANNEL_REQUEST" for d in rep_dup.diagnostics)

    # 3. Profile bound to disallowed channel (percussion is CH4-only; 16-bit CH1+CH2 is CH1-only)
    rep_ch = POKEYRuntime.resolve(
        [ChannelAssignmentRequest(channel=2, instrument_ids=("bass_16bit_pure",))],
        catalog,
        TARGET_V1_XEX,
    )
    assert rep_ch.is_compatible is False
    assert rep_ch.effective_audctl == 0
    assert any(d.severity == "ERROR" for d in rep_ch.diagnostics)

    # 4. Channel-specific 1.79 MHz bit ($40 on CH2 / $20 on CH4) rejected
    bad_hs_profile = InstrumentProfile.model_validate(
        {
            **catalog.get_profile("lead_pure_sustain").model_dump(mode="json"),
            "instrument_id": "invalid_ch2_hs",
            "hardware_constraints": {
                "divider_mode": "8bit",
                "preferred_clock_hz": "1.79mhz",
                "required_audctl_bits": AUDCTL_CH1_179MHZ,
                "forbidden_audctl_bits": 0,
                "poly4_safe_tuning": False,
                "midi_range": [48, 96],
                "channels_allowed": [2],
            },
        }
    )
    bad_cat = InstrumentCatalog(
        InstrumentCatalogDocument(
            schema_id=CATALOG_SCHEMA_ID,
            catalog_version="0.1.0",
            behaviors=catalog.behaviors,
            instruments=(bad_hs_profile,),
        )
    )
    rep_hs = POKEYRuntime.resolve(
        [ChannelAssignmentRequest(channel=2, instrument_ids=("invalid_ch2_hs",))],
        bad_cat,
        TARGET_V1_XEX,
    )
    assert rep_hs.is_compatible is False
    assert rep_hs.effective_audctl == 0
    assert any(d.code == "CHANNEL_NOT_ALLOWED" for d in rep_hs.diagnostics)


def test_multi_instrument_channel_and_v2_iter1_planning_rules(catalog: InstrumentCatalog) -> None:
    drum_kit = ("perc_kick_tight", "perc_snare_crisp", "perc_hihat_closed", "perc_tom_pitched")

    # Blocked in v1 (both multi-instrument and core_v2_iter1 tier)
    rep_v1 = POKEYRuntime.resolve(
        [ChannelAssignmentRequest(channel=4, instrument_ids=drum_kit)],
        catalog,
        TARGET_V1_XEX,
    )
    assert rep_v1.is_compatible is False
    assert rep_v1.effective_audctl == 0
    codes_v1 = {d.code for d in rep_v1.diagnostics if d.severity == "ERROR"}
    assert "MULTI_INSTRUMENT_REQUIRES_V2" in codes_v1
    assert "BEHAVIOR_NOT_IN_TARGET_TIER" in codes_v1

    # Allowed under planned v2_iter1 contract (with explicit target_implemented=False notice)
    rep_v2 = POKEYRuntime.resolve(
        [
            ChannelAssignmentRequest(channel=1, instrument_ids=("bass_16bit_pure",)),
            ChannelAssignmentRequest(channel=3, instrument_ids=("lead_attack_bite",)),
            ChannelAssignmentRequest(channel=4, instrument_ids=drum_kit),
        ],
        catalog,
        TARGET_V2_ITER1_XEX,
    )
    assert rep_v2.is_compatible is True
    assert rep_v2.status == "FULL_HARDWARE_V2_ITER1"
    assert rep_v2.effective_audctl == (AUDCTL_JOIN_1_2_16BIT | AUDCTL_CH1_179MHZ)
    assert rep_v2.target_implemented is False
    assert any(d.code == "TARGET_NOT_IMPLEMENTED" and d.severity == "WARNING" for d in rep_v2.diagnostics)


def test_profile_vs_behavior_separation_and_deferred_or_wav_only_gates(catalog: InstrumentCatalog) -> None:
    bell_profile = catalog.get_profile("ornament_bell_arp")
    arp_behavior = catalog.get_behavior("beh_arp_deferred")
    assert arp_behavior is not None

    # Same static bell profile WITHOUT deferred arpeggio behavior works on v1
    static_status, static_diags = POKEYRuntime.check_profile(bell_profile, None, TARGET_V1_XEX, channel=3)
    assert static_status == "FULL_HARDWARE_V1"
    assert not any(d.severity == "ERROR" for d in static_diags)

    # Same bell profile WITH deferred arpeggio behavior is refused on both v1 and planned v2_iter1
    for target in (TARGET_V1_XEX, TARGET_V2_ITER1_XEX, TARGET_SAP_V1_PLANNED):
        status, diags = POKEYRuntime.check_profile(bell_profile, arp_behavior, target, channel=3)
        assert status == "DEFERRED_FEATURE"
        assert any(d.code == "BEHAVIOR_NOT_IN_TARGET_TIER" and d.severity == "ERROR" for d in diags)

    # Catalog-level resolution for lead_hpf_pwm & ornament_bell_arp blocks with effective_audctl=0
    rep_deferred = POKEYRuntime.resolve(
        [
            ChannelAssignmentRequest(channel=1, instrument_ids=("lead_hpf_pwm",)),
            ChannelAssignmentRequest(channel=3, instrument_ids=("ornament_bell_arp",)),
        ],
        catalog,
        TARGET_V2_ITER1_XEX,
    )
    assert rep_deferred.is_compatible is False
    assert rep_deferred.status == "DEFERRED_FEATURE"
    assert rep_deferred.effective_audctl == 0

    # wav_only behavior passes WAV preview but blocks XEX export without silent dropping
    wav_only_beh = InstrumentBehavior(
        behavior_id="beh_contour_wav",
        required_runtime_tier="wav_only",
        uses_wav_only_contour=True,
    )
    lead_prof = catalog.get_profile("lead_pure_sustain")
    st_wav, diags_wav = POKEYRuntime.check_profile(lead_prof, wav_only_beh, TARGET_WAV_PREVIEW, channel=3)
    assert st_wav == "WAV_PREVIEW_ONLY"
    assert not any(d.severity == "ERROR" for d in diags_wav)

    st_xex, diags_xex = POKEYRuntime.check_profile(lead_prof, wav_only_beh, TARGET_V1_XEX, channel=3)
    assert st_xex == "WAV_PREVIEW_ONLY"
    assert any(d.code == "WAV_ONLY_NOT_EXPORTABLE" and d.severity == "ERROR" for d in diags_xex)


def test_resolver_is_stateless_and_order_independent(catalog: InstrumentCatalog) -> None:
    reqs_a = [
        ChannelAssignmentRequest(channel=1, instrument_ids=("bass_15khz_pure",)),
        ChannelAssignmentRequest(channel=3, instrument_ids=("lead_c1_octave_pulse",)),
        ChannelAssignmentRequest(channel=4, instrument_ids=("harmony_soft_square",)),
    ]
    reqs_b = list(reversed(reqs_a))

    rep_1 = POKEYRuntime.resolve(reqs_a, catalog, TARGET_V1_XEX)
    rep_2 = POKEYRuntime.resolve(reqs_b, catalog, TARGET_V1_XEX)
    assert rep_1 == rep_2

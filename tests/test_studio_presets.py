"""Unit and contract tests for Studio Phase 2 presets (PySide6-free)."""

from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path

import pytest

import atari_music.studio as studio
from atari_music.studio import (
    DEFAULT_PRESETS_DIR,
    PRESET_ALREADY_EXISTS,
    PRESET_INVALID_NAME,
    PRESET_JSON_INVALID,
    PRESET_NOT_FOUND,
    PRESET_SCHEMA_ID,
    PRESET_SCHEMA_UNSUPPORTED,
    PRESET_STORAGE_ERROR,
    PRESET_UNKNOWN_INSTRUMENT,
    PRESET_VALIDATION_ERROR,
    ArrangementPreset,
    InstrumentService,
    PresetError,
    PresetRepository,
    RenderService,
    StudioArrangementConfig,
    apply_preset_to_state,
    load_studio_composition,
    parse_preset_json,
    preset_slug,
    serialize_preset_json,
)

REPO_ROOT = Path(__file__).resolve().parents[1]

pytestmark = pytest.mark.core


def test_public_api_uses_preset_error_without_preset_load_error() -> None:
    assert not hasattr(studio, "PresetLoadError")
    assert "PresetLoadError" not in studio.__all__
    assert studio.PresetError is PresetError


def test_preset_serialization_round_trip_and_keep_original() -> None:
    created = datetime(2026, 11, 18, 16, 30, 0, tzinfo=timezone.utc)
    preset = ArrangementPreset(
        name="  Dungeon 16-bit Punch  ",
        description="  Pure 16-bit bass, Keep Original CH2, bite lead CH3.  ",
        arrangement=StudioArrangementConfig(
            channel_instruments={1: "bass_16bit_pure", 2: None, 3: "lead_attack_bite", 4: "perc_kick_tight"},
            program_change_policy="replace",
            player_version="v2",
            target_backend="xex_v2",
        ),
        created_at=created,
        updated_at=created,
    )

    raw_json = serialize_preset_json(preset)
    payload = json.loads(raw_json)
    assert payload["schema_id"] == PRESET_SCHEMA_ID
    assert payload["name"] == "Dungeon 16-bit Punch"
    assert payload["arrangement"]["channel_instruments"] == {
        "1": "bass_16bit_pure",
        "2": None,
        "3": "lead_attack_bite",
        "4": "perc_kick_tight",
    }
    assert payload["arrangement"]["program_change_policy"] == "replace"
    assert payload["arrangement"]["player_version"] == "v2"
    assert payload["arrangement"]["target_backend"] == "xex_v2"

    restored = parse_preset_json(raw_json)
    assert restored == preset
    assert restored.arrangement.channel_instruments[2] is None
    assert restored.arrangement.assigned_map() == {
        1: "bass_16bit_pure",
        3: "lead_attack_bite",
        4: "perc_kick_tight",
    }


def test_preset_partial_channels_normalize_missing_to_keep_original() -> None:
    raw = json.dumps(
        {
            "schema_id": PRESET_SCHEMA_ID,
            "name": "Partial CH3 Only",
            "arrangement": {
                "channel_instruments": {"3": "lead_pure_sustain"},
                "program_change_policy": "remove",
                "player_version": "v1",
                "target_backend": "xex_v1",
            },
        }
    )
    preset = parse_preset_json(raw)
    assert preset.arrangement.channel_instruments == {
        1: None,
        2: None,
        3: "lead_pure_sustain",
        4: None,
    }
    assert preset.arrangement.program_change_policy == "remove"
    assert preset.arrangement.player_version == "v1"
    assert preset.arrangement.target_backend == "xex_v1"


@pytest.mark.parametrize(
    ("raw_text", "expected_code"),
    [
        ("{broken json", PRESET_JSON_INVALID),
        ("[]", PRESET_VALIDATION_ERROR),
        (json.dumps({"name": "No Schema", "arrangement": {}}), PRESET_SCHEMA_UNSUPPORTED),
        (
            json.dumps({"schema_id": "atari-music/arrangement-preset/99", "name": "Future", "arrangement": {}}),
            PRESET_SCHEMA_UNSUPPORTED,
        ),
        (
            json.dumps({"schema_id": PRESET_SCHEMA_ID, "name": "   ", "arrangement": {}}),
            PRESET_VALIDATION_ERROR,
        ),
        (
            json.dumps({"schema_id": PRESET_SCHEMA_ID, "name": "Extra", "unexpected": 1, "arrangement": {}}),
            PRESET_VALIDATION_ERROR,
        ),
        (
            json.dumps(
                {
                    "schema_id": PRESET_SCHEMA_ID,
                    "name": "Bad Channel",
                    "arrangement": {"channel_instruments": {"5": "lead_pure_sustain"}},
                }
            ),
            PRESET_VALIDATION_ERROR,
        ),
        (
            json.dumps(
                {
                    "schema_id": PRESET_SCHEMA_ID,
                    "name": "Bad Policy",
                    "arrangement": {"program_change_policy": "drop_all"},
                }
            ),
            PRESET_VALIDATION_ERROR,
        ),
        (
            json.dumps(
                {
                    "schema_id": PRESET_SCHEMA_ID,
                    "name": "Bad Target",
                    "arrangement": {"target_backend": "sap_v9"},
                }
            ),
            PRESET_VALIDATION_ERROR,
        ),
    ],
)
def test_preset_parse_validation_errors(raw_text: str, expected_code: str) -> None:
    err_path = Path("broken_preset.json")
    with pytest.raises(PresetError) as exc_info:
        parse_preset_json(raw_text, source=err_path)
    assert exc_info.value.code == expected_code
    assert exc_info.value.path == err_path


def test_serialize_preset_json_validates_constructed_objects() -> None:
    unvalidated = ArrangementPreset.model_construct(
        schema_id="atari-music/arrangement-preset/999",  # type: ignore[arg-type]
        name="Invalid Schema On Write",
        description=None,
        arrangement=StudioArrangementConfig(),
    )
    with pytest.raises(PresetError) as exc_info:
        serialize_preset_json(unvalidated)
    assert exc_info.value.code == PRESET_VALIDATION_ERROR


@pytest.mark.parametrize(
    ("raw_name", "expected_slug"),
    [
        ("Action 16-bit Punch", "action-16-bit-punch"),
        ("  Zażółć gęślą jaźń!!  ", "zazolc-gesla-jazn"),
        ("../Traversal Attempt/Name", "traversal-attempt-name"),
    ],
)
def test_preset_slug_sanitization(raw_name: str, expected_slug: str) -> None:
    assert preset_slug(raw_name) == expected_slug


@pytest.mark.parametrize("bad_name", ["", "   ", "!!!", "..", "CON", "nul", "COM1", "bad\nname"])
def test_preset_slug_rejects_unsafe_or_reserved_names(bad_name: str) -> None:
    with pytest.raises(PresetError) as exc_info:
        preset_slug(bad_name)
    assert exc_info.value.code == PRESET_INVALID_NAME


def test_repository_default_dir_and_empty_scan_without_side_effects(tmp_path: Path) -> None:
    assert DEFAULT_PRESETS_DIR == Path.home() / ".atari_music_studio" / "presets"

    missing_dir = tmp_path / "nonexistent_presets"
    repo = PresetRepository(presets_dir=missing_dir)
    scan = repo.list_presets()
    assert scan.presets == ()
    assert scan.errors == ()
    assert not missing_dir.exists()


def test_repository_crud_save_load_rename_delete_and_overwrite_timestamps(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    t_initial = datetime(2026, 11, 18, 10, 0, 0, tzinfo=timezone.utc)
    t_overwrite = datetime(2026, 11, 18, 10, 5, 0, tzinfo=timezone.utc)
    t_rename = datetime(2026, 11, 18, 10, 10, 0, tzinfo=timezone.utc)
    times = iter([t_initial, t_initial, t_overwrite, t_rename])

    class _FakeDatetime:
        @staticmethod
        def now(tz=None):
            return next(times)

    monkeypatch.setattr("atari_music.studio.presets.datetime", _FakeDatetime)

    repo = PresetRepository(presets_dir=tmp_path / "presets")
    cfg_a = StudioArrangementConfig(
        channel_instruments={1: "bass_16bit_pure", 2: None, 3: "lead_attack_bite", 4: "perc_kick_tight"},
        program_change_policy="replace",
        player_version="v2",
        target_backend="xex_v2",
    )
    cfg_b = StudioArrangementConfig(
        channel_instruments={1: "bass_15khz_pure", 2: "harmony_soft_square", 3: None, 4: None},
        program_change_policy="preserve",
        player_version="auto",
        target_backend="wav",
    )

    rec_z = repo.save_preset("Zebra Lead", cfg_b, description="Second alphabetically")
    rec_a = repo.save_preset("Alpha Bass", cfg_a, description="First alphabetically")
    assert rec_a.preset_id == "alpha-bass"
    assert rec_z.preset_id == "zebra-lead"

    # Deterministic sorted listing by name
    scan = repo.list_presets()
    assert scan.errors == ()
    assert [r.preset.name for r in scan.presets] == ["Alpha Bass", "Zebra Lead"]

    # Overwrite preserves created_at and advances updated_at
    cfg_a2 = cfg_a.with_channel(4, "perc_snare_crisp")
    rec_a2 = repo.save_preset("Alpha Bass", cfg_a2, description="Updated", overwrite=True)
    assert rec_a2.preset.created_at == t_initial
    assert rec_a2.preset.updated_at == t_overwrite
    loaded_a2 = repo.load_preset("alpha-bass")
    assert loaded_a2.preset.arrangement == cfg_a2
    assert loaded_a2.preset.created_at == t_initial
    assert loaded_a2.preset.updated_at == t_overwrite

    # Rename moves file safely and updates name/updated_at
    renamed = repo.rename_preset("alpha-bass", "Beta Bass")
    assert renamed.preset_id == "beta-bass"
    assert renamed.preset.name == "Beta Bass"
    assert renamed.preset.created_at == t_initial
    assert renamed.preset.updated_at == t_rename
    assert not (repo.presets_dir / "alpha-bass.json").exists()
    assert (repo.presets_dir / "beta-bass.json").is_file()

    # Delete removes only target
    deleted_path = repo.delete_preset("beta-bass")
    assert deleted_path == repo.presets_dir / "beta-bass.json"
    assert not deleted_path.exists()
    assert [r.preset_id for r in repo.list_presets().presets] == ["zebra-lead"]


def test_repository_name_and_slug_collisions(tmp_path: Path) -> None:
    repo = PresetRepository(presets_dir=tmp_path / "presets")
    repo.save_preset("Boss Fight", StudioArrangementConfig())
    repo.save_preset("Ambient Pad", StudioArrangementConfig())

    # Exact duplicate name
    with pytest.raises(PresetError) as exc_dup:
        repo.save_preset("  boss fight  ", StudioArrangementConfig())
    assert exc_dup.value.code == PRESET_ALREADY_EXISTS

    # Distinct display name colliding on slug
    with pytest.raises(PresetError) as exc_slug:
        repo.save_preset("Boss Fight!!", StudioArrangementConfig())
    assert exc_slug.value.code == PRESET_ALREADY_EXISTS

    # Rename into existing slug/name blocked unless overwrite=True
    with pytest.raises(PresetError) as exc_rename:
        repo.rename_preset("ambient-pad", "Boss Fight!")
    assert exc_rename.value.code == PRESET_ALREADY_EXISTS
    assert repo.load_preset("ambient-pad").preset.name == "Ambient Pad"
    assert repo.load_preset("boss-fight").preset.name == "Boss Fight"


def test_repository_rejects_outside_files_and_escapes(tmp_path: Path) -> None:
    presets_dir = tmp_path / "presets"
    presets_dir.mkdir()
    outside = tmp_path / "secret.json"
    outside_payload = serialize_preset_json(
        ArrangementPreset(name="Outside Secret", arrangement=StudioArrangementConfig())
    )
    outside.write_text(outside_payload, encoding="utf-8")

    repo = PresetRepository(presets_dir=presets_dir)
    for escape_id in (
        "../secret",
        "../secret.json",
        "..\\secret.json",
        str(outside),
        "sub/secret",
        "CON",
    ):
        with pytest.raises(PresetError) as exc_load:
            repo.load_preset(escape_id)
        assert exc_load.value.code == PRESET_INVALID_NAME

        with pytest.raises(PresetError) as exc_del:
            repo.delete_preset(escape_id)
        assert exc_del.value.code == PRESET_INVALID_NAME

        with pytest.raises(PresetError) as exc_ren:
            repo.rename_preset(escape_id, "Safe Name")
        assert exc_ren.value.code == PRESET_INVALID_NAME

    assert outside.is_file()
    assert outside.read_text(encoding="utf-8") == outside_payload


def test_repository_safe_scan_isolates_malformed_and_unsupported_files(tmp_path: Path) -> None:
    repo = PresetRepository(presets_dir=tmp_path / "presets")
    repo.save_preset("Valid One", StudioArrangementConfig())
    repo.save_preset("Valid Two", StudioArrangementConfig(player_version="v2"))

    (repo.presets_dir / "broken.json").write_text("{invalid json", encoding="utf-8")
    (repo.presets_dir / "future.json").write_text(
        json.dumps({"schema_id": "atari-music/arrangement-preset/99", "name": "Future", "arrangement": {}}),
        encoding="utf-8",
    )
    (repo.presets_dir / "notes.txt").write_text("ignored non-json", encoding="utf-8")

    scan = repo.list_presets()
    assert [r.preset.name for r in scan.presets] == ["Valid One", "Valid Two"]
    err_by_name = {issue.path.name: issue.code for issue in scan.errors}
    assert err_by_name == {
        "broken.json": PRESET_JSON_INVALID,
        "future.json": PRESET_SCHEMA_UNSUPPORTED,
    }


def test_repository_atomic_write_failure_preserves_existing_and_cleans_tmp(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = PresetRepository(presets_dir=tmp_path / "presets")
    orig_cfg = StudioArrangementConfig(channel_instruments={1: "bass_16bit_pure", 2: None, 3: None, 4: None})
    rec = repo.save_preset("Atomic Target", orig_cfg, description="Original")
    before_bytes = rec.path.read_bytes()

    def _boom_replace(_src, _dst):
        raise OSError("simulated disk error during os.replace")

    monkeypatch.setattr("atari_music.studio.presets.os.replace", _boom_replace)

    with pytest.raises(PresetError) as exc_info:
        repo.save_preset(
            "Atomic Target",
            orig_cfg.with_channel(3, "lead_attack_bite"),
            description="Should Fail",
            overwrite=True,
        )
    assert exc_info.value.code == PRESET_STORAGE_ERROR
    assert rec.path.read_bytes() == before_bytes
    leftover_tmps = list(repo.presets_dir.glob("*.tmp"))
    assert leftover_tmps == []


def test_repository_rename_failures_preserve_original_and_target(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = PresetRepository(presets_dir=tmp_path / "presets")
    src_rec = repo.save_preset(
        "Source Preset",
        StudioArrangementConfig(channel_instruments={1: "bass_15khz_pure", 2: None, 3: None, 4: None}),
    )
    dst_rec = repo.save_preset(
        "Dest Preset",
        StudioArrangementConfig(channel_instruments={1: None, 2: None, 3: "lead_pure_sustain", 4: None}),
    )
    src_before = src_rec.path.read_bytes()
    dst_before = dst_rec.path.read_bytes()

    # Case 1: write failure during rename to new name -> original stays intact, no new file
    def _fail_replace(_src, _dst):
        raise OSError("replace failed")

    with monkeypatch.context() as mp:
        mp.setattr("atari_music.studio.presets.os.replace", _fail_replace)
        with pytest.raises(PresetError) as exc_write:
            repo.rename_preset("source-preset", "Brand New Name")
        assert exc_write.value.code == PRESET_STORAGE_ERROR

    assert src_rec.path.read_bytes() == src_before
    assert not (repo.presets_dir / "brand-new-name.json").exists()
    assert list(repo.presets_dir.glob("*.tmp")) == []

    # Case 2: unlink failure after writing target during overwrite rename -> both source & prior target restored!
    orig_unlink = Path.unlink

    def _fail_src_unlink(self: Path, missing_ok: bool = False):
        if self.name == "source-preset.json":
            raise OSError("cannot unlink locked source")
        return orig_unlink(self, missing_ok=missing_ok)

    with monkeypatch.context() as mp:
        mp.setattr(Path, "unlink", _fail_src_unlink)
        with pytest.raises(PresetError) as exc_unlink:
            repo.rename_preset("source-preset", "Dest Preset", overwrite=True)
        assert exc_unlink.value.code == PRESET_STORAGE_ERROR

    assert src_rec.path.is_file() and src_rec.path.read_bytes() == src_before
    assert dst_rec.path.is_file() and dst_rec.path.read_bytes() == dst_before


def test_repository_delete_errors(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo = PresetRepository(presets_dir=tmp_path / "presets")
    with pytest.raises(PresetError) as exc_missing:
        repo.delete_preset("does-not-exist")
    assert exc_missing.value.code == PRESET_NOT_FOUND

    rec = repo.save_preset("Delete Fail Target", StudioArrangementConfig())

    def _fail_unlink(self: Path, missing_ok: bool = False):
        raise OSError("permission denied")

    monkeypatch.setattr(Path, "unlink", _fail_unlink)
    with pytest.raises(PresetError) as exc_io:
        repo.delete_preset("delete-fail-target")
    assert exc_io.value.code == PRESET_STORAGE_ERROR
    assert rec.path.is_file()


def test_apply_preset_rejects_unknown_catalog_id_without_mutating_state() -> None:
    svc = InstrumentService()
    state = load_studio_composition(REPO_ROOT / "examples" / "ai" / "action_fast.json")
    before_ir = state.base_pokey_ir.model_dump(mode="json")
    before_sha = state.base_ir_sha256
    before_fp = state.musical_fingerprint
    before_baseline = state.baseline_config

    bad_preset = ArrangementPreset(
        name="Unknown Instrument",
        arrangement=StudioArrangementConfig(
            channel_instruments={1: "bass_15khz_pure", 2: None, 3: "nonexistent_lead_v99", 4: None}
        ),
    )

    with pytest.raises(PresetError) as exc_info:
        apply_preset_to_state(state, bad_preset, instrument_service=svc)
    assert exc_info.value.code == PRESET_UNKNOWN_INSTRUMENT
    assert state.base_pokey_ir.model_dump(mode="json") == before_ir
    assert state.base_ir_sha256 == before_sha
    assert state.musical_fingerprint == before_fp
    assert state.baseline_config == before_baseline


def test_apply_preset_keep_original_replaces_prior_overrides_and_never_renders(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    svc = InstrumentService()
    state = load_studio_composition(REPO_ROOT / "examples" / "ai" / "action_fast.json")

    def _forbid_render(*_args, **_kwargs):
        raise AssertionError("RenderService must never be invoked during apply_preset_to_state")

    monkeypatch.setattr(RenderService, "render_preview", _forbid_render)

    before_sha = state.base_ir_sha256
    before_fp = state.musical_fingerprint
    before_baseline = state.baseline_config

    prior_preset = ArrangementPreset(
        name="All Assigned",
        arrangement=StudioArrangementConfig(
            channel_instruments={
                1: "lead_pure_sustain",
                2: "bass_15khz_pure",
                3: "harmony_soft_square",
                4: "perc_snare_crisp",
            },
            program_change_policy="replace",
            player_version="v2",
            target_backend="xex_v2",
        ),
    )
    prior_res = apply_preset_to_state(state, prior_preset, instrument_service=svc)
    assert prior_res.evaluation.is_valid is True

    partial_keep_orig = ArrangementPreset(
        name="Keep Original CH2 CH3 CH4",
        arrangement=StudioArrangementConfig(
            channel_instruments={1: "lead_pure_pluck", 2: None, 3: None, 4: None},
            program_change_policy="preserve",
            player_version="auto",
            target_backend="wav",
        ),
    )
    applied = apply_preset_to_state(state, partial_keep_orig, instrument_service=svc)
    assert applied.config.channel_instruments == {1: "lead_pure_pluck", 2: None, 3: None, 4: None}
    assert applied.evaluation.is_valid is True
    assert "(Original)" in applied.evaluation.channels[2].effective_instrument_label
    assert "(Original)" in applied.evaluation.channels[3].effective_instrument_label
    assert "(Original)" in applied.evaluation.channels[4].effective_instrument_label
    # Prior config snapshot remains untouched (immutable replacement)
    assert prior_res.config.channel_instruments[2] == "bass_15khz_pure"
    assert state.base_ir_sha256 == before_sha
    assert state.musical_fingerprint == before_fp
    assert state.baseline_config == before_baseline


def test_apply_preset_16bit_bass_channel_locking_and_conflict_reporting(tmp_path: Path) -> None:
    svc = InstrumentService()

    # Case 1: 8-bit song with empty CH2 + 16-bit CH1 bass preset (CH2=None) -> locks CH2 cleanly
    dsl_empty_ch2 = """TITLE "Eight Bit Sparse"
KEY E
MODE MINOR
BPM 120
CHANNELS 4
LOOP 0

SEQUENCE A

INSTRUMENT bass character=bass
INSTRUMENT lead character=bright_lead
INSTRUMENT perc character=percussion

[PATTERN A length=8]
CH1 bass V12
E2/4 B2/4
CH3 lead V13
E5/4 B4/4
CH4 perc V9
C4/4 R/4
"""
    sparse_path = tmp_path / "sparse_8bit.dsl"
    sparse_path.write_text(dsl_empty_ch2, encoding="utf-8")
    state_8bit_empty_ch2 = load_studio_composition(sparse_path)
    assert state_8bit_empty_ch2.base_uses_16bit_bass is False

    preset_16bit_clean = ArrangementPreset(
        name="16-bit Bass Clean",
        arrangement=StudioArrangementConfig(
            channel_instruments={1: "bass_16bit_pure", 2: None, 3: "lead_attack_bite", 4: "perc_kick_tight"},
            program_change_policy="preserve",
            player_version="auto",
            target_backend="xex_v2",
        ),
    )
    res_clean = apply_preset_to_state(state_8bit_empty_ch2, preset_16bit_clean, instrument_service=svc)
    assert res_clean.evaluation.is_valid is True
    assert res_clean.evaluation.effective_uses_16bit_bass is True
    assert res_clean.evaluation.channels[2].available_for_assignment is False
    assert res_clean.evaluation.channels[2].lock_reason is not None
    assert "16bit_ch12" in res_clean.evaluation.channels[2].lock_reason

    # Case 2: 8-bit song with active notes on CH2 + 16-bit CH1 bass preset -> locked CH2 & blocking conflict
    state_8bit_active_ch2 = load_studio_composition(REPO_ROOT / "examples" / "ai" / "action_fast.json")
    res_pair_conflict = apply_preset_to_state(state_8bit_active_ch2, preset_16bit_clean, instrument_service=svc)
    assert res_pair_conflict.config == preset_16bit_clean.arrangement
    assert res_pair_conflict.evaluation.channels[2].available_for_assignment is False
    assert res_pair_conflict.evaluation.is_valid is False
    assert any("PAIR_16BIT_CHANNEL_CONFLICT" in err for err in res_pair_conflict.evaluation.blocking_errors)

    # Case 3: 16-bit song (wybierak-2.dsl) + preset assigning CH2 -> config applied verbatim, evaluation invalid!
    state_16bit = load_studio_composition(REPO_ROOT / "examples" / "songs" / "wybierak-2.dsl")
    assert state_16bit.base_uses_16bit_bass is True
    preset_ch2_conflict = ArrangementPreset(
        name="Conflicting CH2",
        arrangement=StudioArrangementConfig(
            channel_instruments={1: None, 2: "harmony_soft_square", 3: "lead_pure_sustain", 4: None},
            program_change_policy="preserve",
            player_version="auto",
            target_backend="xex_v2",
        ),
    )
    res_conflict = apply_preset_to_state(state_16bit, preset_ch2_conflict, instrument_service=svc)
    # Must NOT silently drop CH2 assignment
    assert res_conflict.config.channel_instruments[2] == "harmony_soft_square"
    assert res_conflict.evaluation.channels[2].available_for_assignment is False
    assert res_conflict.evaluation.is_valid is False
    assert any("Channel 2 cannot be assigned" in err for err in res_conflict.evaluation.blocking_errors)


def test_apply_preset_propagates_policy_player_version_and_target_into_evaluation(tmp_path: Path) -> None:
    from atari_music.api import generate_music

    svc = InstrumentService()
    # Composition using core_v1 channel instruments + PROGRAM_CHANGE on CH3 (requires v2 unless policy='remove')
    ir_res = generate_music(
        profile="action",
        seed=42,
        uses_16bit_bass=False,
        channel_instruments={
            1: "bass_15khz_pure",
            2: "harmony_soft_square",
            3: "lead_pure_sustain",
            4: "harmony_soft_square",
        },
        program_changes=[{"channel": 3, "pattern_index": 0, "note_index": 1, "instrument_id": "lead_pure_pluck"}],
        player_version="v2",
    )
    ir_path = tmp_path / "pc_song.json"
    ir_res.save_json(ir_path)
    state_pc = load_studio_composition(ir_path)

    # Policy 'remove' + core_v1 overrides + player_version='v1' + target='xex_v1' -> valid Format v1!
    p_strip_to_v1 = ArrangementPreset(
        name="Strip PC to V1",
        arrangement=StudioArrangementConfig(
            channel_instruments={1: "bass_15khz_pure", 2: "harmony_soft_square", 3: "lead_pure_sustain", 4: "lead_pure_pluck"},
            program_change_policy="remove",
            player_version="v1",
            target_backend="xex_v1",
        ),
    )
    res_v1 = apply_preset_to_state(state_pc, p_strip_to_v1, instrument_service=svc)
    assert res_v1.config.program_change_policy == "remove"
    assert res_v1.config.player_version == "v1"
    assert res_v1.config.target_backend == "xex_v1"
    assert res_v1.evaluation.is_valid is True
    assert res_v1.evaluation.effective_format_version == 1

    # Policy 'preserve' + player_version='v1' -> invalid Format v1 conflict because CH3 keeps PROGRAM_CHANGE!
    p_preserve_v1_fail = ArrangementPreset(
        name="Preserve PC Under V1",
        arrangement=StudioArrangementConfig(
            channel_instruments={1: "bass_15khz_pure", 2: "harmony_soft_square", 3: "lead_pure_sustain", 4: "lead_pure_pluck"},
            program_change_policy="preserve",
            player_version="v1",
            target_backend="xex_v1",
        ),
    )
    res_pc_fail = apply_preset_to_state(state_pc, p_preserve_v1_fail, instrument_service=svc)
    assert res_pc_fail.evaluation.is_valid is False
    assert res_pc_fail.evaluation.blocking_errors

    # v2 macro instrument with target='xex_v1' or ('wav' + player_version='v1') -> invalid BEHAVIOR_NOT_IN_TARGET_TIER!
    state_simple = load_studio_composition(REPO_ROOT / "examples" / "ai" / "action_fast.json")
    for limited_target, limited_pv in (("xex_v1", "auto"), ("wav", "v1")):
        p_v2_on_limited = ArrangementPreset(
            name=f"V2 Macro On {limited_target} {limited_pv}",
            arrangement=StudioArrangementConfig(
                channel_instruments={1: None, 2: None, 3: "lead_attack_bite", 4: None},
                program_change_policy="replace",
                player_version=limited_pv,  # type: ignore[arg-type]
                target_backend=limited_target,  # type: ignore[arg-type]
            ),
        )
        res_bad_target = apply_preset_to_state(state_simple, p_v2_on_limited, instrument_service=svc)
        assert res_bad_target.config.target_backend == limited_target
        assert res_bad_target.evaluation.is_valid is False
        assert any(
            d.severity == "ERROR" and d.code == "BEHAVIOR_NOT_IN_TARGET_TIER"
            for d in res_bad_target.evaluation.diagnostics
        )

    # Same v2 macro instrument with target='xex_v2' or target='wav' and player_version='auto' -> valid Format v2!
    for v2_target in ("xex_v2", "wav"):
        p_v2_ok = ArrangementPreset(
            name=f"V2 Macro On {v2_target}",
            arrangement=StudioArrangementConfig(
                channel_instruments={1: None, 2: None, 3: "lead_attack_bite", 4: None},
                program_change_policy="replace",
                player_version="auto",
                target_backend=v2_target,  # type: ignore[arg-type]
            ),
        )
        res_v2_ok = apply_preset_to_state(state_simple, p_v2_ok, instrument_service=svc)
        assert res_v2_ok.config.target_backend == v2_target
        assert res_v2_ok.evaluation.is_valid is True
        assert res_v2_ok.evaluation.effective_format_version == 2
        assert not any(d.code == "TARGET_NOT_IMPLEMENTED" for d in res_v2_ok.evaluation.diagnostics)

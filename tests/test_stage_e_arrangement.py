"""CORE/AUDIO tests for Stage E: decoupled composition vs arrangement pipeline."""

from __future__ import annotations

import hashlib
import json
import wave
from pathlib import Path

import numpy as np
import pytest
from click.testing import CliRunner

from atari_music.api import arrange_song, generate_music
from atari_music.cli import cli
from atari_music.instruments import (
    InstrumentPlanError,
    composition_musical_fingerprint,
    load_instrument_catalog,
    resolve_export_format_version,
)
from atari_music.ir import (
    IREnvelope,
    IRInstrument,
    IRNote,
    IRPattern,
    IRSong,
    plan_v2_pattern_streams,
    song_requires_v2,
)
from atari_music.constants import DISTORTION_4BIT_POLY, DISTORTION_PURE_TONE
from atari_music.mads_exporter import export_mads_asm
from atari_music.xex_layout import validate_xex_file

pytestmark = pytest.mark.core

REPO_ROOT = Path(__file__).resolve().parents[1]
MADS = REPO_ROOT / "tools" / "mads" / "mads.exe"


def _file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _assert_identical_musical_events(song_a: IRSong, song_b: IRSong) -> None:
    """Audit every non-instrument musical field between two IRSong variants."""
    assert composition_musical_fingerprint(song_a) == composition_musical_fingerprint(song_b)
    assert song_a.tempo_bpm == song_b.tempo_bpm
    assert song_a.frames_per_tick == song_b.frames_per_tick
    assert song_a.key == song_b.key
    assert song_a.mode == song_b.mode
    assert song_a.sequence == song_b.sequence
    assert len(song_a.patterns) == len(song_b.patterns)
    for pa, pb in zip(song_a.patterns, song_b.patterns):
        assert pa.id == pb.id
        assert pa.rows == pb.rows
        assert set(pa.tracks.keys()) == set(pb.tracks.keys())
        for ch in pa.tracks:
            na_list, nb_list = pa.tracks[ch], pb.tracks[ch]
            assert len(na_list) == len(nb_list)
            for na, nb in zip(na_list, nb_list):
                assert na.pitch == nb.pitch
                assert na.midi_pitch == nb.midi_pitch
                assert na.duration == nb.duration
                assert na.volume == nb.volume
                assert na.is_rest == nb.is_rest


# ===========================================================================
# 1. End-to-End Composition vs Multi-Variant Arrangement Workflow (§8, §9)
# ===========================================================================


@pytest.mark.audio
def test_ai_compose_once_then_arrange_two_variants_without_ai(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Verify Krok A -> Krok B -> Krok C: AI runs once, two arrangements share exact music & build WAV/ASM/XEX."""
    runner = CliRunner()
    out_dir = tmp_path / "output"
    comp_json = out_dir / "composition.json"

    # Krok A1: ai-compose without WAV/ASM produces ONLY composition.json
    res_ai = runner.invoke(
        cli,
        [
            "ai-compose",
            "--provider",
            "mock",
            "--style",
            "dark atmospheric fantasy soundtrack",
            "-o",
            str(comp_json),
        ],
    )
    assert res_ai.exit_code == 0, res_ai.output
    assert sorted(p.name for p in out_dir.iterdir()) == ["composition.json"]
    comp_hash_before = _file_sha256(comp_json)

    # Krok A2 (optional catalog compose): still produces ONLY JSON, no WAV/ASM
    comp_cat_json = tmp_path / "composition_cat.json"
    res_ai_cat = runner.invoke(
        cli,
        [
            "ai-compose",
            "--provider",
            "mock",
            "--style",
            "dark atmospheric fantasy soundtrack",
            "--use-instrument-catalog",
            "-o",
            str(comp_cat_json),
        ],
    )
    assert res_ai_cat.exit_code == 0, res_ai_cat.output
    assert comp_cat_json.is_file()
    assert not comp_cat_json.with_suffix(".wav").exists()
    assert not comp_cat_json.with_suffix(".asm").exists()

    # Block ALL AI providers during arrangement to prove arrange never invokes AI!
    import atari_music.ai.providers as ai_providers

    def _forbid_ai(*_args, **_kwargs):
        raise AssertionError("arrange must NEVER invoke AI providers")

    monkeypatch.setattr(ai_providers, "get_ai_provider", _forbid_ai)

    # Krok B: Variant A (bass_poly4_punch + harmony + pure_sustain + hihat)
    var_a_dir = tmp_path / "var_a"
    var_a_wav = var_a_dir / "variant_a.wav"
    var_a_xex = var_a_dir / "variant_a.xex"
    args_a = [
        "arrange",
        str(comp_json),
        "--channel-instrument", "1=bass_poly4_punch",
        "--channel-instrument", "2=harmony_soft_square",
        "--channel-instrument", "3=lead_pure_sustain",
        "--channel-instrument", "4=perc_hihat_closed",
        "--program-change-policy", "replace",
        "--output-wav", str(var_a_wav),
    ]
    if MADS.is_file():
        args_a.extend(["--output-xex", str(var_a_xex)])

    res_a = runner.invoke(cli, args_a)
    assert res_a.exit_code == 0, res_a.output

    # Exclusively requested outputs were created (no stray .asm when --output-asm was omitted)
    expected_a = {"variant_a.wav", "variant_a.xex"} if MADS.is_file() else {"variant_a.wav"}
    assert {p.name for p in var_a_dir.iterdir()} == expected_a

    # Krok C: Variant B (bass_15khz_pure + attack_bite + pure_sustain + snare) + JSON + ASM + WAV + XEX
    var_b_dir = tmp_path / "var_b"
    var_b_json = var_b_dir / "variant_b.json"
    var_b_wav = var_b_dir / "variant_b.wav"
    var_b_asm = var_b_dir / "variant_b.asm"
    var_b_xex = var_b_dir / "variant_b.xex"
    args_b = [
        "arrange",
        str(comp_json),
        "--channel-instrument", "1=bass_15khz_pure",
        "--channel-instrument", "2=lead_attack_bite",
        "--channel-instrument", "3=lead_pure_sustain",
        "--channel-instrument", "4=perc_snare_crisp",
        "--program-change-policy", "replace",
        "--output-json", str(var_b_json),
        "--output-wav", str(var_b_wav),
        "--output-asm", str(var_b_asm),
    ]
    if MADS.is_file():
        args_b.extend(["--output-xex", str(var_b_xex)])

    res_b = runner.invoke(cli, args_b)
    assert res_b.exit_code == 0, res_b.output

    # Input composition file untouched byte-for-byte
    assert _file_sha256(comp_json) == comp_hash_before

    # Variant B ASM stays genuine song data ASM even when --output-xex shared the stem
    asm_b_text = var_b_asm.read_text(encoding="utf-8")
    assert "format version 2" in asm_b_text
    assert "harness_start" not in asm_b_text

    # Compare IR variants structurally via API as well: identical notes, different instruments!
    arr_a = arrange_song(
        comp_json,
        channel_instruments={
            1: "bass_poly4_punch",
            2: "harmony_soft_square",
            3: "lead_pure_sustain",
            4: "perc_hihat_closed",
        },
        program_change_policy="replace",
    )
    arr_b = arrange_song(
        comp_json,
        channel_instruments={
            1: "bass_15khz_pure",
            2: "lead_attack_bite",
            3: "lead_pure_sustain",
            4: "perc_snare_crisp",
        },
        program_change_policy="replace",
    )
    _assert_identical_musical_events(arr_a.pokey_ir, arr_b.pokey_ir)
    assert {i.profile_id for i in arr_a.pokey_ir.instruments} != {
        i.profile_id for i in arr_b.pokey_ir.instruments
    }
    # AUDCTL reflects bass_15khz_pure ($01) in Variant B vs $00 in Variant A
    assert any(i.audctl == 0x01 for i in arr_b.pokey_ir.instruments)
    assert "; Mode: AUDCTL=$01" in asm_b_text

    # WAV files differ acoustically & both contain valid audio
    with wave.open(str(var_a_wav), "rb") as wfa, wave.open(str(var_b_wav), "rb") as wfb:
        pcm_a = np.frombuffer(wfa.readframes(wfa.getnframes()), dtype=np.int16)
        pcm_b = np.frombuffer(wfb.readframes(wfb.getnframes()), dtype=np.int16)
    assert len(pcm_a) == len(pcm_b) and len(pcm_a) > 22050
    assert float(np.std(pcm_a.astype(np.float64))) > 500.0
    assert float(np.std(pcm_b.astype(np.float64))) > 500.0
    assert not np.array_equal(pcm_a, pcm_b)

    if MADS.is_file():
        segs_a = validate_xex_file(var_a_xex, player_address=0x6000, music_address=0x8000)
        segs_b = validate_xex_file(var_b_xex, player_address=0x6000, music_address=0x8000)
        assert len(segs_a) >= 2 and len(segs_b) >= 2
        assert var_a_xex.read_bytes() != var_b_xex.read_bytes()


# ===========================================================================
# 2. PROGRAM_CHANGE Policies (preserve, replace, remove) & Channel Independence
# ===========================================================================


def _sample_song_with_program_changes() -> IRSong:
    cat = load_instrument_catalog()
    p_sustain = IRInstrument.from_catalog_profile(0, *cat.resolve_profile_behavior("lead_pure_sustain"))
    p_bite = IRInstrument.from_catalog_profile(1, *cat.resolve_profile_behavior("lead_attack_bite"))
    p_kick = IRInstrument.from_catalog_profile(2, *cat.resolve_profile_behavior("perc_kick_tight"))
    p_snare = IRInstrument.from_catalog_profile(3, *cat.resolve_profile_behavior("perc_snare_crisp"))
    p_bass = IRInstrument.from_catalog_profile(4, *cat.resolve_profile_behavior("bass_poly4_punch"))

    pat = IRPattern(
        id=0,
        name="Main",
        rows=8,
        tracks={
            1: [IRNote(pitch="A-2", midi_pitch=45, duration=8, volume=14, instrument_id=4)],
            3: [
                IRNote(pitch="A-4", midi_pitch=69, duration=4, volume=14, instrument_id=0),
                IRNote(pitch="C-5", midi_pitch=72, duration=4, volume=14, instrument_id=1, pending_program_changes=(1,)),
            ],
            4: [
                IRNote(duration=4, volume=15, instrument_id=2, channel_role="percussion"),
                IRNote(duration=4, volume=14, instrument_id=3, channel_role="percussion", pending_program_changes=(3,)),
            ],
        },
    )
    return IRSong(
        title="PC Policies",
        frames_per_tick=4,
        instruments=[p_sustain, p_bite, p_kick, p_snare, p_bass],
        patterns=[pat],
        sequence=[0],
        initial_channel_instruments={1: 4, 2: 0, 3: 0, 4: 2},
    )


def test_program_change_policies_preserve_replace_remove_and_channel_isolation() -> None:
    """Verify preserve / replace / remove affect only overridden channels and keep original immutable."""
    orig = _sample_song_with_program_changes()
    orig_snapshot = orig.model_dump()
    orig_fp = composition_musical_fingerprint(orig)

    # 1. No overrides -> unchanged clone
    no_op = arrange_song(orig, channel_instruments=None)
    assert no_op.pokey_ir.model_dump() == orig_snapshot
    assert composition_musical_fingerprint(no_op.pokey_ir) == orig_fp

    # 2. Override ONLY CH3 with lead_pure_pluck under preserve:
    #    - CH3 starts with lead_pure_pluck, note 1 keeps PROGRAM_CHANGE -> lead_attack_bite
    #    - Unassigned CH1 & CH4 remain completely untouched!
    res_preserve = arrange_song(
        orig,
        channel_instruments={3: "lead_pure_pluck"},
        program_change_policy="preserve",
    )
    assert composition_musical_fingerprint(res_preserve.pokey_ir) == orig_fp
    ir_p = res_preserve.pokey_ir
    ch3_notes_p = ir_p.patterns[0].tracks[3]
    assert ir_p.instruments[ch3_notes_p[0].instrument_id].profile_id == "lead_pure_pluck"
    assert ir_p.instruments[ch3_notes_p[1].instrument_id].profile_id == "lead_attack_bite"
    assert ch3_notes_p[1].pending_program_changes == (ch3_notes_p[1].instrument_id,)
    # Unassigned CH4 kept perc_kick_tight -> perc_snare_crisp
    ch4_notes_p = ir_p.patterns[0].tracks[4]
    assert ir_p.instruments[ch4_notes_p[0].instrument_id].profile_id == "perc_kick_tight"
    assert ir_p.instruments[ch4_notes_p[1].instrument_id].profile_id == "perc_snare_crisp"
    assert len(ch4_notes_p[1].pending_program_changes) == 1

    # 3. Override CH3 with lead_pure_pluck under replace:
    #    - CH3 initial & note 0 & note 1 AND the PROGRAM_CHANGE target all become lead_pure_pluck
    #    - CH4 stays untouched!
    res_replace = arrange_song(
        orig,
        channel_instruments={3: "lead_pure_pluck"},
        program_change_policy="replace",
    )
    assert composition_musical_fingerprint(res_replace.pokey_ir) == orig_fp
    ir_r = res_replace.pokey_ir
    ch3_notes_r = ir_r.patterns[0].tracks[3]
    assert ir_r.instruments[ch3_notes_r[0].instrument_id].profile_id == "lead_pure_pluck"
    assert ir_r.instruments[ch3_notes_r[1].instrument_id].profile_id == "lead_pure_pluck"
    assert ch3_notes_r[1].pending_program_changes == (ch3_notes_r[1].instrument_id,)
    ch4_notes_r = ir_r.patterns[0].tracks[4]
    assert ir_r.instruments[ch4_notes_r[0].instrument_id].profile_id == "perc_kick_tight"
    assert ir_r.instruments[ch4_notes_r[1].instrument_id].profile_id == "perc_snare_crisp"

    # 4. Override CH3 with lead_pure_pluck under remove:
    #    - CH3 PROGRAM_CHANGE events vanish cleanly; all CH3 notes use lead_pure_pluck
    #    - CH4 stays untouched!
    res_remove = arrange_song(
        orig,
        channel_instruments={3: "lead_pure_pluck"},
        program_change_policy="remove",
    )
    assert composition_musical_fingerprint(res_remove.pokey_ir) == orig_fp
    ir_rem = res_remove.pokey_ir
    ch3_notes_rem = ir_rem.patterns[0].tracks[3]
    assert all(ir_rem.instruments[n.instrument_id].profile_id == "lead_pure_pluck" for n in ch3_notes_rem)
    assert all(n.pending_program_changes == () for n in ch3_notes_rem)
    _, streams_rem = plan_v2_pattern_streams(ir_rem)
    assert not any(kind == "cmd" for kind, _raw, _c in streams_rem[0][3])
    assert any(kind == "cmd" for kind, _raw, _c in streams_rem[0][4])

    # Original IRSong object was never mutated
    assert orig.model_dump() == orig_snapshot


# ===========================================================================
# 3. v1 vs v2 Compatibility, Partial Overrides, py65 Parity & Error Validation
# ===========================================================================


def test_arrange_v1_and_v2_compatibility_and_ir_json_roundtrip(tmp_path: Path) -> None:
    """Static core_v1 arrangements preserve format v1; v2 arrangements compile identically in py65."""
    # Simple plain v1 song exported as POKEY IR JSON
    v1_song = IRSong(
        title="Plain V1",
        frames_per_tick=4,
        instruments=[
            IRInstrument(
                id=0,
                name="Bass",
                distortion=DISTORTION_4BIT_POLY,
                role="bass",
                envelope=IREnvelope(attack_frames=0, decay_frames=3, sustain_vol=10, release_frames=1),
            ),
            IRInstrument(
                id=1,
                name="Lead",
                distortion=DISTORTION_PURE_TONE,
                role="melody",
                envelope=IREnvelope(attack_frames=1, decay_frames=2, sustain_vol=12, release_frames=1),
            ),
        ],
        patterns=[
            IRPattern(
                id=0,
                rows=8,
                tracks={
                    1: [IRNote(pitch="C-3", midi_pitch=48, duration=8, volume=12, instrument_id=0)],
                    3: [IRNote(pitch="A-4", midi_pitch=69, duration=8, volume=14, instrument_id=1)],
                },
            )
        ],
        sequence=[0],
    )
    ir_json = tmp_path / "plain_v1_ir.json"
    v1_song.to_json_file(ir_json)

    # Re-arrange ONLY CH3 with static core_v1 lead_pure_pluck -> still format v1 under auto!
    arr_v1 = arrange_song(ir_json, channel_instruments={3: "lead_pure_pluck"})
    assert arr_v1.metadata.format_version == 1
    assert resolve_export_format_version(arr_v1.pokey_ir, "auto") == 1
    assert song_requires_v2(arr_v1.pokey_ir) == []
    assert composition_musical_fingerprint(arr_v1.pokey_ir) == composition_musical_fingerprint(v1_song)
    asm_v1 = arr_v1.export_mads(tmp_path / "arr_v1.asm")
    assert "; format version (0 = no version byte" in asm_v1

    # Now re-arrange CH1 to v2 bass_poly4_punch -> auto promotes to v2 & passes py65 oracle parity
    arr_v2 = arrange_song(ir_json, channel_instruments={1: "bass_poly4_punch", 3: "lead_attack_bite"})
    assert arr_v2.metadata.format_version == 2
    assert composition_musical_fingerprint(arr_v2.pokey_ir) == composition_musical_fingerprint(v1_song)
    if MADS.is_file():
        from atari_music import frame_simulator
        from tests.test_stage_c_player_v2_parity import _compile_and_run_py65

        frames_py65, syms, _, mpu = _compile_and_run_py65(arr_v2.pokey_ir, tmp_path, "arr_v2_p65", 24)
        frames_bin = frame_simulator.simulate_v2_binary_frames(mpu.memory, syms["song_data"], 24)
        assert np.array_equal(frames_py65, frames_bin)


def test_arrange_validation_errors_api_and_cli(tmp_path: Path) -> None:
    """Invalid catalog instruments, deferred profiles, channel conflicts, and v1/v2 mismatches fail cleanly."""
    comp_res = generate_music(profile="action", seed=42)
    ir_path = tmp_path / "action_ir.json"
    comp_res.save_json(ir_path)

    with pytest.raises(InstrumentPlanError, match="not found in catalog"):
        arrange_song(ir_path, channel_instruments={3: "nonexistent_patch"})

    with pytest.raises(InstrumentPlanError, match="DEFERRED|deferred|tier"):
        arrange_song(ir_path, channel_instruments={3: "lead_hpf_pwm"})

    with pytest.raises(InstrumentPlanError, match="cannot bind to channel 1"):
        arrange_song(ir_path, channel_instruments={1: "perc_kick_tight"})

    with pytest.raises(InstrumentPlanError, match="existing independent notes on channel 2"):
        arrange_song(ir_path, channel_instruments={1: "bass_16bit_pure"})

    with pytest.raises(InstrumentPlanError, match="FORMAT_VERSION_CONFLICT|BEHAVIOR_NOT_IN_TARGET_TIER"):
        arrange_song(ir_path, channel_instruments={3: "lead_attack_bite"}, player_version="v1")

    runner = CliRunner()
    bad_cli = runner.invoke(
        cli,
        ["arrange", str(ir_path), "--channel-instrument", "1=perc_kick_tight", "--output-wav", str(tmp_path / "fail.wav")],
    )
    assert bad_cli.exit_code != 0
    assert not (tmp_path / "fail.wav").exists()


def test_v1_to_v2_promotion_emits_explicit_vibrato_warning_without_silent_loss() -> None:
    """Promoting a v1 song with legacy vibrato to v2 must warn with channel, parameters, and reason."""
    from atari_music.instruments import (
        LEGACY_VIBRATO_STRIPPED_ON_V2_PROMOTION,
        arrange_ir_song,
    )

    base_song = generate_music(profile="action", seed=42).pokey_ir
    # Verify baseline carries legacy vibrato on CH3 lead
    lead_orig = next(i for i in base_song.instruments if i.vibrato_depth or i.vibrato_speed)
    orig_depth, orig_speed = lead_orig.vibrato_depth, lead_orig.vibrato_speed
    assert orig_depth > 0 and orig_speed > 0

    # 1. Staying in v1 (core_v1 override on CH4, auto): vibrato is preserved untouched with no warning
    stay_v1_song, stay_report = arrange_ir_song(
        base_song,
        channel_instruments={4: "lead_pure_pluck"},
        player_version="auto",
    )
    assert song_requires_v2(stay_v1_song) == []
    kept_lead = next(i for i in stay_v1_song.instruments if i.name == lead_orig.name)
    assert kept_lead.vibrato_depth == orig_depth
    assert kept_lead.vibrato_speed == orig_speed
    assert stay_report is not None
    assert not any(d.code == LEGACY_VIBRATO_STRIPPED_ON_V2_PROMOTION for d in stay_report.diagnostics)

    # 2. Promoting to v2 via another channel (CH4 -> perc_kick_tight):
    # untouched CH3 vibrato is cleared for v2 Iter 1 WITH explicit diagnostic (channel, params, reason)
    promoted_song, promo_report = arrange_ir_song(
        base_song,
        channel_instruments={4: "perc_kick_tight"},
        player_version="auto",
    )
    assert song_requires_v2(promoted_song)
    assert promo_report is not None
    vib_diags = [d for d in promo_report.diagnostics if d.code == LEGACY_VIBRATO_STRIPPED_ON_V2_PROMOTION]
    assert len(vib_diags) == 1
    d = vib_diags[0]
    assert d.severity == "WARNING"
    assert d.channel == 3
    assert f"vibrato_depth={orig_depth}" in d.message
    assert f"vibrato_speed={orig_speed}" in d.message
    assert "v2 Iter 1" in d.message

    # Promoted song exports cleanly to v2 without mutating the original base_song
    promo_lead = next(i for i in promoted_song.instruments if i.name == lead_orig.name)
    assert promo_lead.vibrato_depth == 0 and promo_lead.vibrato_speed == 0
    assert lead_orig.vibrato_depth == orig_depth and lead_orig.vibrato_speed == orig_speed
    assert "format version 2" in export_mads_asm(promoted_song, format_version=2)

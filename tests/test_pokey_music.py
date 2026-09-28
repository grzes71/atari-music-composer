"""Unit tests for Atari 8-bit POKEY Music Analysis Toolkit."""

from pathlib import Path

import pytest

from atari_music.constants import (
    AUDCTL_15KHZ,
    AUDCTL_CH1_179MHZ,
    AUDCTL_JOIN_1_2_16BIT,
    DISTORTION_PURE_TONE,
    DISTORTION_WHITE_NOISE,
)
from atari_music.events import PokeyStateReconstructor, parse_dump_tokens
from atari_music.features import (
    calculate_channel_frequency,
    frequency_to_musical_pitch,
    interpret_voice_state,
    midi_to_note_name,
)
from atari_music.models import PokeyEvent
from conftest import require_local_artifact


def test_midi_to_note_name():
    assert midi_to_note_name(69) == "A4"
    assert midi_to_note_name(60) == "C4"
    assert midi_to_note_name(57) == "A3"
    assert midi_to_note_name(72) == "C5"


def test_calculate_channel_frequency_8bit():
    # 64 kHz clock, AUDF = 71 -> 63920.89 / (2 * 72) ≈ 443.89 Hz (near A4)
    freq, conf = calculate_channel_frequency(channel_idx=1, audf_val=71, audctl_val=0)
    assert freq is not None
    assert 438.0 <= freq <= 445.0
    assert conf >= 0.90


def test_calculate_channel_frequency_16bit():
    # Joined 1+2, 1.77 MHz clock: div_16 = 2000 -> 1773447 / (2 * 2007) ≈ 441.8 Hz
    pair_low = 2000 % 256
    pair_high = 2000 // 256
    audctl = AUDCTL_JOIN_1_2_16BIT | AUDCTL_CH1_179MHZ
    freq, conf = calculate_channel_frequency(
        channel_idx=2, audf_val=pair_high, audctl_val=audctl, audf_pair_low=pair_low
    )
    assert freq is not None
    assert 440.0 <= freq <= 445.0
    assert conf == 0.99


def test_frequency_to_musical_pitch_pure_tone():
    # 440.0 Hz should map exactly to A4 with high confidence
    note, conf, midi, cents = frequency_to_musical_pitch(440.0, DISTORTION_PURE_TONE)
    assert note == "A4"
    assert conf >= 0.90
    assert midi == 69.0
    assert cents == 0.0


def test_frequency_to_musical_pitch_noise_rejected():
    # White noise should not map to musical pitch
    note, conf, midi, cents = frequency_to_musical_pitch(440.0, DISTORTION_WHITE_NOISE)
    assert note is None
    assert conf == 0.0


def test_parse_dump_tokens_mono():
    line = "  0.04: 61 00  67 AC  00 00  00 00  78\n"
    res = parse_dump_tokens(line)
    assert res is not None
    time_sec, p0, p1 = res
    assert time_sec == 0.04
    assert len(p0) == 9
    assert p0[0] == 0x61
    assert p0[3] == 0xAC
    assert p0[8] == 0x78
    assert p1 is None


def test_parse_dump_tokens_stereo():
    line = "  0.00: 0E C4  00 A5  00 A4  01 10  02  |  0E C4  00 A5  00 A4  01 10  00\n"
    res = parse_dump_tokens(line)
    assert res is not None
    time_sec, p0, p1 = res
    assert time_sec == 0.00
    assert len(p0) == 9
    assert len(p1) == 9
    assert p0[8] == 0x02
    assert p1[8] == 0x00


def test_pokey_state_reconstructor():
    recon = PokeyStateReconstructor(is_stereo=False)
    evt1 = PokeyEvent(frame=0, time_ms=0.0, pokey=0, register="AUDF1", old=0, new=97)
    evt2 = PokeyEvent(frame=0, time_ms=0.0, pokey=0, register="AUDC1", old=0, new=172)
    recon.apply_event(evt1)
    recon.apply_event(evt2)

    st = recon.get_state_dict()
    assert st["pokey0"]["AUDF1"] == 97
    assert st["pokey0"]["AUDC1"] == 172
    assert st["pokey0"]["AUDCTL"] == 0
    assert st["pokey1"] is None


def test_ir_creation_and_size_budget():
    """Verify procedural generation creates valid IR adhering strictly to < 2KB memory budget."""
    from atari_music.generator import generate_song
    from atari_music.ir import calculate_ir_binary_size, IRSong

    song = generate_song(seed=42)
    assert isinstance(song, IRSong)
    assert len(song.instruments) >= 4
    assert len(song.patterns) >= 3
    assert len(song.sequence) >= 8

    size_bytes = calculate_ir_binary_size(song)
    assert size_bytes <= 2048, f"Song exceeds 2KB budget: {size_bytes} bytes"
    assert size_bytes > 200, "Song IR too small or unpopulated"


def test_compile_ir_to_pokey_frames():
    """Verify IR compiles cleanly into 50Hz POKEY register frames."""
    from atari_music.generator import generate_song
    from atari_music.ir import compile_ir_to_pokey_frames

    song = generate_song(seed=7, parameters={"uses_16bit_bass": True})
    frames = compile_ir_to_pokey_frames(song)

    assert frames.ndim == 2
    assert frames.shape[1] == 9
    assert frames.shape[0] >= 500  # At least 10 seconds of audio at 50Hz
    # In 16-bit bass mode, AUDCTL should have bit 4 set ($10)
    assert bool(frames[0, 8] & 0x10) is True


def test_pokey_synth_wav_rendering(tmp_path):
    """Verify POKEY software synthesizer renders frames to valid 16-bit PCM WAV."""
    import numpy as np
    import wave
    from atari_music.pokey_synth import render_pokey_to_wav

    # 100 frames = 2 seconds at 50Hz
    frames = np.zeros((100, 9), dtype=np.uint8)
    frames[:, 0] = 71     # AUDF1 (A4)
    frames[:, 1] = 0xAF   # AUDC1 ($A0 pure tone, vol 15)

    wav_file = tmp_path / "test_synth.wav"
    render_pokey_to_wav(frames, wav_file, sample_rate=44100)

    assert wav_file.exists()
    assert wav_file.stat().st_size > 0

    with wave.open(str(wav_file), "rb") as wf:
        assert wf.getnchannels() == 1
        assert wf.getsampwidth() == 2
        assert wf.getframerate() == 44100
        assert wf.getnframes() == 100 * (44100 // 50)


def test_archetypes_mining():
    """Verify empirical archetype mining extracts archetypes for all 4 categories."""
    from atari_music.archetypes import mine_archetypes_from_dataset

    dataset_path = Path("dataset/dataset.jsonl")
    require_local_artifact(dataset_path)
    lib = mine_archetypes_from_dataset(dataset_path)
    assert len(lib.melody_archetypes) >= 5
    assert len(lib.rhythm_archetypes) >= 4
    assert len(lib.bass_archetypes) >= 4
    assert len(lib.percussion_archetypes) >= 3


def test_control_generator():
    """Verify naive control generator respects POKEY constraints and creates valid IR."""
    from atari_music.control_generator import generate_control_song
    from atari_music.ir import IRSong, calculate_ir_binary_size, compile_ir_to_pokey_frames

    ctrl_song = generate_control_song(seed=101)
    assert isinstance(ctrl_song, IRSong)
    assert len(ctrl_song.patterns) == 4
    assert len(ctrl_song.instruments) == 4
    size_bytes = calculate_ir_binary_size(ctrl_song)
    assert size_bytes <= 2048

    frames = compile_ir_to_pokey_frames(ctrl_song)
    assert frames.shape[1] == 9
    assert frames.shape[0] >= 500


def test_listening_test_artifacts():
    """Verify blinded listening test folder contains all 30 WAVs, CSV, README, and answer key."""
    test_dir = Path("listening_test")
    require_local_artifact(test_dir)
    assert (test_dir / "README.md").exists()
    assert (test_dir / "rating_template.csv").exists()
    assert (test_dir / "answer_key.json").exists()
    assert (test_dir / "group_statistics.json").exists()

    wavs = list(test_dir.glob("sample_*.wav"))
    assert len(wavs) == 30
    for w in wavs:
        # Exactly 20.00 seconds at 44.1 kHz 16-bit mono = 1,764,044 bytes
        assert w.stat().st_size == 1764044


def test_memorization_and_novelty_metrics():
    """Verify longest common substring and novelty evaluation works accurately."""
    from atari_music.memorization_analysis import longest_common_substring, evaluate_song_novelty, DatasetCorpus
    from atari_music.generator import generate_song

    # Test longest common substring algorithm
    s1 = [60, 62, 64, 65, 67, 69, 71]
    s2 = [55, 57, 62, 64, 65, 72]
    match = longest_common_substring(s1, s2)
    assert match == 3  # [62, 64, 65]

    song = generate_song(seed=42)
    corpus = DatasetCorpus()
    corpus.all_pitch_sequences = [[60, 62, 64, 65], [67, 69, 71, 72]]
    corpus.all_interval_sequences = [[2, 2, 1], [2, 2, 1]]
    corpus.all_rhythm_sequences = [[2, 2, 2, 2]]

    res = evaluate_song_novelty(song, corpus)
    assert "composite_novelty" in res
    assert 0.0 <= res["composite_novelty"] <= 1.0


def test_composer_v2_music_ir_and_seed():
    """Verify Music IR structure and deterministic generation with fixed seed."""
    from atari_music.composer_v2 import compose_song_v2, ComposerV2Config
    from atari_music.music_ir import MusicSong

    cfg1 = ComposerV2Config(seed=42, novelty=0.5)
    res1 = compose_song_v2(cfg1)

    cfg2 = ComposerV2Config(seed=42, novelty=0.5)
    res2 = compose_song_v2(cfg2)

    assert isinstance(res1.music_ir, MusicSong)
    assert res1.quality_report.memory_size == res2.quality_report.memory_size
    assert res1.quality_report.pattern_count == res2.quality_report.pattern_count
    assert res1.quality_report.pitch_range == res2.quality_report.pitch_range
    assert 2 <= res1.quality_report.channels_used <= 4
    assert res1.quality_report.channels_used == res2.quality_report.channels_used
    assert res1.quality_report.memory_size <= 2048


def test_composer_v2_channel_limits():
    """Verify min_channels and max_channels limits (e.g. strict 2-channel mode)."""
    from atari_music.composer_v2 import compose_song_v2, ComposerV2Config

    cfg_2ch = ComposerV2Config(seed=77, min_channels=2, max_channels=2)
    res_2ch = compose_song_v2(cfg_2ch)

    assert res_2ch.quality_report.channels_used == 2
    for pat in res_2ch.music_ir.patterns:
        assert len(pat.tracks) == 2
        roles = {t.role.value for t in pat.tracks.values()}
        assert roles == {"melody", "bass"}
    assert res_2ch.quality_report.memory_size <= 2048


def test_composer_v2_motivic_mutation():
    """Verify motivic mutations generate new phrases maintaining contour/rhythm properties."""
    from atari_music.music_ir import MusicPhrase, MelodicContour
    from atari_music.mutations import generate_phrase_variation
    import random

    phrase_a = MusicPhrase(
        id="A",
        contour=MelodicContour.ASCENDING,
        intervals=[2, 2, 3, -2, -3],
        rhythm=[4, 4, 4, 4],
    )

    rng = random.Random(123)
    scale = [0, 2, 4, 5, 7, 9, 11]
    phrase_var = generate_phrase_variation(phrase_a, variation_id="A'", novelty=0.8, scale=scale, rng=rng)

    assert phrase_var.id == "A'"
    assert phrase_var.contour == phrase_a.contour
    assert sum(phrase_var.rhythm) == sum(phrase_a.rhythm)
    # At high novelty (0.8), intervals or rhythm should have mutated
    assert (phrase_var.intervals != phrase_a.intervals) or (phrase_var.rhythm != phrase_a.rhythm)


def test_composer_v2_memory_deduplication():
    """Verify pattern deduplication compresses identical patterns."""
    from atari_music.ir import IRSong, IRPattern, IRNote, calculate_ir_binary_size
    from atari_music.composer_v2 import deduplicate_pokey_patterns

    p1 = IRPattern(id=0, name="P0", rows=32, tracks={0: [IRNote(pitch="C-4", duration=4, volume=12, distortion=10)]})
    p2 = IRPattern(id=1, name="P1", rows=32, tracks={0: [IRNote(pitch="C-4", duration=4, volume=12, distortion=10)]}) # Duplicate of p1
    p3 = IRPattern(id=2, name="P2", rows=32, tracks={0: [IRNote(pitch="E-4", duration=4, volume=12, distortion=10)]})

    song = IRSong(
        title="Test",
        author="Tester",
        tempo_bpm=120,
        frames_per_tick=4,
        key="C",
        mode="minor",
        instruments=[],
        patterns=[p1, p2, p3],
        sequence=[0, 1, 2, 0]
    )

    initial_size = calculate_ir_binary_size(song)
    deduped_song, num_removed = deduplicate_pokey_patterns(song)
    final_size = calculate_ir_binary_size(deduped_song)

    assert num_removed == 1
    assert len(deduped_song.patterns) == 2
    assert final_size < initial_size
    # Sequence mapping should point to p1's id for old p2
    assert deduped_song.sequence == [0, 0, 1, 0]



def test_composer_v2_generation_failure_handling():
    """Verify generator raises RuntimeError when strict impossible budget cannot be satisfied."""
    import pytest
    from atari_music.composer_v2 import compose_song_v2, ComposerV2Config

    impossible_cfg = ComposerV2Config(
        max_size=30,  # Far below minimum possible song header + pattern size
        max_attempts=5,
    )
    with pytest.raises(RuntimeError, match="Generation failed"):
        compose_song_v2(impossible_cfg)


def test_listening_test_v2_artifacts_and_validation():
    """Verify Stage 6.5 listening test v2 artifacts, 80 samples, keys, and validation checks."""
    from atari_music.listening_test_v2 import validate_listening_test_v2

    test_dir = Path("listening_test_v2")
    require_local_artifact(test_dir)
    assert (test_dir / "README.md").exists()
    assert (test_dir / "rating_template.csv").exists()
    assert (test_dir / "pairwise_rating_template.csv").exists()
    assert (test_dir / "answer_key.json").exists()
    assert (test_dir / "pairwise_answer_key.json").exists()
    assert (test_dir / "group_statistics.json").exists()

    wavs = list(test_dir.glob("sample_*.wav"))
    assert len(wavs) == 80

    # Verify pre-flight validation succeeds
    val_res = validate_listening_test_v2(test_dir)
    assert val_res["status"] == "VALIDATION PASSED: EXPERIMENT READY"
    assert val_res["total_wav_count"] == 80
    assert val_res["group_distribution"] == {"A": 20, "B": 20, "C": 20, "D": 20}
    assert val_res["pairwise_count"] == 30

    report_p = Path("stage6_5_listening_report.md")
    require_local_artifact(report_p)
    assert report_p.stat().st_size > 1000


def test_diversity_audit_artifacts_and_selection():
    """Verify Stage 6.6 diversity audit artifacts, 30 selected WAVs, and representation quotas."""
    from pathlib import Path
    import json
    import wave

    sel_dir = Path("listening_test_v2_selected")
    require_local_artifact(sel_dir)
    assert (sel_dir / "README.md").exists()
    assert (sel_dir / "rating_template.csv").exists()
    assert (sel_dir / "answer_key.json").exists()
    assert (sel_dir / "pairwise_rating_template.csv").exists()
    assert (sel_dir / "pairwise_answer_key.json").exists()

    wavs = list(sel_dir.glob("sample_*.wav"))
    assert len(wavs) == 30

    # Verify audio properties of all 30 selected tracks
    for w in wavs:
        with wave.open(str(w), "rb") as wf:
            assert wf.getnchannels() == 1
            assert wf.getsampwidth() == 2
            assert wf.getframerate() == 44100
            assert wf.getnframes() > 44100 * 5

    # Check quotas in answer_key.json
    with open(sel_dir / "answer_key.json", "r", encoding="utf-8") as f:
        catalog = json.load(f)
    assert len(catalog) == 30

    group_counts = {}
    for entry in catalog:
        grp = entry["group"]
        group_counts[grp] = group_counts.get(grp, 0) + 1

    assert group_counts == {"A": 6, "B": 7, "C": 10, "D": 7}

    # Verify report existence and size
    report_p = Path("stage6_6_diversity_report.md")
    require_local_artifact(report_p)
    assert report_p.stat().st_size > 5000


def test_composer_v3_profile_constraints():
    """Verify all 6 profiles satisfy their tempo bounds, allowed modes, and register limits."""
    from atari_music.composer_v3 import compose_song_v3
    from atari_music.profiles import PROFILES

    for prof_name, prof in PROFILES.items():
        res = compose_song_v3(profile=prof_name, seed=77)
        q = res.quality_report

        # Tempo bound check
        assert prof.tempo_range[0] <= q.tempo <= prof.tempo_range[1], f"{prof_name} tempo {q.tempo} out of range"
        # Allowed mode check
        assert res.music_ir.mode in prof.allowed_modes, f"{prof_name} mode {res.music_ir.mode} not in allowed modes"
        # Channels check
        assert prof.min_channels <= q.channels_used <= prof.max_channels
        # Memory budget
        assert q.memory_size <= 2048


def test_composer_v3_determinism():
    """Verify strict determinism: identical seed = identical song; different seed = distinct song."""
    from atari_music.composer_v3 import compose_song_v3

    # Identical seed
    r1 = compose_song_v3(profile="dungeon", seed=1234)
    r2 = compose_song_v3(profile="dungeon", seed=1234)
    assert r1.quality_report.tempo == r2.quality_report.tempo
    assert r1.quality_report.memory_size == r2.quality_report.memory_size
    assert r1.quality_report.form == r2.quality_report.form
    assert r1.music_ir.sequence == r2.music_ir.sequence

    # Different seed within same profile
    r3 = compose_song_v3(profile="dungeon", seed=1235)
    # At least seed or pitch sequence or key differs
    assert r1.music_ir.title != r3.music_ir.title


def test_composer_v3_profile_separation():
    """Verify measurable musical separation between contrasting profiles."""
    from atari_music.composer_v3 import compose_song_v3

    action_song = compose_song_v3(profile="action", seed=42)
    dungeon_song = compose_song_v3(profile="dungeon", seed=42)
    title_song = compose_song_v3(profile="title", seed=42)

    # 1. Action vs Dungeon BPM separation must be huge (> 60 BPM difference)
    bpm_diff = action_song.quality_report.tempo - dungeon_song.quality_report.tempo
    assert bpm_diff >= 60, f"Expected Action BPM >> Dungeon BPM, got diff {bpm_diff}"

    # 2. Action density > Dungeon density
    assert action_song.quality_report.melodic_density > dungeon_song.quality_report.melodic_density

    # 3. Forms differ
    assert "OUTRO" in title_song.quality_report.form or "INTRO" in title_song.quality_report.form
    assert action_song.quality_report.tempo >= 155
    assert dungeon_song.quality_report.tempo <= 90


def test_composer_v3_memory_budget_and_18_tracks():
    """Verify 18 experimental tracks in experiments/composer_v3/ all pass memory <= 2048 B."""
    import json

    sum_p = Path("experiments/composer_v3/summary.json")
    require_local_artifact(sum_p)

    with open(sum_p, "r", encoding="utf-8") as f:
        data = json.load(f)

    assert len(data) == 6
    total_tracks = 0
    for p_name, tracks in data.items():
        assert len(tracks) == 3
        for t in tracks:
            total_tracks += 1
            assert t["memory_size_bytes"] <= 2048
            assert Path(t["wav_path"]).exists()
            assert Path(t["json_path"]).exists()

    assert total_tracks == 18


def test_listening_test_v3_artifacts_and_validation():
    """Verify Stage 7.1 blind listening test artifacts, 18 samples, keys, and report."""
    import json

    test_dir = Path("listening_test_v3")
    require_local_artifact(test_dir)
    assert (test_dir / "README.md").exists()
    assert (test_dir / "rating_template.csv").exists()
    assert (test_dir / "pairwise_rating_template.csv").exists()
    assert (test_dir / "answer_key.json").exists()
    assert (test_dir / "pairwise_answer_key.json").exists()

    wavs = list(test_dir.glob("sample_*.wav"))
    assert len(wavs) == 18

    with open(test_dir / "answer_key.json", "r", encoding="utf-8") as f:
        key_data = json.load(f)
    assert len(key_data) == 18

    # Check distribution of 3 per profile
    prof_counts = {}
    for item in key_data:
        p = item["true_profile"]
        prof_counts[p] = prof_counts.get(p, 0) + 1
    assert prof_counts == {
        "TITLE": 3,
        "EXPLORATION": 3,
        "ACTION": 3,
        "FUNNY": 3,
        "DUNGEON": 3,
        "ENDING": 3,
    }

    # Verify pairwise comparisons: exactly 12 pairs
    with open(test_dir / "pairwise_answer_key.json", "r", encoding="utf-8") as f:
        pairs = json.load(f)
    assert len(pairs) == 12

    # Verify Stage 7.1 report exists and contains required sections
    report_p = Path("stage7_1_listening_report.md")
    require_local_artifact(report_p)
    report_text = report_p.read_text(encoding="utf-8")
    assert "TITLE EXPL ACTION FUNNY DUNGEON ENDING" in report_text
    assert "Weryfikacja kryteriów akceptacji" in report_text


def test_composer_v4_max_4_channels_and_valid_roles():
    """Verify Composer v4 strictly uses <= 4 channels and official roles."""
    from atari_music.composer_v4 import compose_song_v4

    for prof in ["action", "title", "dungeon", "funny", "exploration", "ending"]:
        res = compose_song_v4(profile=prof, seed=123)
        assert res.quality_report.channels_used <= 4
        assert res.quality_report.active_channels_audio <= 4

        # Validate pattern tracks
        for pat in res.pokey_ir.patterns:
            for ch_idx, notes in pat.tracks.items():
                assert 1 <= ch_idx <= 4, f"Illegal channel index {ch_idx}"
                for n in notes:
                    assert n.channel_role in ("melody", "bass", "harmony", "percussion")


def test_composer_v4_determinism():
    """Verify strict determinism: identical profile + seed yields identical result."""
    from atari_music.composer_v4 import compose_song_v4

    res1 = compose_song_v4(profile="action", seed=777)
    res2 = compose_song_v4(profile="action", seed=777)

    assert res1.pokey_ir.sequence == res2.pokey_ir.sequence
    assert res1.quality_report.memory_size == res2.quality_report.memory_size
    assert res1.quality_report.tempo == res2.quality_report.tempo
    assert len(res1.pokey_ir.patterns) == len(res2.pokey_ir.patterns)

    # Check note-by-note equality
    for p1, p2 in zip(res1.pokey_ir.patterns, res2.pokey_ir.patterns):
        for ch in range(1, 5):
            notes1 = p1.tracks.get(ch, [])
            notes2 = p2.tracks.get(ch, [])
            assert len(notes1) == len(notes2)
            for n1, n2 in zip(notes1, notes2):
                assert n1.pitch == n2.pitch
                assert n1.duration == n2.duration
                assert n1.volume == n2.volume


def test_composer_v4_presence_of_second_voice_and_no_dummy_notes():
    """Verify genuine COUNTER/HARMONY second voice with real notes (no zero-velocity dummies)."""
    from atari_music.composer_v4 import compose_song_v4

    for prof in ["title", "action", "ending", "funny", "exploration", "dungeon"]:
        res = compose_song_v4(profile=prof, seed=42)
        # Check channel 2 notes
        ch2_notes_found = 0
        for pat in res.pokey_ir.patterns:
            ch2_notes = pat.tracks.get(2, [])
            for n in ch2_notes:
                if not n.is_rest:
                    ch2_notes_found += 1
                    # Must NOT be a fake dummy note
                    assert n.volume > 0, "Fake dummy note with zero volume detected!"
                    assert n.midi_pitch is not None, "Non-rest note without pitch detected!"
        assert ch2_notes_found > 0, f"Profile {prof} missing second voice notes on channel 2!"


def test_composer_v4_dynamic_section_activity():
    """Verify dynamic orchestration: sections breathe (e.g. Intro has fewer voices than B)."""
    from atari_music.composer_v4 import compose_song_v4

    # Title profile with INTRO A B A OUTRO
    res = compose_song_v4(profile="title", seed=101)
    sec_counts = res.quality_report.section_channel_counts

    if "INTRO" in sec_counts and "B" in sec_counts:
        assert sec_counts["INTRO"] < sec_counts["B"], "Expected INTRO to be more sparse than climax section B"

    # Action profile should have 4 channels active in all main sections
    res_act = compose_song_v4(profile="action", seed=301)
    assert res_act.quality_report.section_channel_counts.get("B") == 4
    assert res_act.quality_report.section_channel_counts.get("A") == 4


def test_composer_v4_memory_budget_and_18_tracks():
    """Verify 18 experimental tracks in experiments/composer_v4/ all satisfy memory <= 2048 B."""
    import json

    sum_p = Path("experiments/composer_v4/summary.json")
    require_local_artifact(sum_p)

    with open(sum_p, "r", encoding="utf-8") as f:
        data = json.load(f)

    assert len(data) == 6
    total_tracks = 0
    for p_name, tracks in data.items():
        assert len(tracks) == 3
        for t in tracks:
            total_tracks += 1
            assert t["memory_size_bytes"] <= 2048, f"Track {t['track_id']} exceeded 2048 B: {t['memory_size_bytes']} B"
            assert t["channels_used"] == 4, f"Track {t['track_id']} failed to utilize 4 channels"
            assert Path(t["wav_path"]).exists()
            assert Path(t["json_path"]).exists()

    assert total_tracks == 18


def test_composer_v4_compilation_and_report():
    """Verify POKEY frame synthesis and Stage 8 comparative report presence."""
    from atari_music.composer_v4 import compose_song_v4
    from atari_music.ir import compile_ir_to_pokey_frames

    res = compose_song_v4(profile="action", seed=999)
    frames = compile_ir_to_pokey_frames(res.pokey_ir)
    assert frames.shape[1] == 9
    assert frames.shape[0] > 0

    report_p = Path("stage8_composer_v4_report.md")
    require_local_artifact(report_p)
    report_text = report_p.read_text(encoding="utf-8")
    assert "ETAP 8: Raport Porównawczy Composer v3" in report_text
    assert "Główna Tabela Porównawcza v3 vs v4" in report_text
    assert "Aktywność Kanałów w Poszczególnych Sekcjach" in report_text


def test_api_generate_music_all_profiles():
    """Test 1: All 6 canonical profiles successfully generate a valid MusicGenerationResult."""
    from atari_music.api import MusicGenerationResult, generate_music

    profiles = ["title", "exploration", "action", "funny", "dungeon", "ending"]
    for prof in profiles:
        res = generate_music(profile=prof, seed=42)
        assert isinstance(res, MusicGenerationResult)
        assert res.metadata.profile == prof
        assert res.metadata.channels_used == 4
        assert res.metadata.memory_size_bytes <= 2048
        assert len(res.pokey_ir.sequence) > 0


def test_api_determinism():
    """Test 2: Identical profile + seed + parameters must yield identical results."""
    from atari_music.api import generate_music

    res1 = generate_music(profile="action", seed=1234, key="D", tempo=165, variation=0.6)
    res2 = generate_music(profile="action", seed=1234, key="D", tempo=165, variation=0.6)

    assert res1.metadata.tempo == res2.metadata.tempo
    assert res1.metadata.memory_size_bytes == res2.metadata.memory_size_bytes
    assert res1.metadata.key == res2.metadata.key
    assert res1.pokey_ir.sequence == res2.pokey_ir.sequence
    assert len(res1.pokey_ir.patterns) == len(res2.pokey_ir.patterns)


def test_api_seed_variation():
    """Test 3: Different seeds within the same profile produce different musical variations."""
    from atari_music.api import generate_music

    res_a = generate_music(profile="dungeon", seed=100)
    res_b = generate_music(profile="dungeon", seed=200)

    # Patterns or melodic pitches or sequences should differ
    notes_a = [n.pitch for n in res_a.pokey_ir.patterns[0].tracks[3] if n.pitch]
    notes_b = [n.pitch for n in res_b.pokey_ir.patterns[0].tracks[3] if n.pitch]
    assert notes_a != notes_b or res_a.pokey_ir.sequence != res_b.pokey_ir.sequence


def test_api_parameter_validation():
    """Test 4: Strict validation rejects invalid profiles, seeds, keys, tempos, lengths, and ranges."""
    import pytest
    from atari_music.api import generate_music

    # Invalid profile
    with pytest.raises(ValueError, match="Unknown music profile"):
        generate_music(profile="synthwave")

    # Invalid seed (non-int)
    with pytest.raises(ValueError, match="Seed must be an integer"):
        generate_music(seed="42")  # type: ignore

    with pytest.raises(ValueError, match="Seed must be an integer"):
        generate_music(seed=True)  # type: ignore

    # Invalid key
    with pytest.raises(ValueError, match="Invalid musical key"):
        generate_music(key="H")

    # Invalid tempo
    with pytest.raises(ValueError, match="outside allowable POKEY musical bounds"):
        generate_music(tempo=30)

    with pytest.raises(ValueError, match="outside allowable POKEY musical bounds"):
        generate_music(tempo=300)

    # Invalid length
    with pytest.raises(ValueError, match="Invalid length"):
        generate_music(length="epic")

    # Invalid intensity range
    with pytest.raises(ValueError, match="outside valid range"):
        generate_music(intensity=1.5)

    with pytest.raises(ValueError, match="outside valid range"):
        generate_music(intensity=-0.1)

    # Invalid variation range
    with pytest.raises(ValueError, match="outside valid range"):
        generate_music(variation=1.2)


def test_api_profile_separation():
    """Test 5: Preserves categorical separation between high-energy and atmospheric profiles."""
    from atari_music.api import generate_music

    action_song = generate_music(profile="action", seed=555)
    dungeon_song = generate_music(profile="dungeon", seed=555)

    assert action_song.metadata.tempo >= 155
    assert dungeon_song.metadata.tempo <= 90
    assert action_song.metadata.tempo - dungeon_song.metadata.tempo >= 65


def test_api_memory_and_channels_guarantee():
    """Test 6 & 7: Guarantees <= 2048 B memory footprint and 4-channel polyphony across variations."""
    from atari_music.api import generate_music

    for p in ["title", "exploration", "action", "funny", "dungeon", "ending"]:
        res = generate_music(profile=p, seed=888, length="long", variation=0.9)
        assert res.metadata.memory_size_bytes <= 2048
        assert res.metadata.channels_used == 4


def test_mads_exporter_syntax_and_structure():
    """Etap 10: Verify MADS Exporter generates valid MADS syntax with song headers and 4 channels."""
    from atari_music.api import generate_music
    from atari_music.mads_exporter import export_mads_asm

    res = generate_music(profile="action", seed=42)
    asm_text = export_mads_asm(res)

    assert "song_data:" in asm_text
    assert "song_data_instruments:" in asm_text
    assert "song_data_sequence:" in asm_text
    assert "song_data_pat_0_tracks:" in asm_text
    assert ".word song_data_pat_0_ch1" in asm_text
    assert ".word song_data_pat_0_ch4" in asm_text
    assert ".word $ffff" in asm_text
    assert ".byte $ff" in asm_text  # End of track marker


def test_mads_end_to_end_compilation_and_relocation():
    """Etap 10: End-to-end compilation with MADS to Atari XEX under multiple base addresses."""
    import subprocess
    from atari_music.api import generate_music
    from atari_music.mads_exporter import export_mads_asm

    mads_exe = Path("tools/mads/mads.exe")
    require_local_artifact(mads_exe)

    # 1. Generate song via API
    res = generate_music(profile="action", seed=301)
    test_asm = Path("experiments/test_e2e_data.asm")
    export_mads_asm(res, test_asm)

    # 2. Test compilation under $6000, $7000, $8000, $A000
    addresses = ["$6000", "$7000", "$8000", "$A000"]
    for addr in addresses:
        harness = f"""
    org {addr}
main:
    ldx #<song_data
    ldy #>song_data
    jsr music_init
    jsr music_play
    jsr music_update
    jsr music_stop
    rts

    icl '../player.asm'
    icl '{test_asm.name}'

    run main
"""
        harness_p = Path(f"experiments/harness_{addr[1:]}.asm")
        harness_p.write_text(harness, encoding="utf-8")
        xex_p = Path(f"experiments/harness_{addr[1:]}.xex")

        comp = subprocess.run([str(mads_exe), str(harness_p), f"-o:{xex_p}"], capture_output=True, text=True)
        assert comp.returncode == 0, f"MADS failed at {addr}: {comp.stderr or comp.stdout}"
        assert xex_p.exists()
        assert xex_p.stat().st_size > 0


def test_mads_compilation_all_6_profiles():
    """Etap 10: Verify all 6 canonical profiles successfully compile with player to valid Atari XEX."""
    import subprocess
    from atari_music.api import generate_music
    from atari_music.mads_exporter import export_mads_asm

    mads_exe = Path("tools/mads/mads.exe")
    require_local_artifact(mads_exe)
    profiles = ["title", "exploration", "action", "funny", "dungeon", "ending"]

    for p in profiles:
        res = generate_music(profile=p, seed=123)
        data_p = Path(f"experiments/{p}_e2e_data.asm")
        export_mads_asm(res, data_p)

        src = f"""
    org $7000
entry:
    ldx #<song_data
    ldy #>song_data
    jsr music_init
    jsr music_play
    jsr music_update
    rts

    icl '../player.asm'
    icl '{data_p.name}'

    run entry
"""
        src_p = Path(f"experiments/{p}_e2e_run.asm")
        src_p.write_text(src, encoding="utf-8")
        xex_p = Path(f"experiments/{p}_e2e.xex")

        res_comp = subprocess.run([str(mads_exe), str(src_p), f"-o:{xex_p}"], capture_output=True, text=True)
        assert res_comp.returncode == 0, f"MADS build failed for profile {p}: {res_comp.stderr or res_comp.stdout}"
        assert xex_p.exists()
        assert xex_p.stat().st_size <= 2048, f"XEX for {p} too large: {xex_p.stat().st_size} bytes"


def test_stage11_standalone_xex_build_and_headers():
    """Etap 11: Verify all 6 standalone XEX files in stage11_xex are built with valid DOS headers."""
    import sys
    root = Path(__file__).resolve().parent.parent
    require_local_artifact(root / "stage11_xex")
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    from scripts.verify_stage11_runtime import verify_xex_binaries
    results = verify_xex_binaries()
    assert len(results) == 6
    for prof, size, magic in results:
        assert magic is True, f"XEX header magic failed for {prof}"
        assert 1000 <= size <= 2048, f"XEX size out of bounds for {prof}: {size} bytes"


def test_stage11_zero_page_relocation_and_dungeon_16bit():
    """Etap 11: Verify Zero Page reconfigurability, Dungeon 16-bit bass audit, and API call sequences."""
    import sys
    root = Path(__file__).resolve().parent.parent
    require_local_artifact(root / "tools" / "mads" / "mads.exe")
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    from scripts.verify_stage11_runtime import (
        verify_dungeon_16bit_bass,
        verify_player_api_scenarios,
        verify_zero_page,
    )
    zp_res = verify_zero_page()
    for name, ok in zp_res.items():
        assert ok is True, f"Zero Page verification failed for {name}"

    dungeon_res = verify_dungeon_16bit_bass()
    for check, ok in dungeon_res.items():
        assert ok is True, f"Dungeon 16-bit check failed for {check}"

    api_res = verify_player_api_scenarios()
    for scen, ok in api_res.items():
        assert ok is True, f"API scenario check failed for {scen}"


def test_pokey_noise_audf_frequency_response():
    """Verify DISTORTION_WHITE_NOISE ($E0) frequency and transition rate scale with AUDF."""
    import numpy as np
    from atari_music.constants import DISTORTION_WHITE_NOISE
    from atari_music.pokey_synth import render_pokey_samples

    # 1. Low frequency noise (AUDF=254, like bass drum / A2 note)
    frames_low = np.zeros((50, 9), dtype=np.uint8)
    frames_low[:, 0] = 254  # AUDF1
    frames_low[:, 1] = DISTORTION_WHITE_NOISE | 0x0F  # AUDC1: full volume

    # 2. High frequency noise (AUDF=5, like hi-hat / cymbal)
    frames_high = np.zeros((50, 9), dtype=np.uint8)
    frames_high[:, 0] = 5    # AUDF1
    frames_high[:, 1] = DISTORTION_WHITE_NOISE | 0x0F  # AUDC1: full volume

    samples_low = render_pokey_samples(frames_low, sample_rate=44100, frame_rate_hz=50.0)
    samples_high = render_pokey_samples(frames_high, sample_rate=44100, frame_rate_hz=50.0)

    # Count zero crossings
    zc_low = np.sum(np.diff(np.sign(samples_low) >= 0) != 0)
    zc_high = np.sum(np.diff(np.sign(samples_high) >= 0) != 0)

    # High frequency noise must have drastically more zero crossings than low frequency noise
    assert zc_high > zc_low * 5
    # Low frequency noise (250 Hz divider) in 1 second should have roughly ~200-500 crossings, not ~20000
    assert zc_low < 1500


def test_pokey_noise_determinism():
    """Verify POKEY noise synthesis produces bit-for-bit identical output for identical inputs."""
    import numpy as np
    from atari_music.constants import DISTORTION_WHITE_NOISE
    from atari_music.pokey_synth import render_pokey_samples

    frames = np.zeros((25, 9), dtype=np.uint8)
    frames[:, 4] = 80   # Ch 3 AUDF
    frames[:, 5] = DISTORTION_WHITE_NOISE | 0x0C

    samples1 = render_pokey_samples(frames)
    samples2 = render_pokey_samples(frames)

    assert np.array_equal(samples1, samples2)


def test_pokey_noise_9bit_vs_17bit():
    """Verify AUDCTL_9BIT_POLY flag produces distinct noise texture from default 17-bit."""
    import numpy as np
    from atari_music.constants import AUDCTL_9BIT_POLY, DISTORTION_WHITE_NOISE
    from atari_music.pokey_synth import render_pokey_samples

    frames_17 = np.zeros((20, 9), dtype=np.uint8)
    frames_17[:, 0] = 40
    frames_17[:, 1] = DISTORTION_WHITE_NOISE | 0x0F
    frames_17[:, 8] = 0x00

    frames_9 = np.copy(frames_17)
    frames_9[:, 8] = AUDCTL_9BIT_POLY

    samples_17 = render_pokey_samples(frames_17)
    samples_9 = render_pokey_samples(frames_9)

    assert not np.array_equal(samples_17, samples_9)


def test_game_over_percussion_rendering(tmp_path):
    """Verify Game Over composition percussion event (A2 Comic Thud) generates proper punchy WAV."""
    from pathlib import Path
    import numpy as np
    import wave
    from atari_music.ai.schema import AICompositionDoc
    from atari_music.ai.client import generate_music_from_composition
    from atari_music.pokey_synth import render_pokey_to_wav

    doc_dict = {
        "format": "atari-music-composition",
        "version": 1,
        "metadata": {
            "title": "Game Over",
            "author": "Composer AI",
            "key": "A",
            "mode": "minor",
            "bpm": 120,
            "duration_seconds": 2.0,
        },
        "hardware": {
            "channels": 4,
            "use_16bit_bass": False,
        },
        "instruments": [
            {"id": "lead", "name": "Lead", "character": "bright_lead"},
            {"id": "bass", "name": "Bass", "character": "bass"},
            {"id": "perc", "name": "Comic Thud", "character": "percussion"},
        ],
        "patterns": [
            {
                "id": "P1",
                "length_steps": 16,
                "channels": {
                    "1": [{"step": 0, "note": "A4", "instrument": "lead", "duration": 4, "volume": 12}],
                    "2": [{"step": 0, "note": "A2", "instrument": "bass", "duration": 8, "volume": 10}],
                    "3": [
                        {"step": 0, "note": "A2", "instrument": "perc", "duration": 2, "volume": 10},
                        {"step": 8, "note": "A2", "instrument": "perc", "duration": 2, "volume": 9},
                    ],
                    "4": [],
                },
            }
        ],
        "sequence": ["P1"],
        "loop_point": 0,
    }

    doc = AICompositionDoc.model_validate(doc_dict)
    res = generate_music_from_composition(doc)
    assert res.pokey_ir is not None

    wav_path = tmp_path / "game_over.wav"
    res.render_wav(wav_path)
    assert wav_path.exists()
    assert wav_path.stat().st_size > 0

    with wave.open(str(wav_path), "rb") as wf:
        assert wf.getframerate() == 44100
        n_frames = wf.getnframes()
        assert n_frames > 0
        raw_bytes = wf.readframes(n_frames)
        samples = np.frombuffer(raw_bytes, dtype=np.int16)
        # Check non-silent output and no overflow
        assert np.max(np.abs(samples)) > 1000















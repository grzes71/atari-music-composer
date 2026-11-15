"""Stage 10A: the evidence-based rebinding experiment.

These tests lock the *experiment*, not the numbers: that the six songs are the Stage 9C six and not
a guess, that the old assignment reproduces the one the listener heard, that the new one is legal
and justified by the listener's own ratings, that the compositions and the Stage 9C package cannot be
touched, and that the blinded programme is deterministic and does not give itself away.

The end-to-end fixture needs the Stage 9C listening package (gitignored, built by Stage 9C) and the
Stage 9D analysis, so it skips where the experiment has not been run.
"""

from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path
from typing import Any, Dict, List, Sequence, Tuple
import wave

import numpy as np
import pytest
from click.testing import CliRunner

from atari_music import stage10a
from atari_music.ai.client import generate_music_from_composition
from atari_music.cli import cli
from atari_music.sound_profiles import apply_profile_binding, load_profile_binding, load_sound_profile_bank

REPO_ROOT = Path(__file__).resolve().parents[1]
BANK_DIR = REPO_ROOT / "tests" / "data" / "sound_profiles" / "bank"
STAGE9C_PACKAGE = REPO_ROOT / "examples" / "sound_profile_listening"
PACKAGE_NAME = "sound_profile_rebinding_10a"
SONGS_DIR = REPO_ROOT / "examples" / "songs"
STAGE9D_REPORTS = REPO_ROOT / "reports" / "stage9d"


def _require_inputs() -> None:
    if not (STAGE9C_PACKAGE / "manifest.json").is_file():
        pytest.skip("the Stage 9C listening package is not present in this checkout")
    if not (STAGE9D_REPORTS / "profile_scores.json").is_file():
        pytest.skip("the Stage 9D analysis is not present in this checkout")


def _dir_digest(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        digest.update(str(path.relative_to(root)).encode("utf-8"))
        digest.update(path.read_bytes())
    return digest.hexdigest()


def _flat(text: str) -> str:
    """Text with its line wrapping removed, so a phrase can be looked for across a line break."""
    return " ".join(text.split())


def _evidence(
    profile_id: str = "pokey_ref_test",
    *,
    usefulness: float = 3.0,
    distinctiveness: float = 3.0,
    character: float = 3.0,
    tags: Sequence[str] = (stage10a.TAG_TONAL,),
    audio_group: Any = None,
) -> stage10a.Evidence:
    """One synthetic evidence row, for the rule unit tests. Nothing here reaches the real data."""
    return stage10a.Evidence(
        profile_id=profile_id,
        sample_id="sample_999",
        status="PLAYABLE",
        scope="VOICE",
        generator_family="$A",
        audctl_mode="$00",
        audio_group=audio_group,
        usefulness=usefulness,
        distinctiveness=distinctiveness,
        character=character,
        confidence=4.0,
        comment="synthetic",
        tags=tuple(tags),
        candidate_class="shortlist",
        blocking_codes=(),
        used_in_song_trial=None,
    )


@pytest.fixture(scope="module")
def build(tmp_path_factory: pytest.TempPathFactory) -> Dict[str, Any]:
    """One complete preparation, shared by every test.

    The digests of everything the stage calls read-only are captured here, immediately before the
    build, so the immutability assertions are made against the state the build actually saw.
    """
    _require_inputs()
    package = tmp_path_factory.mktemp("stage10a-package") / PACKAGE_NAME
    reports = tmp_path_factory.mktemp("stage10a-reports")
    docs = tmp_path_factory.mktemp("stage10a-docs")
    watched = {
        "bank": _dir_digest(BANK_DIR),
        "stage9c": _dir_digest(STAGE9C_PACKAGE),
        "songs": _dir_digest(SONGS_DIR),
    }
    bundle = stage10a.build_package(
        package,
        stage9c_package=STAGE9C_PACKAGE,
        songs_dir=SONGS_DIR,
        bank_dir=BANK_DIR,
        reports_dir=STAGE9D_REPORTS,
        analysis_dir=reports,
        docs_dir=docs,
    )
    return {
        "bundle": bundle,
        "package": package,
        "reports": reports,
        "docs": docs,
        "watched": watched,
        "report_text": (docs / "stage10a_rebinding_experiment.md").read_text(encoding="utf-8"),
    }


# ---------------------------------------------------------------------------
# 1. The six songs, exactly
# ---------------------------------------------------------------------------
class TestTheSixSongs:
    def test_they_are_the_stage9c_six(self, build: Dict[str, Any]) -> None:
        manifest = json.loads((STAGE9C_PACKAGE / "manifest.json").read_text(encoding="utf-8"))
        expected = [(entry["trial_id"], entry["song"]) for entry in manifest["song_trials"]]
        got = [(song.trial_id, song.song) for song in build["bundle"]["songs"]]
        assert got == expected
        assert [trial_id for trial_id, _ in got] == [f"song_{n:02d}" for n in range(1, 7)]

    def test_each_song_carries_its_old_binding_and_profiles(self, build: Dict[str, Any]) -> None:
        manifest = json.loads((STAGE9C_PACKAGE / "manifest.json").read_text(encoding="utf-8"))
        for entry, song in zip(manifest["song_trials"], build["bundle"]["songs"]):
            assert song.old_profiles == entry["bound_profiles"]
            assert song.old_binding_path.name == entry["binding"]
            assert song.song_path.is_file()

    def test_the_compositions_are_parsed_from_their_real_documents(self, build: Dict[str, Any]) -> None:
        for song in build["bundle"]["songs"]:
            assert song.song_path.suffix in (".dsl", ".json")
            document = stage10a.load_song(song.song_path)
            assert document.instruments, song.song
            for key in song.old_profiles:
                assert any(
                    str(inst.id) == key or str(inst.name) == key for inst in document.instruments
                ), f"{song.song} binds {key!r}, which the composition does not declare"

    def test_a_missing_package_is_refused(self, tmp_path: Path) -> None:
        with pytest.raises(stage10a.Stage10AError, match="Stage 9C package is not present"):
            stage10a.recover_songs(tmp_path, SONGS_DIR)

    def test_an_edited_old_binding_is_refused(self, tmp_path: Path) -> None:
        """A binding edited since the experiment would silently change what 'old' means."""
        package = tmp_path / "package"
        package.mkdir()
        manifest = json.loads((STAGE9C_PACKAGE / "manifest.json").read_text(encoding="utf-8"))
        (package / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        songs = tmp_path / "songs"
        songs.mkdir()
        for entry in manifest["song_trials"]:
            shutil.copy(SONGS_DIR / entry["song"], songs / entry["song"])
            shutil.copy(SONGS_DIR / entry["binding"], songs / entry["binding"])
        victim = songs / manifest["song_trials"][0]["binding"]
        document = json.loads(victim.read_text(encoding="utf-8"))
        first_key = sorted(document["instruments"])[0]
        document["instruments"][first_key] = "pokey_ref_ffffffff"
        victim.write_text(json.dumps(document), encoding="utf-8")

        with pytest.raises(stage10a.Stage10AError, match="no longer matches the Stage 9C manifest"):
            stage10a.recover_songs(package, songs)


# ---------------------------------------------------------------------------
# 2. The plan: one decision per channel, nothing traded
# ---------------------------------------------------------------------------
class TestThePlan:
    def test_every_bound_instrument_is_decided_exactly_once(self, build: Dict[str, Any]) -> None:
        for song in build["bundle"]["songs"]:
            decided = [
                key
                for decision in build["bundle"]["plan"].decisions
                if decision.trial_id == song.trial_id
                for key in decision.keys
            ]
            assert sorted(decided) == sorted(song.old_profiles), song.song

    def test_a_channel_carries_one_profile(self, build: Dict[str, Any]) -> None:
        plan = build["bundle"]["plan"]
        for decision in plan.decisions:
            song = next(item for item in build["bundle"]["songs"] if item.trial_id == decision.trial_id)
            binding = plan.binding_for(song)
            assert len({binding[key] for key in decision.keys}) == 1
            assert binding[decision.keys[0]] == decision.new_profile

    def test_every_new_binding_applies(self, build: Dict[str, Any]) -> None:
        bank = load_sound_profile_bank(BANK_DIR)
        for song in build["bundle"]["songs"]:
            document = stage10a.load_song(song.song_path)
            result = generate_music_from_composition(document)
            applies, code = stage10a.try_binding(
                result, document, bank, build["bundle"]["plan"].binding_for(song)
            )
            assert applies, f"{song.song}: {code}"

    def test_every_new_profile_is_renderable_and_unblocked(self, build: Dict[str, Any]) -> None:
        bank = load_sound_profile_bank(BANK_DIR)
        evidence = stage10a.load_human_evidence(STAGE9D_REPORTS)
        for decision in build["bundle"]["plan"].changed:
            profile = bank.get(decision.new_profile)
            assert profile.renderable, decision.new_profile
            assert not evidence[decision.new_profile].blocking_codes, decision.new_profile

    def test_no_replacement_is_worse_on_any_listener_rating(self, build: Dict[str, Any]) -> None:
        for decision in build["bundle"]["plan"].changed:
            old = decision.human_evidence["old"]
            new = decision.human_evidence["new"]
            for scale in ("usefulness", "distinctiveness", "atari_character"):
                assert new[scale] >= old[scale], f"{decision.song} {scale}"
            assert new["atari_character"] >= stage10a.CHARACTER_FLOOR

    def test_no_replacement_merely_duplicates_the_old_sound(self, build: Dict[str, Any]) -> None:
        evidence = stage10a.load_human_evidence(STAGE9D_REPORTS)
        for decision in build["bundle"]["plan"].changed:
            old = evidence[decision.old_profile]
            new = evidence[decision.new_profile]
            assert stage10a.audio_key(old) != stage10a.audio_key(new)

    def test_the_scope_is_preserved(self, build: Dict[str, Any]) -> None:
        """Swapping VOICE for PAIR would change AUDCTL, which is not this experiment."""
        evidence = stage10a.load_human_evidence(STAGE9D_REPORTS)
        for decision in build["bundle"]["plan"].changed:
            assert evidence[decision.new_profile].scope == evidence[decision.old_profile].scope

    def test_a_kept_channel_has_no_eligible_replacement(self, build: Dict[str, Any]) -> None:
        for decision in build["bundle"]["plan"].decisions:
            if decision.changed:
                continue
            eligible = [item for item in decision.candidates if item.applies and item.rule]
            assert not eligible, decision.song

    def test_each_changed_decision_records_its_evidence(self, build: Dict[str, Any]) -> None:
        for decision in build["bundle"]["plan"].changed:
            assert decision.reason
            assert decision.rule in (stage10a.RULE_MARGIN, stage10a.RULE_CONSISTENT)
            assert set(decision.human_evidence) >= {"old", "new", "rule"}
            for key in ("scope", "generator_family", "audctl_mode", "status", "channel"):
                assert key in decision.technical
            assert decision.technical["pool"]

    def test_no_two_channels_of_a_song_share_a_sound(self, build: Dict[str, Any]) -> None:
        """Two channels with the same profile would spend a channel on a timbre already there."""
        evidence = stage10a.load_human_evidence(STAGE9D_REPORTS)
        for song in build["bundle"]["songs"]:
            keys = [
                stage10a.audio_key(evidence[decision.new_profile])
                for decision in build["bundle"]["plan"].decisions
                if decision.trial_id == song.trial_id
            ]
            assert len(set(keys)) == len(keys), song.song

    def test_the_plan_is_reproducible(self, build: Dict[str, Any]) -> None:
        bank = load_sound_profile_bank(BANK_DIR)
        evidence = stage10a.load_human_evidence(STAGE9D_REPORTS)
        first, _ = stage10a.build_plan(build["bundle"]["songs"], bank, evidence)
        second, _ = stage10a.build_plan(build["bundle"]["songs"], bank, evidence)
        assert first.as_dict() == second.as_dict()

    def test_the_changed_count_is_within_the_briefs_bound(self, build: Dict[str, Any]) -> None:
        """The brief allows one to three changes per song, and leaves a song alone when unsure."""
        plan = build["bundle"]["plan"]
        per_song = {}
        for decision in plan.changed:
            per_song[decision.song] = per_song.get(decision.song, 0) + 1
        assert per_song, "the experiment would be vacuous with no change at all"
        assert all(count <= 3 for count in per_song.values()), per_song

    def test_dziki2_is_left_unchanged_and_the_reason_is_recorded(self, build: Dict[str, Any]) -> None:
        """Its channel 4 carries a bell, a counter *and* a drum, so no one profile can serve it."""
        assert "dziki2.json" in build["bundle"]["plan"].as_dict()["songs_unchanged"]
        for decision in build["bundle"]["plan"].decisions:
            if decision.song != "dziki2.json":
                continue
            assert not decision.changed
            assert "keeps the sound Stage 9C already bound" in decision.reason
        mixed = next(
            decision
            for decision in build["bundle"]["plan"].decisions
            if decision.song == "dziki2.json" and decision.channel == 4
        )
        assert set(mixed.keys) == {"bell", "counter", "drum"}


# ---------------------------------------------------------------------------
# 3. The decision rule itself
# ---------------------------------------------------------------------------
class TestTheDecisionRule:
    def test_an_identical_rating_profile_is_not_adopted(self) -> None:
        rule, reason = stage10a.replacement_rule(_evidence(), _evidence("pokey_ref_other"))
        assert rule == ""
        assert "identically" in reason

    def test_a_single_one_point_gain_is_not_enough(self) -> None:
        rule, reason = stage10a.replacement_rule(
            _evidence(usefulness=3.0), _evidence("pokey_ref_other", usefulness=4.0)
        )
        assert rule == ""
        assert "single one-point difference" in reason

    def test_a_two_point_gain_on_one_rating_is_enough(self) -> None:
        rule, _ = stage10a.replacement_rule(
            _evidence(usefulness=2.0), _evidence("pokey_ref_other", usefulness=4.0)
        )
        assert rule == stage10a.RULE_MARGIN

    def test_a_one_point_gain_on_two_ratings_is_enough(self) -> None:
        rule, _ = stage10a.replacement_rule(
            _evidence(usefulness=3.0, character=3.0),
            _evidence("pokey_ref_other", usefulness=4.0, character=4.0),
        )
        assert rule == stage10a.RULE_CONSISTENT

    def test_regression_on_character_blocks_the_replacement(self) -> None:
        """The listener's distinctiveness and character oppose each other; no trade is allowed."""
        rule, reason = stage10a.replacement_rule(
            _evidence(distinctiveness=1.0, character=5.0),
            _evidence("pokey_ref_other", distinctiveness=4.0, character=4.0),
        )
        assert rule == ""
        assert "rated lower" in reason and "oppose" in reason

    def test_a_profile_heard_as_not_atari_like_cannot_be_the_improvement(self) -> None:
        rule, reason = stage10a.replacement_rule(
            _evidence(usefulness=2.0, distinctiveness=3.0),
            _evidence("pokey_ref_other", usefulness=4.0, distinctiveness=5.0, character=2.0),
        )
        assert rule == ""
        assert "floor" in reason

    def test_an_unrated_profile_carries_no_evidence(self) -> None:
        unrated = _evidence("pokey_ref_other", usefulness=None, distinctiveness=None, character=None)
        rule, reason = stage10a.replacement_rule(_evidence(), unrated)
        assert rule == "" and "did not rate" in reason

    def test_a_sound_identical_to_the_old_one_is_not_a_candidate(self) -> None:
        assert not stage10a._audio_distinct(_evidence(audio_group=4), _evidence("x", audio_group=4))
        assert stage10a._audio_distinct(_evidence(audio_group=4), _evidence("x", audio_group=5))
        assert stage10a._audio_distinct(_evidence(), _evidence("x", audio_group=5))


# ---------------------------------------------------------------------------
# 4. The package
# ---------------------------------------------------------------------------
class TestTheFrameColumns:
    """The row layout is a fact about the renderer, so it is pinned against the renderer.

    Stage 10A originally named the columns as if the row were ``AUDF1..AUDF4`` followed by
    ``AUDC1..AUDC4``. It is not: ``_render_note_to_frames`` interleaves them
    (``AUDF1, AUDC1, AUDF2, AUDC2, …``), so every name after the first was wrong and the published
    tables mislabelled which register had changed. These tests derive the layout from a render.
    """

    def test_the_names_are_the_row_layout(self) -> None:
        from atari_music.ir import FRAME_COLUMN_NAMES, audc_column, audf_column

        assert FRAME_COLUMN_NAMES[8] == "AUDCTL"
        for channel in range(1, 5):
            assert FRAME_COLUMN_NAMES[audf_column(channel)] == f"AUDF{channel}"
            assert FRAME_COLUMN_NAMES[audc_column(channel)] == f"AUDC{channel}"

    def test_a_one_voice_stimulus_only_ever_changes_channel_ones_columns(self) -> None:
        from atari_music.ir import FRAME_COLUMN_NAMES, compile_ir_to_pokey_frames
        from atari_music.sound_profiles.bank import load_sound_profile_bank
        from atari_music.stage9c import stimulus_composition

        bank = load_sound_profile_bank(BANK_DIR)
        document = stimulus_composition(joined_pair=False)
        before = compile_ir_to_pokey_frames(
            generate_music_from_composition(document).pokey_ir
        )
        default_audc = int(before[0, 1]) >> 4

        profile = next(
            item
            for item in bank.renderable()
            if item.scope == "VOICE" and item.distortion_nibble not in (None, default_audc)
        )
        after = compile_ir_to_pokey_frames(
            apply_profile_binding(
                generate_music_from_composition(document),
                load_profile_binding(
                    {
                        "schema": "atari-music/sound-profile-binding/1",
                        "instruments": {"stim": profile.profile_id},
                    }
                ),
                bank,
                composition=document,
            ).pokey_ir
        )
        changed = {
            FRAME_COLUMN_NAMES[index]
            for index in np.nonzero((before != after).any(axis=0))[0]
        }
        # Only the channel the stimulus sounds on, plus the clock, may differ.
        assert changed, "the chosen profile changed nothing, so this test proves nothing"
        assert changed <= {"AUDF1", "AUDC1", "AUDCTL"}, changed


class TestThePackage:
    def test_every_song_gets_three_versions(self, build: Dict[str, Any]) -> None:
        audio = build["package"] / "audio"
        for song in build["bundle"]["songs"]:
            for kind in ("default", "old", "new"):
                assert (audio / f"{song.trial_id}_{kind}.wav").is_file(), (song.song, kind)

    def test_every_version_is_mono_16_bit_pcm(self, build: Dict[str, Any]) -> None:
        audio = build["package"] / "audio"
        for song in build["bundle"]["songs"]:
            lengths = set()
            for kind in ("default", "old", "new"):
                with wave.open(str(audio / f"{song.trial_id}_{kind}.wav"), "rb") as handle:
                    assert handle.getnchannels() == 1
                    assert handle.getsampwidth() == 2
                    assert handle.getframerate() == stage10a.SAMPLE_RATE
                    lengths.add(handle.getnframes())
            # Only the profile changed, so the composition's timing is identical in all three.
            assert len(lengths) == 1, song.song

    def test_the_bound_versions_change_no_note(self, build: Dict[str, Any]) -> None:
        """The brief's §10: same notes, durations, velocities, channels and arrangement."""
        bank = load_sound_profile_bank(BANK_DIR)
        for song in build["bundle"]["songs"]:
            document = stage10a.load_song(song.song_path)
            default = generate_music_from_composition(document)
            new = generate_music_from_composition(document)
            new = apply_profile_binding(
                new,
                load_profile_binding(
                    {
                        "schema": "atari-music/sound-profile-binding/1",
                        "instruments": build["bundle"]["plan"].binding_for(song),
                    }
                ),
                bank,
                composition=document,
            )
            assert _notes(default.pokey_ir) == _notes(new.pokey_ir), song.song

    def test_the_three_versions_are_audibly_different_where_the_profile_changed(
        self, build: Dict[str, Any]
    ) -> None:
        comparison = build["bundle"]["comparison"]
        for song in build["bundle"]["songs"]:
            changed = any(
                decision.changed
                for decision in build["bundle"]["plan"].decisions
                if decision.trial_id == song.trial_id
            )
            block = comparison[song.trial_id]["old_vs_new"]
            assert block["audio_identical"] is (not changed), song.song

    def test_the_blinded_pairs_are_the_versions_they_claim(self, build: Dict[str, Any]) -> None:
        audio = build["package"] / "audio"
        for trial in build["bundle"]["trials"]:
            for side, kind in trial.sides.items():
                copied = (audio / f"{trial.trial_id}_{side}.wav").read_bytes()
                source = (audio / f"{trial.song_trial_id}_{kind}.wav").read_bytes()
                assert copied == source, (trial.trial_id, side)

    def test_the_programme_is_three_kinds_per_song(self, build: Dict[str, Any]) -> None:
        trials = build["bundle"]["trials"]
        assert len(trials) == 3 * len(build["bundle"]["songs"])
        for song in build["bundle"]["songs"]:
            kinds = [trial.trial_kind for trial in trials if trial.song_trial_id == song.trial_id]
            assert sorted(kinds) == sorted(kind for kind, _, _ in stage10a.TRIAL_KINDS)
            assert all(trial.song == song.song for trial in trials if trial.song_trial_id == song.trial_id)

    def test_the_orientation_is_deterministic_and_seed_dependent(self) -> None:
        songs, _ = stage10a.recover_songs(STAGE9C_PACKAGE, SONGS_DIR)
        first = [trial.as_dict() for trial in stage10a.build_trials(songs, __import__("random").Random(7))]
        again = [trial.as_dict() for trial in stage10a.build_trials(songs, __import__("random").Random(7))]
        other = [trial.as_dict() for trial in stage10a.build_trials(songs, __import__("random").Random(8))]
        assert first == again
        assert first != other

    def test_every_trial_pairs_two_different_versions(self, build: Dict[str, Any]) -> None:
        for trial in build["bundle"]["trials"]:
            assert trial.a != trial.b
            assert {trial.a, trial.b} == set(trial.compared.values())

    def test_the_answer_template_is_empty_with_one_row_per_trial(self, build: Dict[str, Any]) -> None:
        rows = [
            line
            for line in (build["package"] / "evaluation_rebinding_10a.csv")
            .read_text(encoding="utf-8")
            .splitlines()
            if line.strip()
        ]
        assert rows[0].split(",") == list(stage10a.ANSWER_HEADER)
        assert len(rows) == len(build["bundle"]["trials"]) + 1
        assert all(
            row.split(",")[1:] == [""] * (len(stage10a.ANSWER_HEADER) - 1) for row in rows[1:]
        )

    def test_the_interface_gives_nothing_away(self, build: Dict[str, Any]) -> None:
        html = (build["package"] / "index.html").read_text(encoding="utf-8")
        forbidden = [
            "pokey_ref_",
            "binding.json",
            "default_vs_new",
            "old_vs_new",
            "default_vs_old",
            "generator",
            "AUDCTL",
            "spectral",
            "manifest.json",
            "profile",
        ]
        for token in forbidden:
            assert token not in html, token
        for trial in build["bundle"]["trials"]:
            assert trial.side_file("a") in html
        assert "No clear difference" in html

    def test_the_package_never_touches_the_stage9c_package(self, build: Dict[str, Any]) -> None:
        package = build["package"]
        assert package.name == PACKAGE_NAME
        assert package.resolve() != STAGE9C_PACKAGE.resolve()
        for entry in STAGE9C_PACKAGE.iterdir():
            assert entry.name not in {"bindings", "evaluation_rebinding_10a.csv"}

    def test_the_readme_says_what_is_asked(self, build: Dict[str, Any]) -> None:
        text = _flat((build["package"] / "README.md").read_text(encoding="utf-8")).lower()
        for phrase in (
            "better overall",
            "more convincing as atari music",
            "sound character",
            "do not open it while listening",
        ):
            assert phrase in text, phrase


# ---------------------------------------------------------------------------
# 5. Reproducibility and immutability
# ---------------------------------------------------------------------------
class TestNothingChanges:
    def test_the_stage9c_package_is_untouched(self, build: Dict[str, Any]) -> None:
        assert _dir_digest(STAGE9C_PACKAGE) == build["watched"]["stage9c"]
        verification = build["bundle"]["verification"]
        assert verification["stage9c_package_unchanged"] is True

    def test_the_compositions_and_old_bindings_are_untouched(self, build: Dict[str, Any]) -> None:
        assert _dir_digest(SONGS_DIR) == build["watched"]["songs"]
        verification = build["bundle"]["verification"]
        assert verification["compositions_unchanged"] is True
        assert verification["old_bindings_unchanged"] is True
        for song in build["bundle"]["songs"]:
            assert (
                stage10a.song_digest(song.song_path)
                == verification["source_hashes"]["compositions"][song.song]
            )

    def test_the_profile_bank_is_untouched(self, build: Dict[str, Any]) -> None:
        assert _dir_digest(BANK_DIR) == build["watched"]["bank"]

    def test_the_default_and_old_sides_reproduce_stage9c_byte_for_byte(
        self, build: Dict[str, Any]
    ) -> None:
        verification = build["bundle"]["verification"]
        flags = verification["stage9c_default_and_old_byte_identical"]
        assert set(flags) == {song.trial_id for song in build["bundle"]["songs"]}
        assert all(flags[trial_id]["default"] for trial_id in flags)
        assert all(flags[trial_id]["old"] for trial_id in flags)
        counts = verification["stage9c_bytes_compared"]
        assert set(counts) == set(flags)
        for trial_id, pair in counts.items():
            assert pair["default"] > 0 and pair["old"] > 0, trial_id
            assert pair["default"] == pair["old"], trial_id

    def test_the_shared_gain_matches_the_stage9c_manifest(self, build: Dict[str, Any]) -> None:
        """Same normalization, to four decimal places, as the experiment being re-tested."""
        manifest = json.loads((STAGE9C_PACKAGE / "manifest.json").read_text(encoding="utf-8"))
        for entry in manifest["song_trials"]:
            mine = build["bundle"]["comparison"][entry["trial_id"]]["shared_gain_db"]
            assert mine == pytest.approx(entry["shared_gain_db"], abs=1e-3), entry["trial_id"]

    def test_a_render_is_reproducible(self, build: Dict[str, Any]) -> None:
        """The audio on disk is a function of the inputs, not of the run."""
        bank = load_sound_profile_bank(BANK_DIR)
        song = build["bundle"]["songs"][0]
        document = stage10a.load_song(song.song_path)
        limit = int(round(stage10a.SONG_EXCERPT_SECONDS * stage10a.SAMPLE_RATE))
        recorded = build["bundle"]["comparison"][song.trial_id]
        from atari_music.ir import compile_ir_to_pokey_frames
        from atari_music.pokey_synth import render_pokey_samples

        default = stage10a.bound_result(document, None, None)
        gain = stage10a.shared_gain(
            render_pokey_samples(compile_ir_to_pokey_frames(default.pokey_ir), stage10a.SAMPLE_RATE, 50.0),
            limit,
        )
        assert round(20.0 * __import__("math").log10(gain), 4) == recorded["shared_gain_db"]
        again = stage10a.render_version(
            document,
            bank,
            build["bundle"]["plan"].binding_for(song),
            kind="new",
            gain=gain,
            limit=limit,
        )
        assert again.audio_sha256 == recorded["old_vs_new"]["sha256"]["new"]

    def test_no_clipping_was_introduced(self, build: Dict[str, Any]) -> None:
        for song in build["bundle"]["songs"]:
            clipped = build["bundle"]["comparison"][song.trial_id]["clipped_samples"]
            assert clipped["new"] == 0, song.song

    def test_the_analysis_outputs_are_written(self, build: Dict[str, Any]) -> None:
        for name in ("songs.json", "rebinding.json", "machine_comparison.json", "verification.json"):
            assert (build["reports"] / name).is_file(), name
        payload = json.loads((build["reports"] / "rebinding.json").read_text(encoding="utf-8"))
        assert payload["decisions"]
        assert payload["changed_channels"] == len(
            [decision for decision in payload["decisions"] if decision["changed"]]
        )


def _notes(song: Any) -> List[Tuple[Any, ...]]:
    """The musical content of an IRSong: everything a profile must not be able to change."""
    events: List[Tuple[Any, ...]] = []
    for pattern in song.patterns:
        for channel in sorted(pattern.tracks):
            for note in pattern.tracks[channel]:
                events.append(
                    (
                        int(channel),
                        int(note.instrument_id),
                        bool(note.is_rest),
                        getattr(note, "pitch", None),
                        getattr(note, "duration", None),
                        getattr(note, "velocity", None),
                    )
                )
    return events


# ---------------------------------------------------------------------------
# 6. The report and the command
# ---------------------------------------------------------------------------
class TestTheReport:
    def test_it_has_the_ten_sections_the_brief_asks_for(self, build: Dict[str, Any]) -> None:
        text = build["report_text"]
        for heading in (
            "## 1. Objective",
            "## 2. The six songs",
            "## 3. The old binding",
            "## 4. Candidate selection",
            "## 5. The final experimental rebinding",
            "## 6. Evidence for each changed assignment",
            "## 7. Machine-level differences",
            "## 8. The listening experiment",
            "## 9. Limitations",
            "## 10. STOP condition",
        ):
            assert heading in text, heading

    def test_it_keeps_observation_inference_and_choice_apart(self, build: Dict[str, Any]) -> None:
        text = build["report_text"]
        assert "**Observed" in text
        assert "**Inference." in text
        assert "**Experimental choice." in text

    def test_it_declares_no_winner(self, build: Dict[str, Any]) -> None:
        """"Rebinding is better" may not be said before the listening happens."""
        text = _flat(build["report_text"]).lower()
        for claim in (
            "the listener preferred",
            "the new binding is better",
            "the experiment shows",
            "we have shown",
            "the result is that",
        ):
            assert claim not in text, claim
        assert "what the outcome will mean" in text
        assert "waiting for" in text

    def test_it_documents_every_changed_assignment(self, build: Dict[str, Any]) -> None:
        text = _flat(build["report_text"])
        for decision in build["bundle"]["plan"].changed:
            assert decision.new_profile in text, decision.new_profile
            assert f"channel {decision.channel}" in text
            assert _flat(decision.reason.split(" (")[0]) in text

    def test_it_states_the_limitations(self, build: Dict[str, Any]) -> None:
        text = _flat(build["report_text"]).lower()
        for phrase in (
            "not a population",
            "one profile per channel",
            "gestures are still not rendered",
            "no profile, fingerprint, schema",
            "the same song is heard three times",
        ):
            assert phrase in text, phrase


class TestTheCommand:
    def test_it_is_registered_and_documents_itself(self) -> None:
        result = CliRunner().invoke(cli, ["prepare-rebinding-10a", "--help"])
        assert result.exit_code == 0
        assert "read-only" in result.output.lower()
        assert "--stage9d-reports" in result.output

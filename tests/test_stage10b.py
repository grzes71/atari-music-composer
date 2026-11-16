"""Stage 10B — the volume contour transfer experiment.

Three things are pinned here, in the order the stage claims them:

1. the mapping's contract, as arithmetic (no fixture needed);
2. the tested set's eligibility rules, from the bank's own measurements;
3. the end-to-end chain — contour → IR → frames → WAV — proved by rendering, and the negative
   proof that with the feature switched off nothing at all moved.

Everything the stage reads is read-only, and the tests check that too: the bank, the six
compositions and the Stage 10A package are hashed before and after a full preparation.
"""

from __future__ import annotations

import csv
import hashlib
import json
import shutil
from pathlib import Path
from typing import Any, Dict, List, Sequence, Tuple

import numpy as np
import pytest
from click.testing import CliRunner

from atari_music import stage10a, stage10b
from atari_music.ai.client import generate_music_from_composition
from atari_music.cli import cli
from atari_music.ir import (
    FRAME_COLUMN_NAMES,
    apply_volume_contour,
    audc_column,
    compile_ir_to_pokey_frames,
)
from atari_music.mads_exporter import (
    VolumeContourNotExpressibleError,
    export_mads_asm,
)
from atari_music.sound_profiles import (
    SoundProfile,
    apply_profile_binding,
    load_profile_binding,
    load_sound_profile_bank,
)

pytestmark = pytest.mark.experimental

REPO_ROOT = Path(__file__).resolve().parents[1]
BANK_DIR = REPO_ROOT / "tests" / "data" / "sound_profiles" / "bank"
STAGE9C_PACKAGE = REPO_ROOT / "examples" / "sound_profile_listening"
STAGE10A_PACKAGE = REPO_ROOT / "examples" / "sound_profile_rebinding_10a"
SONGS_DIR = REPO_ROOT / "examples" / "songs"
PACKAGE_NAME = "sound_profile_volume_contour_10b"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _require_inputs() -> None:
    if not (STAGE9C_PACKAGE / "manifest.json").is_file():
        pytest.skip("the Stage 9C listening package is not present in this checkout")
    if not (STAGE10A_PACKAGE / "manifest.json").is_file():
        pytest.skip("the Stage 10A package is not present in this checkout")


def _dir_digest(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        digest.update(str(path.relative_to(root)).encode("utf-8"))
        digest.update(path.read_bytes())
    return digest.hexdigest()


def _flat(text: str) -> str:
    """Text with its line wrapping removed, so a phrase can be looked for across a line break."""
    return " ".join(text.split())


def _profile(
    runs: Sequence[Sequence[int]],
    *,
    scope: str = "VOICE",
    status: str = "PLAYABLE",
    declared: Any = True,
    rate: float = 2.0,
    shape: str = "tremolo",
) -> SoundProfile:
    """A synthetic profile document carrying one contour. Nothing here touches the real bank."""
    document: Dict[str, Any] = {
        "gesture": {
            "volume": {
                "present": True,
                "static": False,
                "runs": [list(run) for run in runs],
                "change_rate_hz": rate,
                "shape": shape,
                "unit": "audc_volume_level_0_15",
            }
        },
        "pokey": {"hardware": {"distortion": "$A", "audctl_mode": "$00"}},
    }
    if declared is not None:
        document["playability"] = {
            "gesture": {"volume": {"available": declared, "enabled": False}}
        }
    return SoundProfile(
        profile_id="pokey_ref_synthetic",
        scope=scope,
        fingerprint="synthetic",
        document=document,
        status=status,
    )


@pytest.fixture(scope="module")
def build(tmp_path_factory: pytest.TempPathFactory) -> Dict[str, Any]:
    """One complete preparation, shared by every test that needs a rendered package.

    The digests of everything the stage calls read-only are captured immediately before the build,
    so the immutability assertions are made against the state the build actually saw.
    """
    _require_inputs()
    root = tmp_path_factory.mktemp("stage10b")
    package = root / PACKAGE_NAME
    reports = root / "reports"
    docs = root / "docs"
    watched = {
        "bank": _dir_digest(BANK_DIR),
        "stage10a": _dir_digest(STAGE10A_PACKAGE),
        "songs": _dir_digest(SONGS_DIR),
    }
    bundle = stage10b.build_package(
        package,
        stage10a_package=STAGE10A_PACKAGE,
        stage9c_package=STAGE9C_PACKAGE,
        songs_dir=SONGS_DIR,
        bank_dir=BANK_DIR,
        analysis_dir=reports,
        docs_dir=docs,
    )
    return {
        "bundle": bundle,
        "package": package,
        "reports": reports,
        "docs": docs,
        "watched": watched,
        "report_text": (docs / "stage10b_volume_contour_experiment.md").read_text(encoding="utf-8"),
        "manifest": json.loads((package / "manifest.json").read_text(encoding="utf-8")),
        "bank": load_sound_profile_bank(BANK_DIR),
    }


# ---------------------------------------------------------------------------
# 1. The mapping
# ---------------------------------------------------------------------------
class TestTheMapping:
    def test_a_static_contour_is_an_exact_no_op(self) -> None:
        base = [3, 7, 15, 0, 12]
        assert apply_volume_contour(base, [6] * 11) == base

    def test_the_contour_can_only_attenuate(self) -> None:
        base = [15, 12, 9, 4, 1]
        for contour in ([1] * 5, [1, 2, 4, 8, 15], [15, 1, 8, 2, 4]):
            assert all(
                got <= was
                for got, was in zip(apply_volume_contour(base, contour), base)
            )

    def test_the_result_stays_inside_the_audc_nibble(self) -> None:
        got = apply_volume_contour([15, 15, 15], [15, 15, 15, 15, 15])
        assert got == [15, 15, 15]
        assert apply_volume_contour([0, 0, 0], [1, 4, 9]) == [0, 0, 0]

    def test_the_span_tiles_and_truncates(self) -> None:
        # A two-frame contour over five frames: 1, 2, 1, 2, 1 (reference level 2).
        assert apply_volume_contour([10] * 5, [1, 2]) == [5, 10, 5, 10, 5]
        # A five-frame contour over two frames: truncated to its first two levels.
        assert apply_volume_contour([10, 10], [1, 2, 3, 4, 5]) == [2, 4]
        # The restart is per note and positional, not per level: the first frame always takes the
        # contour's first level.
        assert apply_volume_contour([8] * 3, [1, 4, 8])[0] == 1

    def test_a_measured_silence_leaves_the_envelope_untouched(self) -> None:
        assert apply_volume_contour([9, 9, 9], [0, 0, 0]) == [9, 9, 9]

    def test_the_rounding_is_floor_plus_a_half_not_bankers(self) -> None:
        # 1 * 2 / 4 = 0.5. round() would give 0 (banker's rounding); the contract says 1.
        assert apply_volume_contour([1, 1], [2, 4]) == [1, 1]

    def test_the_reference_level_is_the_contours_own_peak(self) -> None:
        # Loudness must not leak: the same shape at two different absolute levels maps the same.
        assert apply_volume_contour([10] * 4, [2, 4, 6, 8]) == apply_volume_contour(
            [10] * 4, [1, 2, 3, 4]
        )

    def test_contour_statistics_are_measured_not_guessed(self) -> None:
        stats = stage10b.contour_statistics([4] * 30 + [8, 8] + [4])
        assert stats["span_frames"] == 33
        assert stats["level_changes"] == 2
        assert stats["distinct_levels"] == 2
        assert stats["min_level"] == 4
        assert stats["max_level"] == 8
        assert stats["depth_ratio"] == 0.5
        assert stats["asymmetric"] is True

    def test_an_empty_contour_has_no_statistics(self) -> None:
        with pytest.raises(stage10b.Stage10BError):
            stage10b.contour_statistics([])

    def test_silence_shape_separates_leading_interior_and_trailing(self) -> None:
        assert stage10b.silence_shape([0, 0, 3, 0, 4, 0]) == {
            "leading": 2,
            "trailing": 1,
            "interior": 1,
        }
        assert stage10b.silence_shape([5, 5]) == {"leading": 0, "trailing": 0, "interior": 0}
        assert stage10b.silence_shape([]) == {"leading": 0, "trailing": 0, "interior": 0}

    def test_the_attenuation_metric_reads_the_render_not_the_envelope(self) -> None:
        contour = [2, 4, 4, 1]
        base = [10] * 4
        observed = apply_volume_contour(base, contour)
        report = stage10b.attenuation_follows(contour, base, observed)
        assert report["frames_compared"] == 4
        # Not exactly 1: the volume nibble is quantized, so the observed *ratio* carries that
        # quantization while the contour does not.
        assert report["correlation"] > 0.99
        assert report["mae_factor"] <= 0.15


# ---------------------------------------------------------------------------
# 2. What may be transferred
# ---------------------------------------------------------------------------
class TestTransferability:
    def test_a_varying_contour_is_transferable(self) -> None:
        contour, refusal = stage10b.transferability(_profile([[4, 10], [8, 4]]))
        assert refusal is None
        assert contour == (4,) * 10 + (8,) * 4

    def test_a_static_contour_is_refused(self) -> None:
        contour, refusal = stage10b.transferability(_profile([[6, 12]]))
        assert contour is None
        assert "constant" in str(refusal)

    def test_a_contour_that_gates_is_refused(self) -> None:
        contour, refusal = stage10b.transferability(_profile([[0, 5], [7, 5]]))
        assert contour is None
        assert refusal == stage10b.CONTOUR_WITHHELD_GATING

    def test_an_absent_contour_is_refused(self) -> None:
        contour, refusal = stage10b.transferability(_profile([]))
        assert contour is None
        assert refusal == stage10b.CONTOUR_WITHHELD_ABSENT

    def test_a_profile_that_withdraws_its_gesture_is_refused(self) -> None:
        contour, refusal = stage10b.transferability(
            _profile([[4, 8], [8, 4]], declared=False)
        )
        assert contour is None
        assert refusal == stage10b.CONTOUR_WITHHELD_DECLARED_UNAVAILABLE

    def test_a_record_of_a_refused_contour_carries_the_evidence(self) -> None:
        record = stage10b.contour_record(_profile([[0, 4], [9, 4], [0, 2]]))
        assert record["transferable"] is False
        assert record["gating_share"] == pytest.approx(0.6)
        assert record["silence_shape"] == {"leading": 4, "trailing": 2, "interior": 0}
        assert record["declared"] == {"available": True, "enabled": False}


# ---------------------------------------------------------------------------
# 3. The tested set
# ---------------------------------------------------------------------------
class TestTheTestedSet:
    def test_the_set_is_the_size_the_brief_asks_for(self, build: Dict[str, Any]) -> None:
        tested = build["bundle"]["tested"]
        by_scope = {item.scope for item in tested}
        assert by_scope == {"VOICE", "PAIR"}
        assert sum(1 for item in tested if item.scope == "VOICE") == stage10b.TESTED_VOICE_PROFILES
        assert sum(1 for item in tested if item.scope == "PAIR") == stage10b.TESTED_PAIR_PROFILES

    def test_every_tested_contour_obeys_the_stated_bounds(self, build: Dict[str, Any]) -> None:
        bank = build["bank"]
        for item in build["bundle"]["tested"]:
            statistics = item.statistics
            assert statistics["min_level"] >= 1, item.profile_id
            assert statistics["distinct_levels"] >= 2, item.profile_id
            assert statistics["change_rate_hz"] <= stage10b.CONTOUR_RATE_LIMIT_HZ, item.profile_id
            assert stage10b.CONTOUR_MIN_SPAN_FRAMES <= statistics["span_frames"], item.profile_id
            assert statistics["span_frames"] <= stage10b.HOLD_MAX_FRAMES, item.profile_id
            assert bank.get(item.profile_id).renderable, item.profile_id

    def test_the_hold_is_long_enough_for_the_contour_to_be_heard_once(
        self, build: Dict[str, Any]
    ) -> None:
        for item in build["bundle"]["tested"]:
            assert item.hold_frames >= item.statistics["span_frames"]
            assert stage10b.HOLD_MIN_FRAMES <= item.hold_frames <= stage10b.HOLD_MAX_FRAMES

    def test_the_selection_is_reproducible(self, build: Dict[str, Any]) -> None:
        again, _ = stage10b.select_tested_profiles(build["bank"])
        assert [item.profile_id for item in again] == [
            item.profile_id for item in build["bundle"]["tested"]
        ]

    def test_every_candidate_has_a_reason_for_its_verdict(self, build: Dict[str, Any]) -> None:
        candidates = build["bundle"]["candidates"]
        assert candidates
        for item in candidates:
            if item.get("qualifies"):
                continue
            assert item["reason"], item["profile_id"]

    def test_the_gating_evidence_records_where_the_silence_sits(
        self, build: Dict[str, Any]
    ) -> None:
        evidence = build["bundle"]["gating_evidence"]
        assert evidence, "the bank is expected to contain contours that gate"
        for record in evidence:
            assert record["gating_share"] > 0.0
            shape = record["silence_shape"]
            assert shape["leading"] + shape["interior"] + shape["trailing"] > 0

    def test_a_candidate_that_qualified_but_lost_says_so(self, build: Dict[str, Any]) -> None:
        losers = [
            item
            for item in build["bundle"]["candidates"]
            if str(item.get("reason", "")).startswith("qualified but not chosen")
        ]
        assert losers, "the bank has more candidates than the set tests"
        for item in losers:
            assert "ranked" in item["reason"]


# ---------------------------------------------------------------------------
# 4. The perturbation proof
# ---------------------------------------------------------------------------
class TestThePerturbationProof:
    def test_every_proof_shows_one_column_and_only_one(self, build: Dict[str, Any]) -> None:
        for proof in build["bundle"]["proofs"]:
            assert proof["only_one_column_changed"], proof["profile_id"]
            assert proof["column_is_audc"], proof["profile_id"]
            assert proof["column_matches_a_sounding_channel"], proof["profile_id"]

    def test_the_distortion_nibble_never_moved(self, build: Dict[str, Any]) -> None:
        for proof in build["bundle"]["proofs"]:
            assert proof["distortion_untouched"], proof["profile_id"]
            assert proof["audf_and_audctl_untouched"], proof["profile_id"]

    def test_the_volume_is_exactly_the_mapping_applied_to_the_unmodulated_frames(
        self, build: Dict[str, Any]
    ) -> None:
        for proof in build["bundle"]["proofs"]:
            assert proof["volume_equals_the_mapping"], proof["profile_id"]
            assert proof["volume_mismatch_frames"] == 0, proof["profile_id"]

    def test_the_audio_follows_the_frame_volume(self, build: Dict[str, Any]) -> None:
        """The chain contour → frames → audio, measured on the audio itself."""
        correlations = [
            proof["audio_tracks_volume_c"]["correlation"] for proof in build["bundle"]["proofs"]
        ]
        assert all(value is not None for value in correlations)
        assert float(np.median(correlations)) > 0.8

    def test_a_reversed_contour_changes_the_sound_again(self, build: Dict[str, Any]) -> None:
        for proof in build["bundle"]["proofs"]:
            assert proof["c_vs_reversed"]["audio_identical"] is False, proof["profile_id"]
            assert proof["c_vs_reversed"]["columns_differing"], proof["profile_id"]

    def test_a_flat_contour_changes_nothing_at_all(self, build: Dict[str, Any]) -> None:
        for proof in build["bundle"]["proofs"]:
            no_op = proof["static_contour_is_a_no_op"]
            assert no_op["frames_identical"], proof["profile_id"]
            assert no_op["audio_identical"], proof["profile_id"]

    def test_the_only_difference_between_b_and_c_is_the_contour_field(
        self, build: Dict[str, Any]
    ) -> None:
        """Rendered through the real path: same document, same binding, one field apart."""
        bank = build["bank"]
        item = build["bundle"]["tested"][0]
        profile = bank.get(item.profile_id)
        document, _ = stage10b.stimulus_document(profile, bank, contour=item.contour)
        binding = load_profile_binding(
            {
                "schema": "atari-music/sound-profile-binding/1",
                "instruments": {"stim": profile.profile_id},
            }
        )
        plain = generate_music_from_composition(document)
        bound_plain = apply_profile_binding(plain, binding, bank, composition=document)
        bound_contour = apply_profile_binding(
            plain, binding, bank, composition=document, volume_contour=True
        )
        assert bound_plain.pokey_ir.instruments[0].volume_contour is None
        assert bound_contour.pokey_ir.instruments[0].volume_contour == list(item.contour)
        stripped = bound_contour.pokey_ir.instruments[0].model_copy(
            update={"volume_contour": None}
        )
        assert stripped == bound_plain.pokey_ir.instruments[0]
        assert compile_ir_to_pokey_frames(bound_plain.pokey_ir).tobytes() != np.asarray(
            compile_ir_to_pokey_frames(bound_contour.pokey_ir)
        ).tobytes()

    def test_a_coupled_profile_carries_its_volume_in_audc2(self, build: Dict[str, Any]) -> None:
        """The 16-bit claim: the pair needs no special case, because AUDC2 is the volume column."""
        pairs = [proof for proof in build["bundle"]["proofs"] if proof["scope"] == "PAIR"]
        assert pairs
        for proof in pairs:
            assert proof["changed_column"] == FRAME_COLUMN_NAMES[audc_column(2)]
        voices = [proof for proof in build["bundle"]["proofs"] if proof["scope"] == "VOICE"]
        for proof in voices:
            assert proof["changed_column"] == FRAME_COLUMN_NAMES[audc_column(1)]


# ---------------------------------------------------------------------------
# 5. The regression
# ---------------------------------------------------------------------------
class TestTheRegression:
    def test_every_published_stage10a_render_is_reproduced_byte_for_byte(
        self, build: Dict[str, Any]
    ) -> None:
        regression = build["bundle"]["regression"]
        assert regression["songs_compared"] == 6
        assert regression["renders_compared"] == 18
        assert regression["all_byte_identical"] is True
        for record in regression["songs"].values():
            for entry in record["published"].values():
                assert entry["byte_identical"], (record["song"], entry["file"])
                assert entry["samples_compared"] > 0

    def test_the_switch_off_is_the_old_code_path(self, build: Dict[str, Any]) -> None:
        """`volume_contour=False` and "no argument at all" must be the same render."""
        bank = build["bank"]
        for subject in build["bundle"]["subjects"]:
            if subject.kind != "song":
                continue
            document = stage10a.load_song(subject.song_path)
            binding = load_profile_binding(
                {
                    "schema": "atari-music/sound-profile-binding/1",
                    "instruments": dict(subject.binding),
                }
            )
            base = generate_music_from_composition(document)
            without = apply_profile_binding(base, binding, bank, composition=document)
            with_false = apply_profile_binding(
                base,
                binding,
                bank,
                composition=document,
                volume_contour=False,
            )
            assert np.array_equal(
                compile_ir_to_pokey_frames(without.pokey_ir),
                compile_ir_to_pokey_frames(with_false.pokey_ir),
            )

    def test_the_withheld_channel_is_left_exactly_as_it_was(self, build: Dict[str, Any]) -> None:
        """Withholding is real: the channel given no contour is byte-identical, the others are not."""
        from atari_music.sound_profiles.binding import _instrument_channels, _resolve_targets

        bank = build["bank"]
        subjects = [subject for subject in build["bundle"]["subjects"] if subject.withheld]
        assert subjects, "the bank is expected to force at least one withholding"
        for subject in subjects:
            document = stage10a.load_song(subject.song_path)
            binding = load_profile_binding(
                {
                    "schema": "atari-music/sound-profile-binding/1",
                    "instruments": dict(subject.binding),
                }
            )
            base = generate_music_from_composition(document)
            before = apply_profile_binding(base, binding, bank, composition=document)
            after = apply_profile_binding(
                base,
                binding,
                bank,
                composition=document,
                volume_contour=list(subject.contour_binding),
            )
            withheld_columns = []
            for item in subject.withheld:
                targets = _resolve_targets(before.pokey_ir, item["instrument"], document)
                channels = _instrument_channels(before.pokey_ir, targets[0])
                withheld_columns.extend(audc_column(channel) for channel in channels)
            assert withheld_columns, subject.subject_id
            plain = compile_ir_to_pokey_frames(before.pokey_ir)
            contoured = compile_ir_to_pokey_frames(after.pokey_ir)
            for column in withheld_columns:
                assert np.array_equal(
                    plain[:, column], contoured[:, column]
                ), (subject.subject_id, column)
            taken = [
                column
                for column in range(plain.shape[1])
                if column < 8 and column % 2 == 1 and column not in withheld_columns
            ]
            assert any(
                not np.array_equal(plain[:, column], contoured[:, column]) for column in taken
            ), subject.subject_id

    def test_the_exporter_refuses_a_song_that_carries_a_contour(
        self, build: Dict[str, Any]
    ) -> None:
        bank = build["bank"]
        subject = next(s for s in build["bundle"]["subjects"] if s.kind == "song")
        document = stage10a.load_song(subject.song_path)
        binding = load_profile_binding(
            {
                "schema": "atari-music/sound-profile-binding/1",
                "instruments": dict(subject.binding),
            }
        )
        base = generate_music_from_composition(document)
        plain = apply_profile_binding(base, binding, bank, composition=document)
        contoured = apply_profile_binding(
            base, binding, bank, composition=document, volume_contour=True
        )
        assert export_mads_asm(plain)  # unchanged behaviour
        with pytest.raises(VolumeContourNotExpressibleError) as caught:
            export_mads_asm(contoured)
        assert caught.value.code == "VOLUME_CONTOUR_NOT_EXPRESSIBLE_IN_XEX"
        assert "player.asm" in str(caught.value)

    def test_the_render_is_reproducible(self, build: Dict[str, Any]) -> None:
        bank = build["bank"]
        item = build["bundle"]["tested"][0]
        profile = bank.get(item.profile_id)
        first, _ = stage10b.render_profile_variants(profile, bank, contour=item.contour)
        second, _ = stage10b.render_profile_variants(profile, bank, contour=item.contour)
        for kind in ("a", "b", "c"):
            assert first[kind].frames_sha256 == second[kind].frames_sha256
            assert first[kind].audio_sha256 == second[kind].audio_sha256


# ---------------------------------------------------------------------------
# 6. The package
# ---------------------------------------------------------------------------
class TestThePackage:
    def test_every_subject_has_three_variants(self, build: Dict[str, Any]) -> None:
        for subject in build["bundle"]["subjects"]:
            for kind in ("a", "b", "c"):
                path = build["package"] / "audio" / f"{subject.subject_id}_{kind}.wav"
                assert path.is_file(), (subject.subject_id, kind)

    def test_every_variant_is_mono_16_bit_pcm_at_the_project_rate(
        self, build: Dict[str, Any]
    ) -> None:
        import wave

        for subject in build["bundle"]["subjects"]:
            for kind in ("a", "b", "c"):
                path = build["package"] / "audio" / f"{subject.subject_id}_{kind}.wav"
                with wave.open(str(path), "rb") as handle:
                    assert handle.getnchannels() == 1
                    assert handle.getsampwidth() == 2
                    assert handle.getframerate() == stage10b.SAMPLE_RATE

    def test_c_differs_from_b_in_every_subject(self, build: Dict[str, Any]) -> None:
        for record in build["bundle"]["subject_records"]:
            assert record["transfer"]["b_vs_c"]["audio_identical"] is False, record["subject_id"]
            assert record["sha256"]["b"] != record["sha256"]["c"], record["subject_id"]

    def test_no_variant_clipped(self, build: Dict[str, Any]) -> None:
        for record in build["bundle"]["subject_records"]:
            assert sum(record["clipped_samples"].values()) == 0, record["subject_id"]

    def test_the_programme_is_b_vs_c_with_a_few_controls(self, build: Dict[str, Any]) -> None:
        trials = build["bundle"]["trials"]
        assert 12 <= len(trials) <= 18
        by_kind: Dict[str, int] = {}
        for trial in trials:
            by_kind[trial.trial_kind] = by_kind.get(trial.trial_kind, 0) + 1
        assert by_kind["profile_current_vs_contour"] == len(build["bundle"]["tested"])
        assert by_kind["song_current_vs_contour"] == 6
        assert by_kind["profile_default_vs_contour"] == stage10b.CONTROL_PROFILE_TRIALS
        assert by_kind["song_default_vs_contour"] == stage10b.CONTROL_SONG_TRIALS

    def test_every_subject_has_exactly_one_b_vs_c_pair(self, build: Dict[str, Any]) -> None:
        for subject in build["bundle"]["subjects"]:
            primary = [
                trial
                for trial in build["bundle"]["trials"]
                if trial.subject_id == subject.subject_id
                and trial.trial_kind.endswith("current_vs_contour")
            ]
            assert len(primary) == 1, subject.subject_id

    def test_every_trial_pairs_two_different_variants(self, build: Dict[str, Any]) -> None:
        for trial in build["bundle"]["trials"]:
            assert trial.a != trial.b, trial.trial_id

    def test_the_blinded_sides_are_the_variants_they_claim(self, build: Dict[str, Any]) -> None:
        audio = build["package"] / "audio"
        for trial in build["bundle"]["trials"]:
            for side, kind in trial.sides.items():
                assert (
                    audio / f"{trial.trial_id}_{side}.wav"
                ).read_bytes() == (
                    audio / f"{trial.subject_id}_{kind}.wav"
                ).read_bytes(), trial.trial_id

    def test_the_orientation_is_seed_dependent(self) -> None:
        subjects = [
            stage10b.Subject(
                subject_id=f"prof_{index:02d}",
                kind="profile",
                label="label",
                binding={"stim": "pokey_ref_x"},
                contour_binding=("stim",),
                withheld=(),
                profile=None,
                contour=(4, 8),
                song_path=None,
                hold_frames=40,
            )
            for index in range(1, 9)
        ]
        first = [
            (trial.trial_id, trial.a, trial.b)
            for trial in stage10b.build_trials(subjects, __import__("random").Random(1))
        ]
        second = [
            (trial.trial_id, trial.a, trial.b)
            for trial in stage10b.build_trials(subjects, __import__("random").Random(2))
        ]
        assert first != second
        third = [
            (trial.trial_id, trial.a, trial.b)
            for trial in stage10b.build_trials(subjects, __import__("random").Random(1))
        ]
        assert first == third

    def test_the_answer_template_is_empty_with_one_row_per_trial(
        self, build: Dict[str, Any]
    ) -> None:
        rows = [
            line
            for line in (build["package"] / "evaluation_volume_contour_10b.csv")
            .read_text(encoding="utf-8")
            .splitlines()
            if line.strip()
        ]
        assert rows[0].split(",") == list(stage10b.ANSWER_HEADER)
        assert len(rows) == len(build["bundle"]["trials"]) + 1
        assert all(
            row.split(",")[1:] == [""] * (len(stage10b.ANSWER_HEADER) - 1) for row in rows[1:]
        )

    def test_the_interface_gives_nothing_away(self, build: Dict[str, Any]) -> None:
        html = (build["package"] / "index.html").read_text(encoding="utf-8")
        lowered = html.lower()
        for token in (
            "pokey_ref_",
            "binding.json",
            "current_vs_contour",
            "default_vs_contour",
            "volume_contour\":",
            "manifest.json",
            "audc",
            "distortion",
        ):
            assert token.lower() not in lowered, token
        for trial in build["bundle"]["trials"]:
            assert trial.side_file("a") in html
        # The embedded payload carries ids and file names and nothing else: no side-to-variant
        # mapping reaches the page.
        payload = html.split("const PACKAGE = ", 1)[1].split(";\n", 1)[0]
        decoded = json.loads(payload)
        assert decoded["experiment"] == stage10b.EXPERIMENT
        for entry in decoded["trials"]:
            assert set(entry) == {"trial_id", "a", "b", "material"}
            assert entry["material"] in {"profile", "song"}
            for side in ("a", "b"):
                assert entry[side].startswith("audio/") and entry[side].endswith(".wav")
                assert entry[side].split("/")[-1].startswith(entry["trial_id"])

    def test_the_interface_asks_the_perceptibility_question(self, build: Dict[str, Any]) -> None:
        html = (build["package"] / "index.html").read_text(encoding="utf-8")
        assert "audible_movement" in html
        assert "change noticeably during a note" in _flat(html)

    def test_the_readme_says_what_is_asked_and_what_was_withheld(
        self, build: Dict[str, Any]
    ) -> None:
        text = _flat((build["package"] / "README.md").read_text(encoding="utf-8"))
        for phrase in (
            "better overall",
            "more convincing as Atari music",
            "sound character",
            "do not open it while listening",
            "was not transferred",
        ):
            assert phrase in text, phrase
        for subject in build["bundle"]["subjects"]:
            for item in subject.withheld:
                assert item["instrument"] in text, item

    def test_the_binding_files_are_the_bindings_that_were_rendered(
        self, build: Dict[str, Any]
    ) -> None:
        for subject in build["bundle"]["subjects"]:
            document = load_profile_binding(
                build["package"] / "bindings" / f"{subject.subject_id}.binding.json"
            )
            assert dict(document.instruments) == dict(subject.binding)

    def test_the_manifest_is_private_and_carries_the_mapping(self, build: Dict[str, Any]) -> None:
        manifest = build["manifest"]
        assert manifest["private"] is True
        assert "answer key" in manifest["warning"]
        assert manifest["mapping"]["reference_level"].startswith("max(contour)")
        assert manifest["variants"]["c"].startswith("PROFILE + VOLUME CONTOUR")


# ---------------------------------------------------------------------------
# 7. Nothing moved
# ---------------------------------------------------------------------------
class TestNothingChanges:
    def test_the_bank_the_songs_and_the_stage10a_package_are_untouched(
        self, build: Dict[str, Any]
    ) -> None:
        watched = build["watched"]
        assert _dir_digest(BANK_DIR) == watched["bank"]
        assert _dir_digest(STAGE10A_PACKAGE) == watched["stage10a"]
        assert _dir_digest(SONGS_DIR) == watched["songs"]

    def test_the_package_never_touches_the_stage9c_package(self, build: Dict[str, Any]) -> None:
        package = build["package"]
        assert package.name == PACKAGE_NAME
        assert package.resolve() != STAGE9C_PACKAGE.resolve()

    def test_the_verification_record_says_all_of_it(self, build: Dict[str, Any]) -> None:
        verification = build["bundle"]["verification"]
        assert verification["compositions_unchanged"] is True
        assert verification["stage10a_package_unchanged"] is True
        assert verification["profile_bank_unchanged"] is True
        assert verification["regression"]["all_byte_identical"] is True
        assert all(verification["only_one_column_changed"].values())
        assert all(verification["audio_differs_b_vs_c"].values())
        assert all(
            record["frames_identical"] and record["audio_identical"]
            for record in verification["static_contour_no_op"].values()
        )

    def test_the_analysis_files_are_written(self, build: Dict[str, Any]) -> None:
        for name in (
            "profiles.json",
            "subjects.json",
            "transfer.json",
            "perturbation.json",
            "regression.json",
            "verification.json",
        ):
            path = build["reports"] / name
            assert path.is_file(), name
            json.loads(path.read_text(encoding="utf-8"))

    def test_no_ir_carries_a_contour_unless_it_was_asked_for(self, build: Dict[str, Any]) -> None:
        """The default of the IR field is what keeps every existing artefact identical."""
        from atari_music.ir import IRInstrument

        assert IRInstrument(id=1, name="x").volume_contour is None


# ---------------------------------------------------------------------------
# 8. The report
# ---------------------------------------------------------------------------
class TestTheReport:
    def test_it_has_the_fourteen_sections_the_brief_asks_for(self, build: Dict[str, Any]) -> None:
        text = build["report_text"]
        for index in range(1, 15):
            assert f"\n## {index}. " in text, index

    def test_it_opens_with_an_explicit_verdict(self, build: Dict[str, Any]) -> None:
        text = build["report_text"]
        assert "**VERDICT: INCONCLUSIVE**" in text
        assert "POSITIVE" in text and "not judged" in text

    def test_it_never_declares_a_winner(self, build: Dict[str, Any]) -> None:
        text = build["report_text"].lower()
        for claim in (
            "sounds better than",
            "is better than",
            "proves the contour",
            "verdict: positive",
            "we recommend",
        ):
            assert claim not in text, claim

    def test_it_keeps_observation_inference_and_choice_apart(
        self, build: Dict[str, Any]
    ) -> None:
        text = build["report_text"]
        for marker in ("**Observed.**", "**Inference.**", "**Experimental choice.**"):
            assert marker in text, marker

    def test_it_documents_every_withheld_channel(self, build: Dict[str, Any]) -> None:
        text = build["report_text"]
        for subject in build["bundle"]["subjects"]:
            for item in subject.withheld:
                assert item["instrument"] in text
                assert item["profile_id"] in text

    def test_it_states_the_limitations(self, build: Dict[str, Any]) -> None:
        text = _flat(build["report_text"])
        for code in (
            "XEX_CANNOT_CARRY_A_CONTOUR",
            "GATING_CONTOURS_ARE_OUT_OF_SCOPE",
            "CONTOUR_IS_RELATIVE",
            "ONE_SOUND_PER_PROFILE",
        ):
            assert code in text, code
        assert "Nothing here has been heard by a human yet" in text

    def test_it_reports_the_regression_numbers_it_claims(self, build: Dict[str, Any]) -> None:
        text = _flat(build["report_text"])
        assert "18 of 18 renders across 6 songs are byte-identical" in text

    def test_it_names_the_xex_gap(self, build: Dict[str, Any]) -> None:
        text = _flat(build["report_text"])
        assert "VOLUME_CONTOUR_NOT_EXPRESSIBLE_IN_XEX" in text


# ---------------------------------------------------------------------------
# 9. Reading the answers back
# ---------------------------------------------------------------------------
class TestTheAnswers:
    def test_an_empty_template_is_not_an_answer(self, build: Dict[str, Any]) -> None:
        summary = stage10b.summarise_answers(build["package"], analysis_dir=None)
        assert summary["answered"] == 0
        assert "note" in summary

    def test_answers_are_counted_against_the_private_key(
        self, build: Dict[str, Any], tmp_path: Path
    ) -> None:
        package = tmp_path / PACKAGE_NAME
        package.mkdir()
        shutil.copyfile(build["package"] / "manifest.json", package / "manifest.json")
        trials = build["manifest"]["trials"]
        with (package / "evaluation_volume_contour_10b.csv").open(
            "w", encoding="utf-8", newline=""
        ) as handle:
            writer = csv.writer(handle)
            writer.writerow(list(stage10b.ANSWER_HEADER))
            for trial in trials:
                writer.writerow(
                    [trial["trial_id"], "a", "b", "a", "both", "4", "synthetic answer"]
                )
        summary = stage10b.summarise_answers(package, analysis_dir=None)
        assert summary["answered"] == len(trials)
        assert summary["preference"]["c"] + summary["preference"]["b_or_a"] == len(trials)
        assert summary["perceptibility"]["heard"] == len(trials)
        assert summary["difference_median"] == 4
        assert len(summary["comments"]) == len(trials)

    def test_an_unknown_trial_is_refused(self, build: Dict[str, Any], tmp_path: Path) -> None:
        package = tmp_path / "broken"
        package.mkdir()
        shutil.copyfile(build["package"] / "manifest.json", package / "manifest.json")
        (package / "evaluation_volume_contour_10b.csv").write_text(
            ",".join(stage10b.ANSWER_HEADER) + "\nnot_a_trial,a,b,a,neither,3,\n",
            encoding="utf-8",
        )
        with pytest.raises(stage10b.Stage10BError):
            stage10b.summarise_answers(package, analysis_dir=None)


# ---------------------------------------------------------------------------
# 10. The command
# ---------------------------------------------------------------------------
class TestTheCommand:
    def test_it_is_registered_and_documents_itself(self) -> None:
        result = CliRunner().invoke(cli, ["prepare-volume-contour-10b", "--help"])
        assert result.exit_code == 0, result.output
        assert "volume-contour variants" in result.output

    def test_the_analysis_command_is_registered(self) -> None:
        result = CliRunner().invoke(cli, ["analyze-volume-contour-10b", "--help"])
        assert result.exit_code == 0, result.output


# ---------------------------------------------------------------------------
# 11. The frame columns the whole stage is measured in
# ---------------------------------------------------------------------------
class TestTheFrameColumns:
    def test_the_names_are_the_row_layout(self) -> None:
        assert FRAME_COLUMN_NAMES == (
            "AUDF1",
            "AUDC1",
            "AUDF2",
            "AUDC2",
            "AUDF3",
            "AUDC3",
            "AUDF4",
            "AUDC4",
            "AUDCTL",
        )

    def test_a_volume_change_lands_in_the_column_the_name_claims(
        self, build: Dict[str, Any]
    ) -> None:
        """Derived from a render: a contour can only touch an AUDC column, and only the one it names."""
        bank = build["bank"]
        item = build["bundle"]["tested"][0]
        profile = bank.get(item.profile_id)
        document, _ = stage10b.stimulus_document(profile, bank, contour=item.contour)
        plain = generate_music_from_composition(document)
        binding = load_profile_binding(
            {
                "schema": "atari-music/sound-profile-binding/1",
                "instruments": {"stim": profile.profile_id},
            }
        )
        before = compile_ir_to_pokey_frames(
            apply_profile_binding(plain, binding, bank, composition=document).pokey_ir
        )
        after = compile_ir_to_pokey_frames(
            apply_profile_binding(
                plain, binding, bank, composition=document, volume_contour=True
            ).pokey_ir
        )
        changed = {
            FRAME_COLUMN_NAMES[index]
            for index in np.nonzero((before != after).any(axis=0))[0]
        }
        assert changed == {"AUDC1"}, changed

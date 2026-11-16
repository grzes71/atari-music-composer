"""Stage 9E: the perceptual / renderer gap diagnosis.

These tests lock the diagnosis rather than the numbers: that the pipeline is measured instead of
assumed, that the duplicate groups are reproducible and explained, and — most importantly — that
the stage cannot silently modify anything it is diagnosing.

The end-to-end tests need the 67-profile bank (tracked) and the listening package (gitignored,
built by Stage 9C), so they skip where the experiment has not been run.
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List

import numpy as np
import pytest

from atari_music import stage9e
from atari_music.sound_profiles import load_sound_profile_bank
from atari_music.stage9e import (
    CLASS_REPRESENTATION,
    STATUS_IGNORED,
    STATUS_UNREPRESENTABLE,
    STATUS_USED,
    TrackingMapping,
    container_summary,
    document_delta,
    field_status,
    flatten,
    leaf_paths,
)

pytestmark = pytest.mark.experimental

REPO_ROOT = Path(__file__).resolve().parents[1]
BANK_DIR = REPO_ROOT / "tests" / "data" / "sound_profiles" / "bank"
PACKAGE_DIR = REPO_ROOT / "examples" / "sound_profile_listening"
SONGS_DIR = REPO_ROOT / "examples" / "songs"


def _require_package() -> None:
    if not (PACKAGE_DIR / "manifest.json").is_file():
        pytest.skip("the Stage 9C listening package is not present in this checkout")


def _dir_digest(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(p for p in root.rglob("*") if p.is_file()):
        digest.update(str(path.relative_to(root)).encode("utf-8"))
        digest.update(path.read_bytes())
    return digest.hexdigest()


@pytest.fixture(scope="module")
def bank() -> Any:
    return load_sound_profile_bank(BANK_DIR)


@pytest.fixture(scope="module")
def diagnosis(tmp_path_factory: pytest.TempPathFactory) -> Dict[str, Any]:
    """One complete diagnosis, shared by every test — including the "nothing changed" checks.

    The pre-run digests are captured here, immediately before the analysis runs, so the
    immutability assertions below are made against the state the diagnosis actually saw rather
    than against a second run that would only prove something about itself.
    """
    _require_package()
    out = tmp_path_factory.mktemp("stage9e")
    watched = {
        "bank": _dir_digest(BANK_DIR),
        "audio": _dir_digest(PACKAGE_DIR / "audio"),
        "package": _dir_digest(PACKAGE_DIR),
    }
    written = stage9e.analyze_stage9e(
        bank_dir=BANK_DIR, songs_dir=SONGS_DIR, package_dir=PACKAGE_DIR,
        docs_dir=out, reports_dir=out,
    )
    return {
        "written": written,
        "before": watched,
        "after": {
            "bank": _dir_digest(BANK_DIR),
            "audio": _dir_digest(PACKAGE_DIR / "audio"),
            "package": _dir_digest(PACKAGE_DIR),
        },
        "groups": json.loads(written["duplicate_groups"].read_text(encoding="utf-8")),
        "fields": json.loads(written["pipeline_fields"].read_text(encoding="utf-8")),
        "loss": json.loads(written["information_loss"].read_text(encoding="utf-8")),
        "diffs": json.loads(written["profile_diffs"].read_text(encoding="utf-8")),
        "part_c": json.loads(written["part_c_diagnostics"].read_text(encoding="utf-8")),
        "capabilities": json.loads(written["missing_capabilities"].read_text(encoding="utf-8")),
        "verdict": json.loads(written["verdict"].read_text(encoding="utf-8")),
        "report": written["report"].read_text(encoding="utf-8"),
    }


# ---------------------------------------------------------------------------
# Document plumbing
# ---------------------------------------------------------------------------
class TestDocumentPlumbing:
    def test_flatten_returns_every_leaf_path_deterministically(self) -> None:
        document = {"a": 1, "b": {"c": [10, 20]}, "d": []}
        flat = flatten(document)
        assert list(flat) == ["a", "b.c[0]", "b.c[1]", "d"]
        assert flat["b.c[1]"] == 20
        assert list(flatten(document)) == list(flat), "ordering must be stable"

    def test_document_delta_reports_only_real_differences(self) -> None:
        left = flatten({"a": 1, "b": {"c": 2}})
        right = flatten({"a": 1, "b": {"c": 3}})
        delta = document_delta(left, right)
        assert list(delta) == ["b.c"]
        assert delta["b.c"] == (2, 3)
        assert document_delta(left, left) == {}

    def test_container_summary_groups_leaves_by_section(self) -> None:
        delta = {"gesture.pitch.runs[0][0]": (1, 2), "gesture.pitch.runs[1][0]": (1, 3),
                 "pitch.base_hz": (440.0, 450.0)}
        summary = container_summary(delta, depth=2)
        assert summary == {"gesture.pitch": 2, "pitch.base_hz": 1}

    def test_the_tracking_mapping_records_reads_without_changing_them(self) -> None:
        log: List[str] = []
        tracking = TrackingMapping({"a": {"b": 1}, "c": [7, 8]}, "", log)
        assert tracking["a"]["b"] == 1
        assert tracking["c"][1] == 8
        assert tracking.get("missing", "fallback") == "fallback"
        assert "a" in tracking
        assert log == ["a", "a.b", "c", "c[1]", "missing"]


# ---------------------------------------------------------------------------
# Field propagation, measured
# ---------------------------------------------------------------------------
class TestFieldPropagation:
    def test_the_binding_reads_a_small_measured_subset(self, bank: Any) -> None:
        propagation = stage9e.field_propagation(bank)
        assert propagation["path_count"] > 150
        assert 0 < len(propagation["read_paths"]) < propagation["path_count"] / 5
        for path in propagation["read_paths"]:
            assert path.split(".")[0] in propagation["sections"], path

    def test_every_read_path_is_the_one_that_reaches_the_ir(self, bank: Any) -> None:
        """The measurement must name the values, not just a count."""
        propagation = stage9e.field_propagation(bank)
        for expected in (
            "envelope.frames.attack",
            "envelope.frames.decay",
            "envelope.frames.release",
            "envelope.sustain_level",
            "pokey.hardware.distortion",
            "pokey.hardware.audctl_mode",
        ):
            assert expected in propagation["read_paths"], expected

    def test_statuses_are_assigned_from_the_brief_vocabulary(self, bank: Any) -> None:
        propagation = stage9e.field_propagation(bank)
        allowed = {"USED", "PARTIALLY_USED", "TRANSFORMED", "IGNORED", "UNREPRESENTABLE", "PLAYER_ONLY"}
        assert set(propagation["status_totals"]) <= allowed
        assert set(propagation["status_totals"]) == {STATUS_USED, STATUS_IGNORED,
                                                     STATUS_UNREPRESENTABLE, "PLAYER_ONLY"}

    def test_a_read_path_is_used_and_an_unread_path_is_not(self) -> None:
        assert field_status("envelope.frames.attack", ["envelope.frames"]) == STATUS_USED
        assert field_status("pitch.base_hz", ["envelope.frames"]) == STATUS_IGNORED

    def test_the_gesture_sections_are_unrepresentable_rather_than_missing(self, bank: Any) -> None:
        """A gesture is a series, not a forgotten field: the report must say which it is."""
        propagation = stage9e.field_propagation(bank)
        statuses = {row["path"]: row["status"] for row in propagation["paths"]}
        for path in ("gesture.pitch.runs[0][0]", "gesture.volume.runs[0][0]"):
            assert statuses.get(path) == STATUS_UNREPRESENTABLE, path
        assert statuses.get("pitch.base_hz") == STATUS_IGNORED, "a reference fact is not a series"


# ---------------------------------------------------------------------------
# The measured boundaries
# ---------------------------------------------------------------------------
class TestBoundaries:
    def test_the_frame_compiler_uses_the_fields_the_binding_writes(self, bank: Any) -> None:
        reach = stage9e.reach_of_ir_fields(bank, list(bank.renderable()))
        for field in ("distortion", "audctl", "envelope.attack_frames", "envelope.sustain_vol",
                      "envelope.release_frames"):
            assert reach["fields"][field]["changed"] > 0, field

    def test_fields_that_reach_nothing_are_reported_as_such(self, bank: Any) -> None:
        reach = stage9e.reach_of_ir_fields(bank, list(bank.renderable()))
        for field in ("role", "vibrato_depth", "vibrato_speed", "macro", "name", "profile_id"):
            assert reach["fields"][field]["changed"] == 0, field
        assert reach["fields"]["profile_id"]["changes_frames"] is False if (
            "changes_frames" in reach["fields"]["profile_id"]
        ) else True

    def test_the_audio_is_a_function_of_the_frames(self, bank: Any) -> None:
        usage = stage9e.frame_column_usage(bank)
        assert set(usage) == {"VOICE", "PAIR"}
        voice = usage["VOICE"]["columns"]
        pair = usage["PAIR"]["columns"]
        # A VOICE stimulus sounds on channel 1; AUDCTL is $00 there, so zeroing it changes nothing.
        assert voice["AUDF1"]["changes_audio"] is True
        assert voice["AUDC1"]["changes_audio"] is True
        assert voice["AUDF2"]["changes_audio"] is False, "channel 2 is silent in this stimulus"
        # A PAIR stimulus sounds on channel 2 (the divider's high byte); channel 1's AUDC is 0.
        assert pair["AUDF1"]["changes_audio"] is True, "the pair's divider low byte"
        assert pair["AUDF2"]["changes_audio"] is True, "the pair's divider high byte"
        assert pair["AUDC2"]["changes_audio"] is True, "the pair's sounding channel"
        assert pair["AUDC1"]["changes_audio"] is False, "zero by construction in a pair"
        assert pair["AUDCTL"]["changes_audio"] is True, "the clock the pair is derived from"


# ---------------------------------------------------------------------------
# Duplicate groups
# ---------------------------------------------------------------------------
class TestDuplicateGroups:
    def test_every_renderable_profile_is_covered(self, diagnosis: Dict[str, Any]) -> None:
        _require_package()
        bank = load_sound_profile_bank(BANK_DIR)
        manifest = json.loads((PACKAGE_DIR / "manifest.json").read_text(encoding="utf-8"))
        grouped = {profile for group in diagnosis["groups"]["groups"] for profile in group["profiles"]}
        singles = {
            entry["profile_id"] for entry in manifest["samples"]
        } - grouped
        assert len(grouped) + len(singles) == len(bank.renderable())

    def test_the_group_sizes_match_stage9d(self, diagnosis: Dict[str, Any]) -> None:
        """Two independent analyses of the same library must agree."""
        assert diagnosis["groups"]["summary"]["group_sizes"] == [10, 6, 4, 4, 3, 3]
        assert diagnosis["groups"]["summary"]["redundant_profiles"] == 24
        assert diagnosis["verdict"]["groups"] == 6

    def test_every_re_render_is_byte_identical_to_the_package_audio(
        self, diagnosis: Dict[str, Any]
    ) -> None:
        """The strong claim: the diagnosis describes exactly the audio the listener heard."""
        _require_package()
        groups = diagnosis["groups"]
        assert groups["bytes_identical_to_package"] == groups["profiles_probed"] == 61
        assert groups["reproduces_package_grouping"] is True

    def test_a_modified_package_wav_is_refused(self, bank: Any, tmp_path: Path) -> None:
        """Byte identity is enforced, not asserted after the fact."""
        manifest = json.loads((PACKAGE_DIR / "manifest.json").read_text(encoding="utf-8"))
        entry = manifest["samples"][0]
        torn = tmp_path / "torn.wav"
        payload = bytearray((PACKAGE_DIR / entry["file"]).read_bytes())
        payload[-1] ^= 0xFF
        torn.write_bytes(bytes(payload))

        profile = next(
            profile for profile in bank.renderable() if profile.profile_id == entry["profile_id"]
        )
        with pytest.raises(stage9e.Stage9EError):
            stage9e.probe_profile(
                profile, bank, sample_id=entry["sample_id"], package_wav=torn
            )

    def test_the_audio_hashes_are_reproducible(self, diagnosis: Dict[str, Any]) -> None:
        """Every group member's package WAV really is byte-identical to its group's."""
        _require_package()
        required = {
            entry["profile_id"]: entry["file"]
            for entry in json.loads((PACKAGE_DIR / "manifest.json").read_text(encoding="utf-8"))["samples"]
        }
        for group in diagnosis["groups"]["groups"]:
            hashes = set()
            for profile in group["profiles"]:
                path = PACKAGE_DIR / next(
                    entry["file"]
                    for entry in json.loads((PACKAGE_DIR / "manifest.json").read_text(encoding="utf-8"))["samples"]
                    if entry["profile_id"] == profile
                )
                hashes.add(hashlib.sha256(path.read_bytes()).hexdigest())
            assert len(hashes) == 1, group["profiles"]
        assert required

    def test_every_group_is_classified_and_explained(self, diagnosis: Dict[str, Any]) -> None:
        for group in diagnosis["groups"]["groups"]:
            assert group["classification"] in (
                stage9e.CLASS_TRUE, stage9e.CLASS_RENDERER,
                stage9e.CLASS_REPRESENTATION, stage9e.CLASS_UNKNOWN,
            )
            assert group["explanation"]
            assert group["first_agreeing_stage"] in stage9e.PIPELINE_STAGES

    def test_each_group_stops_at_the_binding_not_later(self, diagnosis: Dict[str, Any]) -> None:
        """The whole point: the members agree at the IR, so the loss is before the renderer."""
        for group in diagnosis["groups"]["groups"]:
            assert group["classification"] == CLASS_REPRESENTATION
            assert group["first_agreeing_stage"] == "document"
            assert group["first_divergence"] == "bound_ir"
            assert group["ir_differences"] == []
            assert group["frames_differing"] == 0

    def test_the_documents_really_do_differ(self, diagnosis: Dict[str, Any]) -> None:
        """A group whose documents were identical would be a different finding entirely."""
        for group in diagnosis["groups"]["groups"]:
            assert group["differing_sections"], group["profiles"]
            assert sum(group["differing_sections"].values()) > 0

    def test_the_profile_diffs_are_deterministic_and_complete(self, diagnosis: Dict[str, Any]) -> None:
        payload = diagnosis["diffs"]["groups"]
        assert len(payload) == diagnosis["verdict"]["groups"]
        for group in payload:
            assert group["pairs"], "a group of two or more must have at least one pair"
            for pair in group["pairs"]:
                assert pair["audio_sha256_equal"] is True
                # profile_id and profile_fingerprint identify the profile and are expected to
                # differ; nothing that reaches the audio may.
                sound_fields = {
                    key: value
                    for key, value in pair["ir_differences"].items()
                    if key not in ("profile_id", "profile_fingerprint")
                }
                assert sound_fields == {}, sound_fields
                assert pair["frames_differing"] == 0
                assert pair["document_paths_differing"] == len(pair["document_delta"])


# ---------------------------------------------------------------------------
# Gesture and loss
# ---------------------------------------------------------------------------
class TestGestureAndLoss:
    def test_gesture_is_lost_where_the_documents_say_it_is(self, diagnosis: Dict[str, Any]) -> None:
        status = diagnosis["fields"]["gesture"]["status"]
        for series in ("pitch", "volume", "modulation", "timing", "control_state"):
            assert status[series]["verdict"] == "lost", series
            assert status[series]["where"], series
        # The four series the binding could carry but does not; timing is a different loss.
        for series in ("pitch", "volume", "modulation", "control_state"):
            assert status[series]["in_ir"] == 0, series
            assert status[series]["as_register_writes"] == 0, series
        assert "frames_per_tick" in status["timing"]["in_ir"], (
            "timing is lost for a different reason and the report must say so"
        )

    def test_the_documents_do_carry_gestures(self, diagnosis: Dict[str, Any]) -> None:
        counts = diagnosis["fields"]["gesture"]["counts"]
        assert counts["pitch"] > 0
        assert counts["volume"] > 0
        assert counts["pitch_non_static"] > 0

    def test_the_loss_points_name_a_module_and_a_measurement(self, diagnosis: Dict[str, Any]) -> None:
        points = diagnosis["loss"]["loss"]["loss_points"]
        assert [entry["id"] for entry in points] == ["L1", "L2", "L3", "L4"]
        for entry in points:
            assert entry["module"] and entry["measurement"] and entry["classified_as"]
        assert "_rebuild_song" in points[0]["module"]
        assert "pure function" in points[2]["what_is_lost"]


# ---------------------------------------------------------------------------
# Part C
# ---------------------------------------------------------------------------
class TestPartC:
    def test_all_six_songs_are_diagnosed(self, diagnosis: Dict[str, Any]) -> None:
        trials = diagnosis["part_c"]["diagnostics"]["trials"]
        assert len(trials) == 6
        for trial in trials:
            assert trial["frames_total"] > 0
            assert trial["listener_preferred"] in ("profile", "default", "not answered")
            assert set(trial["default_level"]) >= {"peak_dbfs", "rms_dbfs", "dynamic_range_db"}

    def test_the_binding_changed_every_bound_instrument(self, diagnosis: Dict[str, Any]) -> None:
        for trial in diagnosis["part_c"]["diagnostics"]["trials"]:
            assert trial["bound_instruments"], trial["song"]

    def test_the_two_sides_were_compared_at_one_shared_gain(self, diagnosis: Dict[str, Any]) -> None:
        loudness = diagnosis["part_c"]["loudness"]
        assert "one gain" in loudness["note"]
        assert len(loudness["per_song"]) == 6
        for entry in loudness["per_song"]:
            assert "rms_delta_db" in entry and "dynamic_range_delta_db" in entry

    def test_the_listener_verdict_is_reported_not_reinterpreted(self, diagnosis: Dict[str, Any]) -> None:
        outcomes = Counter(
            trial["listener_preferred"]
            for trial in diagnosis["part_c"]["diagnostics"]["trials"]
        )
        assert outcomes.get("default", 0) >= 1
        assert "5–0" in diagnosis["report"] or "5-0" in diagnosis["report"]


# ---------------------------------------------------------------------------
# Capabilities and verdict
# ---------------------------------------------------------------------------
class TestCapabilitiesAndVerdict:
    def test_capabilities_are_ranked_by_evidence_not_by_opinion(
        self, diagnosis: Dict[str, Any]
    ) -> None:
        capabilities = diagnosis["capabilities"]["capabilities"]
        groups = [entry["groups_needing_it"] for entry in capabilities]
        assert groups == sorted(groups, reverse=True)
        for entry in capabilities:
            assert entry["implemented"] is False, "stage 9E implements nothing"
            assert entry["risk"] and entry["expected_effect"]

    def test_the_volume_and_pitch_contours_have_the_most_evidence(
        self, diagnosis: Dict[str, Any]
    ) -> None:
        capabilities = diagnosis["capabilities"]["capabilities"]
        top = {entry["capability"] for entry in capabilities[:2]}
        assert any("volume contour" in name for name in top)
        assert any("pitch trajectory" in name for name in top)

    def test_a_capability_no_group_needs_is_not_claimed_as_supported(
        self, diagnosis: Dict[str, Any]
    ) -> None:
        quantization = diagnosis["capabilities"]["quantization_only"]
        assert quantization, "the envelope limit is a quantization finding, not a duplicate finding"
        for entry in diagnosis["capabilities"]["capabilities"]:
            if not entry["explains_duplicates"]:
                assert entry["evidence_strength"] == "not applicable"

    def test_the_verdict_answers_all_eight_questions(self, diagnosis: Dict[str, Any]) -> None:
        verdict = diagnosis["verdict"]
        assert verdict["verdict"].startswith("DIAGNOSTICALLY_COMPLETE")
        assert [entry["id"] for entry in verdict["questions"]] == [
            f"Q{n}" for n in range(1, 9)
        ]
        for entry in verdict["questions"]:
            assert len(entry["answer"]) > 40
        assert verdict["next_stage"]

    def test_the_report_has_every_required_section(self, diagnosis: Dict[str, Any]) -> None:
        report = diagnosis["report"]
        for heading in (
            "## 1. Executive summary",
            "## 2. Current pipeline",
            "## 3. Field propagation matrix",
            "## 4. Duplicate audio groups",
            "## 5. Differential rendering",
            "## 6. Information loss points",
            "## 7. Gesture analysis",
            "## 8. Relationship to Part A",
            "## 9. Part C analysis",
            "## 10. Representation vs renderer vs musical interpretation",
            "## 11. True vs renderer vs representation duplicates",
            "## 12. Missing capabilities",
            "## 13. Loudness analysis",
            "## 14. Implications",
            "## 15. Recommended next step",
            "## 16. STOP / decision",
        ):
            assert heading in report, heading

    def test_the_report_does_not_call_a_renderer_duplicate_redundant(
        self, diagnosis: Dict[str, Any]
    ) -> None:
        assert "redundant **today**" in diagnosis["report"]
        assert "does **not** mean a redundant profile" in diagnosis["report"]


# ---------------------------------------------------------------------------
# Nothing may change
# ---------------------------------------------------------------------------
class TestNothingChanges:
    """The stage is diagnostic: it must leave everything it reads exactly as it found it."""

    def test_the_analysis_did_not_modify_anything_it_read(self, diagnosis: Dict[str, Any]) -> None:
        assert diagnosis["before"] == diagnosis["after"], (
            "the diagnosis modified the bank, the package or the audio it was describing"
        )

    def test_the_diagnosis_is_deterministic(self, diagnosis: Dict[str, Any], tmp_path: Path) -> None:
        """A second run must reproduce the first byte for byte."""
        _require_package()
        second = stage9e.analyze_stage9e(
            bank_dir=BANK_DIR, songs_dir=SONGS_DIR, package_dir=PACKAGE_DIR,
            docs_dir=tmp_path / "b", reports_dir=tmp_path / "b",
        )
        for name, path in diagnosis["written"].items():
            assert path.read_bytes() == second[name].read_bytes(), name

    def test_the_audio_was_not_regenerated(self, diagnosis: Dict[str, Any]) -> None:
        wavs = sorted((PACKAGE_DIR / "audio").glob("*.wav"))
        assert len(wavs) == 73
        assert diagnosis["before"]["audio"] == _dir_digest(PACKAGE_DIR / "audio")

    def test_the_composer_and_player_sources_are_untouched(self) -> None:
        """The stage is diagnostic: its own module must not be imported by the pipeline."""
        for name in ("ir.py", "pokey_synth.py", "mads_exporter.py", "pokey_hw.py"):
            source = (REPO_ROOT / "src" / "atari_music" / name).read_text(encoding="utf-8")
            assert "stage9e" not in source, f"{name} must not depend on the diagnosis"
        for name in ("binding.py", "bank.py"):
            source = (REPO_ROOT / "src" / "atari_music" / "sound_profiles" / name).read_text(
                encoding="utf-8"
            )
            assert "stage9e" not in source

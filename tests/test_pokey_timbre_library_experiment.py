"""Experiment 29 — the curated timbre candidate library and its blind audition.

These tests check the *experiment*, not the sound. Specifically:

* the inventory covers all 67 profiles and the historical playability breakdown is verified from
  repository data rather than quoted;
* the shortlist is 12 candidates with no duplicated profile, each renderable, covering several
  generator families, and the two profiles the production binding refuses are recorded and excluded;
* the clip plan is deterministic, gives every candidate one clip per group, and shuffles the candidate
  order inside each group;
* every clip renders through the production path with the profile's own generator and clock reaching
  the stream — nothing is substituted, and C1's generator and octave pulse are the real ones;
* the listening page leaks no candidate name, profile id or generator byte, and its JavaScript parses;
* the CSV templates match the headers the page downloads;
* one shared gain is applied to all clips with no per-file normalisation;
* no production file is changed.
"""

from __future__ import annotations

import hashlib
import csv
import json
import re
import shutil
import subprocess
import tempfile
import wave
from pathlib import Path
from typing import Any, Dict, List, Tuple

import numpy as np
import pytest

from atari_music import cli as cli_module
from atari_music import ir
from atari_music import pokey_timbre_library_experiment as e29

PRODUCTION_FILES: Tuple[str, ...] = (
    "src/atari_music/ir.py",
    "src/atari_music/pokey_hw.py",
    "src/atari_music/pokey_synth.py",
    "src/atari_music/constants.py",
    "src/atari_music/cli.py",
    "src/atari_music/mads_exporter.py",
    "src/atari_music/ai/dsl.py",
    "src/atari_music/ai/client.py",
    "src/atari_music/sound_profiles/bank.py",
    "src/atari_music/sound_profiles/binding.py",
)

DELIVERED = e29.DEFAULT_OUTPUT_DIR


def file_hash(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read_wav(path: Path) -> Tuple[Any, np.ndarray]:
    with wave.open(str(path), "rb") as handle:
        params = handle.getparams()
        raw = handle.readframes(handle.getnframes())
    return params, np.frombuffer(raw, dtype=np.int16)


@pytest.fixture(scope="module")
def bank() -> Any:
    return e29.load_bank()


@pytest.fixture(scope="module")
def inventory(bank: Any) -> List[Dict[str, Any]]:
    return e29.build_inventory(bank)


@pytest.fixture(scope="module")
def summary(inventory: List[Dict[str, Any]]) -> Dict[str, Any]:
    return e29.inventory_summary(inventory)


@pytest.fixture(scope="module")
def rendered(tmp_path_factory: pytest.TempPathFactory) -> Dict[str, Any]:
    return e29.render_all(tmp_path_factory.mktemp("experiment29"))


# ---------------------------------------------------------------------------
# 1. the inventory
# ---------------------------------------------------------------------------
class TestInventory:
    def test_the_bank_is_the_expected_one(self, bank: Any) -> None:
        assert bank.schema == "pokey-sound-profile-registry-1.0"
        assert len(bank.profiles) == 67

    def test_every_profile_has_a_row(self, inventory: List[Dict[str, Any]]) -> None:
        assert len(inventory) == 67
        assert len({row["profile_id"] for row in inventory}) == 67

    def test_the_historical_breakdown_is_verified(self, summary: Dict[str, Any]) -> None:
        """The figures the brief quotes, checked against the repository rather than assumed."""
        assert summary["by_profile_type"] == {"PAIR": 18, "VOICE": 49}
        assert summary["by_status"] == {
            "MEASUREMENT_ONLY": 6,
            "PLAYABLE": 22,
            "PLAYABLE_WITH_LIMITATION": 39,
        }
        assert summary["renderable_count"] == 61

    def test_every_row_carries_the_required_fields(self, inventory: List[Dict[str, Any]]) -> None:
        required = {
            "profile_id", "profile_type", "status", "renderable", "feasibility",
            "distortion_nibble", "waveform", "audctl_mode", "clock_mode", "pair",
            "divider_bits", "audible_channel", "pitch_base_hz", "pitch_range_semitones",
            "volume_peak_level", "volume_contour_frames", "envelope_frames",
            "envelope_sustain_level", "gesture_pitch_available", "gesture_control_state_available",
            "gesture_volume_available", "blocking_codes", "limitation_codes", "consumer_gap_codes",
            "audible_signature",
        }
        for row in inventory:
            assert required <= set(row), row["profile_id"]

    def test_the_feasibility_verdicts_are_consistent(self, inventory: List[Dict[str, Any]]) -> None:
        for row in inventory:
            if row["status"] == "MEASUREMENT_ONLY":
                assert row["feasibility"] == "unusable", row["profile_id"]
                assert row["renderable"] is False
            else:
                assert row["feasibility"] in ("faithful", "limited"), row["profile_id"]
                assert row["renderable"] is True

    def test_a_measured_pitch_gesture_makes_a_profile_limited(
        self, inventory: List[Dict[str, Any]]
    ) -> None:
        for row in inventory:
            if row["gesture_pitch_available"] and row["renderable"]:
                assert row["feasibility"] == "limited", row["profile_id"]

    def test_the_diversity_the_bank_offers_is_counted(self, summary: Dict[str, Any]) -> None:
        assert summary["distinct_audible_signatures_among_renderable"] == 37
        assert summary["largest_identical_group"] > 1
        assert summary["measured_pitch_gesture_count"] > 0
        assert summary["measured_volume_contour_count"] > 0

    def test_the_unreproduced_properties_are_declared(self) -> None:
        declared = {item["property"] for item in e29.UNREPRODUCED_PROPERTIES}
        assert any("pitch" in item for item in declared)
        assert any("control_state" in item for item in declared)
        assert any("volume" in item for item in declared)
        codes = {item["code"] for item in e29.UNREPRODUCED_PROPERTIES}
        assert "GESTURE_NOT_RENDERABLE_BY_CONSUMER" in codes
        assert "VOLUME_MODULATION_NOT_REPRODUCIBLE" in codes


# ---------------------------------------------------------------------------
# 2. the shortlist
# ---------------------------------------------------------------------------
class TestCandidates:
    def test_the_shortlist_is_twelve_candidates(self) -> None:
        assert len(e29.CANDIDATES) == 12
        assert len(e29.candidate_names()) == 12
        assert len(set(e29.candidate_names())) == 12

    def test_c1_is_present_as_the_reference(self) -> None:
        names = e29.candidate_names()
        assert e29.C1_NAME in names
        assert e29.candidate_by_name(e29.C1_NAME)["kind"] == "experiment"
        assert e29.candidate_by_name(e29.C1_NAME)["profile_id"] is None

    def test_every_bank_candidate_names_a_renderable_profile(self, bank: Any) -> None:
        for candidate in e29.CANDIDATES:
            if candidate["kind"] != "bank":
                continue
            profile = bank.get(str(candidate["profile_id"]))
            assert profile.renderable, candidate["name"]

    def test_no_profile_is_used_twice(self) -> None:
        ids = [c["profile_id"] for c in e29.CANDIDATES if c["profile_id"]]
        assert len(ids) == len(set(ids)) == 11

    def test_every_candidate_documents_its_rationale(self) -> None:
        required = {
            "name", "kind", "generator", "clock", "selected_because",
            "audibly_different_because", "role_hypothesis", "compromises", "why_audition",
        }
        for candidate in e29.CANDIDATES:
            assert required <= set(candidate), candidate["name"]
            for field in required:
                assert candidate[field], (candidate["name"], field)

    def test_the_shortlist_covers_several_generator_families(self) -> None:
        generators = {
            candidate["generator"] for candidate in e29.CANDIDATES if candidate["kind"] == "bank"
        }
        assert len(generators) >= 5, generators
        assert any("$00" in g for g in generators)
        assert any("$60" in g for g in generators)
        assert any("$80" in g for g in generators)
        assert any("$A0" in g for g in generators)
        assert any("$C0" in g for g in generators)

    def test_the_shortlist_covers_both_hardware_configurations(self) -> None:
        clocks = {candidate["clock"] for candidate in e29.CANDIDATES}
        assert any("64 kHz" in clock for clock in clocks)
        assert any("1.79 MHz" in clock for clock in clocks)
        assert any("16-bit" in clock for clock in clocks)

    def test_the_refused_profiles_are_recorded_and_not_selected(self, bank: Any) -> None:
        refused = {item["profile_id"] for item in e29.REFUSED_PROFILES}
        assert refused
        selected = {c["profile_id"] for c in e29.CANDIDATES}
        assert refused.isdisjoint(selected)
        for profile_id in refused:
            assert bank.get(profile_id).renderable, profile_id


# ---------------------------------------------------------------------------
# 3. the clip plan
# ---------------------------------------------------------------------------
class TestClipPlan:
    def test_there_are_thirty_six_clips(self) -> None:
        plan = e29.clip_plan()
        assert len(plan) == 36
        assert [entry["clip"] for entry in plan] == [f"clip_{i:02d}" for i in range(1, 37)]

    def test_the_plan_is_deterministic(self) -> None:
        assert e29.clip_plan() == e29.clip_plan()

    def test_every_candidate_appears_once_per_group(self) -> None:
        plan = e29.clip_plan()
        for score in e29.SCORE_ORDER:
            names = sorted(entry["candidate"] for entry in plan if entry["score"] == score)
            assert names == sorted(e29.candidate_names()), score

    def test_the_candidate_order_is_shuffled_within_each_group(self) -> None:
        plan = e29.clip_plan()
        orders = {
            score: tuple(entry["candidate"] for entry in plan if entry["score"] == score)
            for score in e29.SCORE_ORDER
        }
        assert len(set(orders.values())) == 3, orders
        for score, order in orders.items():
            assert order != e29.candidate_names(), score

    def test_the_clip_lookup_agrees_with_the_plan(self) -> None:
        for entry in e29.clip_plan():
            assert e29.clip_id_for(entry["candidate"], entry["score"]) == entry["clip"]

    def test_an_unknown_candidate_is_refused(self) -> None:
        with pytest.raises(KeyError):
            e29.candidate_by_name("not_a_candidate")


# ---------------------------------------------------------------------------
# 4. the rendering: the profile's own parameters reach the stream
# ---------------------------------------------------------------------------
class TestRendering:
    def test_every_clip_renders_at_the_grid_length(self, rendered: Dict[str, Any]) -> None:
        for row in rendered["rows"]:
            assert row["frames"] == e29.GRID[row["score"]]["frames"], row["clip"]

    def test_the_bank_candidate_gets_its_own_generator(
        self, rendered: Dict[str, Any], bank: Any
    ) -> None:
        """No silent substitution: the AUDC generator nibble is the profile's declared one.

        The channel is the one the clip actually sounds on, not the profile's ``audible_channel`` —
        that field records the channel of the *source recording*, which is not where the profile is
        realized here.
        """
        for row in rendered["rows"]:
            candidate = e29.candidate_by_name(row["candidate"])
            if candidate["kind"] != "bank":
                continue
            profile = bank.get(str(candidate["profile_id"]))
            stream = rendered["streams"][row["clip"]]
            assert len(row["audible_channels"]) == 1, row["clip"]
            channel = int(row["audible_channels"][0])
            generators = {
                int(value) & 0xE0 for value in np.unique(stream[:, ir.audc_column(channel)])
            }
            assert generators == {profile.distortion_byte}, (row["clip"], generators)

    def test_the_bank_candidate_gets_its_own_clock(
        self, rendered: Dict[str, Any], bank: Any
    ) -> None:
        for row in rendered["rows"]:
            candidate = e29.candidate_by_name(row["candidate"])
            if candidate["kind"] != "bank":
                continue
            profile = bank.get(str(candidate["profile_id"]))
            stream = rendered["streams"][row["clip"]]
            assert set(int(v) for v in np.unique(stream[:, 8])) == {profile.audctl_mode}, row["clip"]

    def test_a_voice_candidate_is_a_single_eight_bit_channel(
        self, rendered: Dict[str, Any], bank: Any
    ) -> None:
        for row in rendered["rows"]:
            candidate = e29.candidate_by_name(row["candidate"])
            if candidate["kind"] != "bank":
                continue
            profile = bank.get(str(candidate["profile_id"]))
            if profile.scope != "VOICE":
                continue
            assert row["audible_channels"] == [3], row["clip"]
            assert int(rendered["streams"][row["clip"]][0, 8]) == 0x00

    def test_a_pair_candidate_uses_the_joined_pair(
        self, rendered: Dict[str, Any], bank: Any
    ) -> None:
        for row in rendered["rows"]:
            candidate = e29.candidate_by_name(row["candidate"])
            if candidate["kind"] != "bank":
                continue
            profile = bank.get(str(candidate["profile_id"]))
            if profile.scope != "PAIR":
                continue
            assert row["audible_channels"] == [2], row["clip"]
            assert int(rendered["streams"][row["clip"]][0, 8]) == 0x50

    def test_the_c1_reference_uses_generator_40_and_the_octave_pulse(
        self, rendered: Dict[str, Any]
    ) -> None:
        seen = 0
        for row in rendered["rows"]:
            if row["candidate"] != e29.C1_NAME:
                continue
            seen += 1
            stream = rendered["streams"][row["clip"]]
            generators = {int(v) & 0xE0 for v in np.unique(stream[:, ir.audc_column(3)])}
            assert 0x40 in generators, row["clip"]
            assert len(row["distinct_audf"]) >= 2, row["clip"]
        assert seen == 3

    def test_no_clip_is_silent(self, rendered: Dict[str, Any]) -> None:
        for clip, buffer in rendered["raw"].items():
            assert float(np.max(np.abs(buffer))) > 0.5, clip

    def test_the_profiles_source_channel_does_not_decide_the_render_channel(
        self, rendered: Dict[str, Any], bank: Any
    ) -> None:
        """``audible_channel`` is where the profile was *measured*, not where it is realized.

        A VOICE candidate always plays on CH3 here whatever channel its source recording used, which
        is exactly the contract in ``binding.py``: the profile supplies the clock, the composition
        supplies the channel.
        """
        source_channels = set()
        for candidate in e29.CANDIDATES:
            if candidate["kind"] != "bank":
                continue
            profile = bank.get(str(candidate["profile_id"]))
            source_channels.add(profile.audible_channel)
        assert len(source_channels) > 1, source_channels
        for row in rendered["rows"]:
            candidate = e29.candidate_by_name(row["candidate"])
            if candidate["kind"] != "bank":
                continue
            profile = bank.get(str(candidate["profile_id"]))
            expected = [2] if profile.scope == "PAIR" else [3]
            assert row["audible_channels"] == expected, row["clip"]

    def test_the_grid_is_the_one_experiments_26_to_28_used(self) -> None:
        assert e29.GRID["note"]["frames"] == 48
        assert e29.GRID["phrase"]["frames"] == 80
        assert e29.GRID["phrase_low"]["frames"] == 80
        assert e29.GRID["phrase"]["notes"] == "A4/5 C5/5 E5/5 C5/5"
        assert e29.GRID["phrase_low"]["notes"] == "A3/5 C4/5 E4/5 C4/5"

    def test_the_compiled_composition_plays_the_grid(self) -> None:
        for score in e29.SCORE_ORDER:
            _document, result = e29.compile_composition(score, sixteen_bit=False)
            stream = np.asarray(ir.compile_ir_to_pokey_frames(result.pokey_ir))
            assert stream.shape[0] == e29.GRID[score]["frames"], score


# ---------------------------------------------------------------------------
# 5. unsupported features are reported, not worked around
# ---------------------------------------------------------------------------
class TestUnsupportedFeatures:
    def test_the_refused_profiles_really_are_refused(self, bank: Any) -> None:
        """Verified live: the production binding refuses them for the recorded reason."""
        for item in e29.REFUSED_PROFILES:
            profile = bank.get(item["profile_id"])
            document, result = e29.compile_composition(
                "note", sixteen_bit=profile.scope == "PAIR"
            )
            binding = e29.load_profile_binding({
                "schema": e29.BINDING_SCHEMA,
                "instruments": {"lead": profile.profile_id},
            })
            with pytest.raises(Exception) as info:
                e29.apply_profile_binding(result, binding, bank, composition=document)
            assert item["refusal"] in str(info.value), item["profile_id"]

    def test_the_volume_contour_is_not_applied(self, rendered: Dict[str, Any], bank: Any) -> None:
        for row in rendered["rows"]:
            candidate = e29.candidate_by_name(row["candidate"])
            if candidate["kind"] != "bank":
                continue
            profile = bank.get(str(candidate["profile_id"]))
            document, result = e29.compile_composition(
                row["score"], sixteen_bit=profile.scope == "PAIR"
            )
            binding = e29.load_profile_binding({
                "schema": e29.BINDING_SCHEMA,
                "instruments": {"lead": profile.profile_id},
            })
            bound = e29.apply_profile_binding(result, binding, bank, composition=document)
            for instrument in bound.pokey_ir.instruments:
                assert instrument.volume_contour is None, row["clip"]

    def test_every_measurement_only_profile_is_excluded(
        self, inventory: List[Dict[str, Any]]
    ) -> None:
        unusable = {row["profile_id"] for row in inventory if not row["renderable"]}
        assert len(unusable) == 6
        selected = {c["profile_id"] for c in e29.CANDIDATES}
        assert unusable.isdisjoint(selected)


# ---------------------------------------------------------------------------
# 6. the blinding
# ---------------------------------------------------------------------------
class TestBlinding:
    def test_the_page_leaks_no_candidate_or_profile(self, rendered: Dict[str, Any]) -> None:
        page = rendered["page_path"].read_text(encoding="utf-8")
        for candidate in e29.CANDIDATES:
            assert candidate["name"] not in page, candidate["name"]
            if candidate["profile_id"]:
                assert candidate["profile_id"] not in page, candidate["profile_id"]
        for token in ("pokey_ref", "generator", "profile_id", "distortion"):
            assert token not in page, token

    def test_the_embedded_package_carries_no_candidate(self, rendered: Dict[str, Any]) -> None:
        page = rendered["page_path"].read_text(encoding="utf-8")
        match = re.search(r"const PACKAGE = (\{.*?\});\n", page, re.S)
        assert match
        package = json.loads(match.group(1))
        for clip in package["clips"]:
            assert sorted(clip) == ["audio", "clip", "score"]
        assert "candidates" not in package

    def test_the_mapping_lives_only_in_the_manifest(self, rendered: Dict[str, Any]) -> None:
        manifest = e29.build_manifest(rendered)
        assert manifest["private"] is True
        assert len(manifest["clip_mapping"]) == 36
        for row in manifest["clip_mapping"]:
            assert row["candidate"] in e29.candidate_names()

    def test_the_blinding_note_is_honest_about_being_partial(self, rendered: Dict[str, Any]) -> None:
        manifest = e29.build_manifest(rendered)
        assert "PARTIALLY blinded" in manifest["blinding"]["honest_note"]
        note = (rendered["output_dir"] / "README.md").read_text(encoding="utf-8")
        assert "manifest.json" in note

    def test_the_templates_carry_no_candidate_column(self, rendered: Dict[str, Any]) -> None:
        for name in (e29.CLIPS_CSV, e29.SUMMARY_CSV):
            text = (rendered["listening_dir"] / name).read_text(encoding="utf-8")
            for candidate in e29.CANDIDATES:
                assert candidate["name"] not in text, candidate["name"]


# ---------------------------------------------------------------------------
# 7. the page and the CSV templates
# ---------------------------------------------------------------------------
class TestListeningPage:
    def test_the_page_is_complete(self, rendered: Dict[str, Any]) -> None:
        page = rendered["page_path"].read_text(encoding="utf-8")
        assert "__PACKAGE__" not in page and "__TITLE__" not in page
        assert page.startswith("<!DOCTYPE html>")
        assert page.rstrip().endswith("</html>")
        # the audio elements are built from the package at runtime, so the markup carries none
        assert page.split("<script>", 1)[0].count("<audio") == 0
        assert page.count('src="audio/') == 0

    def test_the_page_asks_every_required_question(self, rendered: Dict[str, Any]) -> None:
        package = e29.build_listening_package(rendered)
        assert [s["field"] for s in package["clip_scales"]] == [
            "musical_usefulness_1_5", "character_interest_1_5", "annoyance_1_5",
        ]
        assert package["musical_question"]["field"] == "recognisably_musical"
        assert len(package["musical_question"]["choices"]) == 4
        assert len(package["preference_questions"]) == 2
        assert len(package["overall_questions"]) == 1

    def test_the_package_groups_the_clips_by_score(self, rendered: Dict[str, Any]) -> None:
        package = e29.build_listening_package(rendered)
        assert [group["score"] for group in package["groups"]] == list(e29.SCORE_ORDER)
        for group in package["groups"]:
            assert len(group["clips"]) == 12
            assert group["description"]
        assert len(package["clips"]) == 36

    def test_every_clip_has_an_audio_file(self, rendered: Dict[str, Any]) -> None:
        for row in rendered["rows"]:
            path = rendered["listening_dir"] / "audio" / f"{row['clip']}.wav"
            assert path.is_file(), row["clip"]

    def test_the_wav_format_is_consistent(self, rendered: Dict[str, Any]) -> None:
        for row in rendered["rows"]:
            params, samples = read_wav(rendered["listening_dir"] / "audio" / f"{row['clip']}.wav")
            assert params.nchannels == 1, row["clip"]
            assert params.sampwidth == 2, row["clip"]
            assert params.framerate == e29.SAMPLE_RATE, row["clip"]
            assert params.nframes == row["samples"], row["clip"]
            assert samples.dtype == np.int16

    def test_the_page_script_parses(self, rendered: Dict[str, Any]) -> None:
        node = shutil.which("node")
        if node is None:
            pytest.skip("node is not available to syntax-check the page")
        page = rendered["page_path"].read_text(encoding="utf-8")
        body = page.split("<script>", 1)[1]
        chunks = [chunk.split("</script>")[0] for chunk in body.split("<script>")]
        assert len(chunks) == 2
        for index, chunk in enumerate(chunks):
            with tempfile.NamedTemporaryFile(
                "w", suffix=".js", delete=False, encoding="utf-8"
            ) as handle:
                handle.write(chunk)
                script_path = Path(handle.name)
            try:
                result = subprocess.run(
                    [node, "--check", str(script_path)], capture_output=True, text=True
                )
            finally:
                script_path.unlink()
            assert result.returncode == 0, (index, result.stderr)

    def test_the_page_does_not_upload_anything(self, rendered: Dict[str, Any]) -> None:
        page = rendered["page_path"].read_text(encoding="utf-8")
        for token in ("fetch(", "XMLHttpRequest", "navigator.sendBeacon", "WebSocket"):
            assert token not in page, token
        assert "localStorage" in page


class TestCsvTemplates:
    def test_the_templates_match_the_page_headers(self, rendered: Dict[str, Any]) -> None:
        package = e29.build_listening_package(rendered)
        clips = (rendered["listening_dir"] / e29.CLIPS_CSV).read_text(encoding="utf-8").splitlines()
        summary = (rendered["listening_dir"] / e29.SUMMARY_CSV).read_text(encoding="utf-8").splitlines()
        assert clips[0] == ",".join(package["clip_fields"])
        assert summary[0] == ",".join(package["summary_fields"])

    def test_the_clips_template_has_one_row_per_clip(self, rendered: Dict[str, Any]) -> None:
        with (rendered["listening_dir"] / e29.CLIPS_CSV).open(encoding="utf-8", newline="") as handle:
            rows = list(csv.DictReader(handle))
        assert len(rows) == 36
        assert [row["clip"] for row in rows] == [f"clip_{i:02d}" for i in range(1, 37)]
        assert [row["score"] for row in rows] == [entry["score"] for entry in e29.clip_plan()]

    def test_the_summary_template_has_one_blank_row(self, rendered: Dict[str, Any]) -> None:
        with (rendered["listening_dir"] / e29.SUMMARY_CSV).open(
            encoding="utf-8", newline=""
        ) as handle:
            rows = list(csv.DictReader(handle))
        assert len(rows) == 1
        assert all(value == "" for value in rows[0].values())

    def test_the_summary_fields_cover_every_group(self) -> None:
        for score in e29.SCORE_ORDER:
            assert f"{score}_best_clip" in e29.SUMMARY_FIELDS
            assert f"{score}_least_usable_clip" in e29.SUMMARY_FIELDS
            assert f"{score}_comment" in e29.SUMMARY_FIELDS
        assert "library_diverse_enough" in e29.SUMMARY_FIELDS
        assert "listener" in e29.SUMMARY_FIELDS

    def test_the_clip_fields_cover_every_question(self) -> None:
        for scale in e29.CLIP_SCALES:
            assert scale["field"] in e29.CLIP_FIELDS
        assert e29.CLIP_MUSICAL_QUESTION["field"] in e29.CLIP_FIELDS
        assert {"listener", "clip", "score", "comment"} <= set(e29.CLIP_FIELDS)

    def test_the_page_writes_the_headers_it_declares(self) -> None:
        """The page serialises `PACKAGE.clip_fields` / `PACKAGE.summary_fields`, so the exported
        header is the same tuple the templates are written from."""
        package = e29.build_listening_package({"rows": []})
        assert package["clip_fields"] == list(e29.CLIP_FIELDS)
        assert package["summary_fields"] == list(e29.SUMMARY_FIELDS)
        page = e29.render_page(package)
        assert "PACKAGE.clip_fields" in page
        assert "PACKAGE.summary_fields" in page
        assert "csvEscape" in page


# ---------------------------------------------------------------------------
# 8. the gain policy
# ---------------------------------------------------------------------------
class TestGainPolicy:
    def test_one_shared_gain_for_every_clip(self, rendered: Dict[str, Any]) -> None:
        gain = float(rendered["gain"])
        assert gain == pytest.approx(e29.TARGET_PEAK / float(rendered["reference_peak"]))
        for row in rendered["rows"]:
            expected = e29.e26.to_int16(rendered["raw"][row["clip"]], gain)
            _params, actual = read_wav(
                rendered["listening_dir"] / "audio" / f"{row['clip']}.wav"
            )
            assert np.array_equal(actual, expected), row["clip"]

    def test_the_gain_is_the_loudest_raw_render(self, rendered: Dict[str, Any]) -> None:
        peaks = [float(np.max(np.abs(buffer))) for buffer in rendered["raw"].values()]
        assert float(rendered["reference_peak"]) == pytest.approx(max(peaks))

    def test_the_loudest_clip_reaches_the_target_peak(self, rendered: Dict[str, Any]) -> None:
        assert max(row["peak_after_gain"] for row in rendered["rows"]) == pytest.approx(
            e29.TARGET_PEAK, abs=1e-4
        )

    def test_no_clip_clips(self, rendered: Dict[str, Any]) -> None:
        for row in rendered["rows"]:
            assert row["peak_after_gain"] <= 1.0, row["clip"]
        peaks = sorted((row["peak_after_gain"] for row in rendered["rows"]), reverse=True)
        assert peaks[0] > 0.89

    def test_no_clip_was_normalised_on_its_own(self, rendered: Dict[str, Any]) -> None:
        """Peaks differ, which is exactly what per-file normalisation would have hidden."""
        peaks = {row["peak_after_gain"] for row in rendered["rows"]}
        assert len(peaks) > 1
        manifest = e29.build_manifest(rendered)
        assert manifest["level_policy"]["per_file_normalisation"] is False

    def test_the_loudness_spread_is_published(self, rendered: Dict[str, Any]) -> None:
        note_rows = sorted(
            (row for row in rendered["rows"] if row["score"] == "note"),
            key=lambda row: row["rms_after_gain"],
        )
        spread_db = 20.0 * np.log10(
            note_rows[-1]["rms_after_gain"] / note_rows[0]["rms_after_gain"]
        )
        assert spread_db > 6.0, spread_db
        note = (rendered["output_dir"] / "README.md").read_text(encoding="utf-8")
        assert f"{spread_db:.1f} dB" in note
        for row in note_rows:
            assert row["candidate"] in note


# ---------------------------------------------------------------------------
# 9. determinism
# ---------------------------------------------------------------------------
class TestDeterminism:
    def test_two_runs_produce_identical_bytes(self, tmp_path: Path) -> None:
        first = e29.render_all(tmp_path / "one")
        second = e29.render_all(tmp_path / "two")
        assert first["gain"] == second["gain"]
        assert first["reference_peak"] == second["reference_peak"]
        for row in first["rows"]:
            clip = row["clip"]
            assert file_hash(first["files"][clip]) == file_hash(second["files"][clip]), clip
        for name in ("manifest.json", "candidates.json", "README.md"):
            assert file_hash(first["output_dir"] / name) == file_hash(
                second["output_dir"] / name
            ), name
        assert file_hash(first["page_path"]) == file_hash(second["page_path"])

    def test_the_manifest_is_json_serialisable(self, rendered: Dict[str, Any]) -> None:
        manifest = e29.build_manifest(rendered)
        assert json.loads(json.dumps(manifest)) == manifest

    def test_the_candidates_document_is_json_serialisable(self, rendered: Dict[str, Any]) -> None:
        document = e29.build_candidates_document(rendered)
        assert json.loads(json.dumps(document)) == document
        assert len(document["inventory"]) == 67
        assert len(document["shortlist"]) == 12


# ---------------------------------------------------------------------------
# 10. nothing production changed
# ---------------------------------------------------------------------------
EXPERIMENT_MODULES = {
    "pokey_timbre_library_experiment.py",
    "pokey_timbre_experiment.py",
    "pokey_octave_pulse_experiment.py",
    "pokey_c1_musical_context_experiment.py",
    "pokey_timbre_ab_experiment.py",
}


class TestProductionUntouched:
    def test_the_experiment_module_is_not_imported_by_production(self) -> None:
        sources = [
            path
            for path in (e29.REPO_ROOT / "src" / "atari_music").rglob("*.py")
            if path.name not in EXPERIMENT_MODULES
        ]
        assert sources
        for path in sources:
            text = path.read_text(encoding="utf-8")
            assert "pokey_timbre_library_experiment" not in text, path

    def test_the_cli_does_not_expose_the_experiment(self) -> None:
        text = (e29.REPO_ROOT / "src" / "atari_music" / "cli.py").read_text(encoding="utf-8")
        assert "timbre_library" not in text
        assert "experiment29" not in text

    def test_no_candidate_is_registered_as_an_instrument(self) -> None:
        text = (e29.REPO_ROOT / "src" / "atari_music" / "ir.py").read_text(encoding="utf-8")
        for candidate in e29.CANDIDATES:
            assert candidate["name"] not in text, candidate["name"]

    def test_the_page_references_no_production_module(self, rendered: Dict[str, Any]) -> None:
        page = rendered["page_path"].read_text(encoding="utf-8")
        assert "atari_music" not in page

    def test_the_bank_is_only_read(self, bank: Any) -> None:
        assert bank.schema == "pokey-sound-profile-registry-1.0"
        assert len(bank.profiles) == 67


# ---------------------------------------------------------------------------
# 11. the delivered artefacts, when they have been generated
# ---------------------------------------------------------------------------
@pytest.mark.skipif(not DELIVERED.is_dir(), reason="experiment29 has not been generated here")
class TestDeliveredArtefacts:
    def test_the_delivered_set_is_complete(self) -> None:
        for name in ("manifest.json", "candidates.json", "README.md"):
            assert (DELIVERED / name).is_file(), name
        assert (DELIVERED / "listening" / "index.html").is_file()
        audio = sorted((DELIVERED / "listening" / "audio").glob("clip_*.wav"))
        assert len(audio) == 36
        assert [path.name for path in audio] == [f"clip_{i:02d}.wav" for i in range(1, 37)]

    def test_the_delivered_templates_exist(self) -> None:
        assert (DELIVERED / "listening" / e29.CLIPS_CSV).is_file()
        assert (DELIVERED / "listening" / e29.SUMMARY_CSV).is_file()

    def test_the_delivered_manifest_matches_the_code(self) -> None:
        manifest = json.loads((DELIVERED / "manifest.json").read_text(encoding="utf-8"))
        assert manifest["experiment"] == "experiment29"
        assert manifest["private"] is True
        assert len(manifest["clip_mapping"]) == 36
        assert manifest["inventory_summary"]["profile_count"] == 67
        assert manifest["inventory_summary"]["by_status"]["PLAYABLE"] == 22
        assert len(manifest["refused_profiles"]) == len(e29.REFUSED_PROFILES)
        assert manifest["production_untouched"] == e29.PRODUCTION_STATEMENT

    def test_the_delivered_page_is_blinded(self) -> None:
        page = (DELIVERED / "listening" / "index.html").read_text(encoding="utf-8")
        for candidate in e29.CANDIDATES:
            assert candidate["name"] not in page
            if candidate["profile_id"]:
                assert candidate["profile_id"] not in page

    def test_the_delivered_candidates_document_has_the_whole_inventory(self) -> None:
        document = json.loads((DELIVERED / "candidates.json").read_text(encoding="utf-8"))
        assert len(document["inventory"]) == 67
        assert len(document["shortlist"]) == 12
        for entry in document["shortlist"]:
            assert set(entry["clip_ids"]) == set(e29.SCORE_ORDER)

    def test_the_delivered_readme_states_the_limits(self) -> None:
        note = (DELIVERED / "README.md").read_text(encoding="utf-8")
        assert "not a finding" in note
        assert "manifest.json" in note
        assert "dB between the quietest and the loudest" in note









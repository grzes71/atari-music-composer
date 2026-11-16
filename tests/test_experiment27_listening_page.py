"""The Experiment 27 listening page and its blinded audio package.

These tests protect the two things that could silently break: the **blinding** (a variant label
leaking into the page, the manifest or a CSV would invalidate every answer) and the **alignment**
between what the page asks and what the CSVs contain. They also confirm that the package is
reproducible and that building it changes nothing outside its own folder.
"""

from __future__ import annotations

import csv
import json
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Dict, List

import pytest

from atari_music import pokey_octave_pulse_experiment as e27
from scripts import build_experiment27_listening_page as builder

pytestmark = pytest.mark.experimental

LISTENING = builder.LISTENING_DIR
EXPERIMENT = builder.EXPERIMENT_DIR

#: Tokens that would tell a listener which clip is which, directly or by elimination.
LEAKY_TOKENS = (
    "C1", "C2", "C3", "C4",
    "pulse1", "pulse4", "onset_only", "selected",
    "contrast", "hold_frames", "active_frames", "active_notes",
)


def read_page() -> str:
    return (LISTENING / "index.html").read_text(encoding="utf-8")


def embedded_package(page: str) -> Dict[str, Any]:
    match = re.search(r"const PACKAGE = (\{.*?\});\n", page, re.S)
    assert match, "the page does not embed a PACKAGE object"
    return json.loads(match.group(1))


def page_script(page: str) -> str:
    return page.split("<script>", 1)[1].split("</script>", 1)[0]


@pytest.fixture(scope="module")
def page() -> str:
    return read_page()


@pytest.fixture(scope="module")
def package(page: str) -> Dict[str, Any]:
    return embedded_package(page)


@pytest.fixture(scope="module")
def manifest() -> Dict[str, Any]:
    return json.loads((LISTENING / "manifest.json").read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# 1. the clip mapping
# ---------------------------------------------------------------------------
class TestMapping:
    def test_there_are_twelve_clips_four_per_score(self) -> None:
        clips = builder.build_mapping()
        assert len(clips) == 12
        for score in builder.SCORE_ORDER:
            assert len([c for c in clips if c["score"] == score]) == 4

    def test_the_mapping_is_deterministic(self) -> None:
        assert builder.build_mapping() == builder.build_mapping()

    def test_the_mapping_covers_every_variant_exactly_once_per_score(self) -> None:
        clips = builder.build_mapping()
        for score in builder.SCORE_ORDER:
            variants = sorted(c["variant"] for c in clips if c["score"] == score)
            assert variants == sorted(e27.VARIANT_ORDER)

    def test_every_clip_points_at_a_delivered_wav(self) -> None:
        for row in builder.build_mapping():
            assert row["source"] == e27.wav_filename(row["variant"], row["score"])
            assert (EXPERIMENT / row["source"]).is_file()
            assert row["audio"] == f"audio/{row['clip']}.wav"

    def test_no_clip_keeps_its_natural_position(self) -> None:
        """A derangement, so a clip number cannot be read as a variant index."""
        clips = builder.build_mapping()
        for score in builder.SCORE_ORDER:
            order = [c["variant"] for c in clips if c["score"] == score]
            assert order != list(e27.VARIANT_ORDER), score

    def test_the_clip_ids_are_sequential_and_unique(self) -> None:
        clips = builder.build_mapping()
        assert [c["clip"] for c in clips] == [f"clip_{i:02d}" for i in range(1, 13)]


# ---------------------------------------------------------------------------
# 2. the blinding
# ---------------------------------------------------------------------------
class TestBlinding:
    def test_the_page_contains_no_variant_label(self, page: str) -> None:
        leaked = [token for token in LEAKY_TOKENS if token in page]
        assert leaked == []

    def test_the_embedded_package_carries_no_variant(self, package: Dict[str, Any]) -> None:
        for clip in package["clips"]:
            assert sorted(clip) == ["audio", "clip", "score"]
        assert "variants" not in package

    def test_the_manifest_is_the_only_file_with_the_key(self, manifest: Dict[str, Any]) -> None:
        assert manifest["private"] is True
        assert manifest["seed"] == builder.SEED
        assert len(manifest["clips"]) == 12
        for row in manifest["clips"]:
            assert row["variant"] in e27.VARIANT_ORDER

    def test_the_clip_csv_template_has_no_variant_column(self) -> None:
        header = next(csv.reader((LISTENING / builder.CLIPS_CSV).open(encoding="utf-8")))
        assert "variant" not in header

    def test_the_downloaded_headers_have_no_variant_column(self, package: Dict[str, Any]) -> None:
        assert "variant" not in package["clip_fields"]
        assert not any("variant" in field for field in package["summary_fields"])

    def test_the_readme_does_not_map_a_clip_to_a_variant(self) -> None:
        readme = (LISTENING / "README.md").read_text(encoding="utf-8")
        for row in builder.build_mapping():
            assert f"{row['clip']}" not in readme


# ---------------------------------------------------------------------------
# 3. the page itself
# ---------------------------------------------------------------------------
class TestPage:
    def test_the_placeholders_are_substituted(self, page: str) -> None:
        assert "__PACKAGE__" not in page
        assert "__TITLE__" not in page
        assert "<title>POKEY octave-pulse timbre" in page

    def test_the_page_is_well_formed_html(self, page: str) -> None:
        assert page.startswith("<!DOCTYPE html>")
        assert page.rstrip().endswith("</html>")
        for tag in ("html", "head", "body", "main", "script"):
            assert page.count(f"<{tag}") == page.count(f"</{tag}>"), tag

    def test_the_questions_come_from_the_package(self, page: str, package: Dict[str, Any]) -> None:
        """The page renders the declarations, so a question cannot exist in one place only."""
        script = page_script(page)
        assert "PACKAGE.clip_scales" in script
        assert "PACKAGE.pulse_question" in script
        assert "PACKAGE.preference_questions" in script
        assert "PACKAGE.overall_questions" in script
        assert len(package["clip_scales"]) == 3
        assert len(package["overall_questions"]) == 5

    def test_the_page_asks_every_declared_question(self, package: Dict[str, Any]) -> None:
        fields = [s["field"] for s in package["clip_scales"]]
        fields.append(package["pulse_question"]["field"])
        for field in fields:
            assert field in package["clip_fields"]
        for question in package["overall_questions"]:
            assert question["field"] in package["summary_fields"]

    def test_every_scale_question_has_a_label_per_point(self, package: Dict[str, Any]) -> None:
        for scale in package["clip_scales"]:
            assert len(scale["labels"]) == 5
            assert scale["question"]
        for question in package["overall_questions"]:
            assert len(question["labels"]) >= 2
            assert question["question"]
        choices = package["pulse_question"]["choices"]
        assert [c["value"] for c in choices][0] == "deliberate"

    def test_the_page_lists_all_twelve_clips(self, package: Dict[str, Any]) -> None:
        assert len(package["clips"]) == 12
        assert sum(len(entry["clips"]) for entry in package["scores"]) == 12

    def test_the_page_offers_both_csv_downloads(self, page: str) -> None:
        assert "downloadClips()" in page
        assert "downloadSummary()" in page
        assert "text/csv" in page

    def test_the_csv_header_and_rows_come_from_the_same_field_list(self, page: str) -> None:
        script = page_script(page)
        assert "PACKAGE.clip_fields" in script
        assert "PACKAGE.summary_fields" in script
        assert script.count("PACKAGE.summary_fields") >= 2

    def test_answers_are_kept_in_the_browser(self, page: str) -> None:
        assert "localStorage" in page
        assert builder.__name__  # the builder is the single source, imported above


# ---------------------------------------------------------------------------
# 4. the JavaScript is syntactically valid
# ---------------------------------------------------------------------------
@pytest.mark.skipif(shutil.which("node") is None, reason="node is not on PATH")
class TestJavaScript:
    def test_the_script_parses(self, page: str) -> None:
        with tempfile.NamedTemporaryFile(
            "w", suffix=".js", delete=False, encoding="utf-8"
        ) as handle:
            handle.write(page_script(page))
            path = handle.name
        try:
            result = subprocess.run(
                ["node", "--check", path], capture_output=True, text=True, timeout=60
            )
        finally:
            Path(path).unlink()
        assert result.returncode == 0, result.stderr


# ---------------------------------------------------------------------------
# 5. the blinded audio
# ---------------------------------------------------------------------------
class TestAudio:
    def test_twelve_clips_are_present(self) -> None:
        files = sorted((LISTENING / "audio").glob("*.wav"))
        assert len(files) == 12

    def test_every_copy_is_byte_identical_to_its_delivered_source(
        self, manifest: Dict[str, Any]
    ) -> None:
        for row in manifest["clips"]:
            source = EXPERIMENT / row["source"]
            copy = LISTENING / row["audio"]
            assert copy.is_file(), row["clip"]
            assert copy.read_bytes() == source.read_bytes(), row["clip"]

    def test_the_blinded_names_are_the_only_thing_that_changed(self) -> None:
        """Nothing is re-rendered here, so the page cannot drift from the artefact set."""
        assert not any(p.name.startswith("C") for p in (LISTENING / "audio").glob("*.wav"))


# ---------------------------------------------------------------------------
# 6. the CSV templates
# ---------------------------------------------------------------------------
class TestTemplates:
    def test_the_clip_template_matches_the_downloaded_header(self, package: Dict[str, Any]) -> None:
        with (LISTENING / builder.CLIPS_CSV).open(encoding="utf-8", newline="") as handle:
            rows = list(csv.reader(handle))
        assert rows[0] == package["clip_fields"]
        assert len(rows) == 13
        for index, row in enumerate(rows[1:], start=1):
            assert row[1] == f"clip_{index:02d}"
            assert row[2] in builder.SCORE_ORDER
            assert all(cell == "" for cell in row[3:])

    def test_the_summary_template_matches_the_downloaded_header(
        self, package: Dict[str, Any]
    ) -> None:
        with (LISTENING / builder.SUMMARY_CSV).open(encoding="utf-8", newline="") as handle:
            rows = list(csv.reader(handle))
        assert rows[0] == package["summary_fields"]
        assert len(rows) == 2
        assert rows[1] == [""] * len(package["summary_fields"])

    def test_the_summary_fields_are_exactly_what_the_page_would_build(
        self, package: Dict[str, Any]
    ) -> None:
        """Re-derives the row from the declarations and compares with the declared field list."""
        expected = ["listener"]
        for entry in package["scores"]:
            for question in package["preference_questions"]:
                expected.append(f"{entry['score']}_{question['field']}")
            expected.append(f"{entry['score']}_comment")
        expected += [q["field"] for q in package["overall_questions"]]
        expected.append("comment")
        assert expected == package["summary_fields"] == list(builder.SUMMARY_FIELDS)

    def test_the_clip_fields_cover_every_declared_question(self, package: Dict[str, Any]) -> None:
        """The template header and the downloaded header are the same list, by construction."""
        declared = {"listener", "clip", "score", "comment"}
        declared |= {scale["field"] for scale in package["clip_scales"]}
        declared.add(package["pulse_question"]["field"])
        assert set(package["clip_fields"]) == declared
        assert package["clip_fields"] == list(builder.CLIP_FIELDS)
        with (LISTENING / builder.CLIPS_CSV).open(encoding="utf-8", newline="") as handle:
            assert next(csv.reader(handle)) == package["clip_fields"]



# ---------------------------------------------------------------------------
# 7. the build is reproducible and writes nowhere else
# ---------------------------------------------------------------------------
class TestBuild:
    def test_a_fresh_build_reproduces_the_delivered_package(self, tmp_path: Path) -> None:
        fresh = builder.build(tmp_path / "listening")
        target = fresh["page"].parent
        assert fresh["page"].read_bytes() == (LISTENING / "index.html").read_bytes()
        assert fresh["manifest"].read_bytes() == (LISTENING / "manifest.json").read_bytes()
        assert fresh["readme"].read_bytes() == (LISTENING / "README.md").read_bytes()
        for name in (builder.CLIPS_CSV, builder.SUMMARY_CSV):
            assert (target / name).read_bytes() == (LISTENING / name).read_bytes(), name
        for name in fresh["audio"]:
            assert (target / name).read_bytes() == (LISTENING / name).read_bytes(), name

    def test_two_builds_agree(self, tmp_path: Path) -> None:
        left = builder.build(tmp_path / "a")
        right = builder.build(tmp_path / "b")
        assert left["page"].read_bytes() == right["page"].read_bytes()
        assert left["manifest"].read_bytes() == right["manifest"].read_bytes()

    def test_the_build_writes_only_inside_its_target(self, tmp_path: Path) -> None:
        before = sorted(p.relative_to(LISTENING) for p in LISTENING.rglob("*"))
        builder.build(tmp_path / "elsewhere")
        after = sorted(p.relative_to(LISTENING) for p in LISTENING.rglob("*"))
        assert before == after

    def test_the_build_changes_no_production_or_experiment_module(self, tmp_path: Path) -> None:
        import hashlib

        watched = (
            "src/atari_music/pokey_synth.py",
            "src/atari_music/pokey_hw.py",
            "src/atari_music/ir.py",
            "src/atari_music/cli.py",
            "src/atari_music/pokey_timbre_experiment.py",
            "src/atari_music/pokey_octave_pulse_experiment.py",
        )
        def digest(name: str) -> str:
            return hashlib.sha256((builder.ROOT_DIR / name).read_bytes()).hexdigest()

        before = {name: digest(name) for name in watched}
        builder.build(tmp_path / "render")
        after = {name: digest(name) for name in watched}
        assert before == after

    def test_the_manifest_reuses_the_experiment_summary(self, manifest: Dict[str, Any]) -> None:
        summary_path = EXPERIMENT / "summary.json"
        if not summary_path.is_file():
            pytest.skip("the Experiment 27 summary is not present on this machine")
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
        assert manifest["variants"] == summary["variants"]
        assert manifest["limitations"] == summary["limitations"]
        assert manifest["level_policy"] == summary["level_policy"]

    def test_the_build_refuses_a_missing_wav(self, tmp_path: Path, monkeypatch) -> None:
        monkeypatch.setattr(builder, "EXPERIMENT_DIR", tmp_path / "nothing-here")
        with pytest.raises(FileNotFoundError):
            builder.build(tmp_path / "listening")




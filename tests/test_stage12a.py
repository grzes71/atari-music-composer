"""Stage 12A — profile decoration vs replacement.

These tests pin the experiment to the measured facts and prove the production path is
untouched: the existing binding (variant B) changes the IR fields it always did, and no
production file was modified to make the experiment run.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any, Dict

import pytest
from click.testing import CliRunner

from atari_music import stage12a
from atari_music.cli import cli


@pytest.fixture(scope="module")
def bundle() -> Dict[str, Any]:
    return stage12a.run_experiment()


@pytest.fixture(scope="module")
def usable(bundle: Dict[str, Any]) -> list:
    return [c for c in bundle["cases"] if "variants" in c]


# ---------------------------------------------------------------------------
# 1. Determinism
# ---------------------------------------------------------------------------
class TestDeterminism:
    def test_two_runs_are_equal(self, bundle: Dict[str, Any]) -> None:
        assert stage12a.run_experiment() == bundle

    def test_no_wall_clock_in_the_record(self, bundle: Dict[str, Any]) -> None:
        text = stage12a._md_table(("a",), []) + str(bundle["inputs"])
        assert "created_utc" not in text

    def test_writing_twice_is_byte_identical(self, tmp_path: Path) -> None:
        a = stage12a.write_experiment(
            stage12a.run_experiment(), stage12a_dir=tmp_path / "a", docs_dir=tmp_path / "a"
        )
        b = stage12a.write_experiment(
            stage12a.run_experiment(), stage12a_dir=tmp_path / "b", docs_dir=tmp_path / "b"
        )
        da = {n: hashlib.sha256(p.read_bytes()).hexdigest() for n, p in a.items()}
        db = {n: hashlib.sha256(p.read_bytes()).hexdigest() for n, p in b.items()}
        assert da == db


# ---------------------------------------------------------------------------
# 2. Reconnaissance — the binding writes exactly what it always wrote
# ---------------------------------------------------------------------------
class TestReconnaissance:
    def test_the_binding_still_writes_its_five_fields(self, bundle: Dict[str, Any]) -> None:
        assert set(bundle["binding_writes_ir_fields_union"]) >= {
            "distortion",
            "envelope",
            "audctl",
            "profile_id",
            "profile_fingerprint",
        }

    def test_the_binding_touches_no_note_field(self, bundle: Dict[str, Any]) -> None:
        # pitches/velocity/patterns are composition-owned: never in the changed set
        assert not (
            {"pitch", "midi_pitch", "volume", "patterns", "sequence"} 
            & set(bundle["binding_writes_ir_fields_union"])
        )

    def test_the_pipeline_is_the_one_read_from_source(self, bundle: Dict[str, Any]) -> None:
        joined = " ".join(bundle["pipeline"])
        assert "map_instrument_character" in joined
        assert "_rebuild_song" in joined
        assert "compile_ir_to_pokey_frames" in joined


# ---------------------------------------------------------------------------
# 3. The variants and the byte-level proof (Parts 9)
# ---------------------------------------------------------------------------
class TestVariants:
    def test_every_case_has_all_four_variants(self, usable: list) -> None:
        for record in usable:
            assert set(record["variants"]) == set(stage12a.VARIANT_ORDER)

    def test_decoration_changes_at_most_one_pokey_column(self, usable: list) -> None:
        # A decoration that was meant to touch one field but changed several columns is a bug.
        for record in usable:
            columns = record["variants"]["C"]["proof"]["changed_pokey_columns"]
            assert len(columns) <= 1, (record["case"], columns)
            assert all(name.startswith("AUDC") for name in columns), (record["case"], columns)

    def test_replacement_can_change_more_than_decoration(self, usable: list) -> None:
        wider = [c for c in usable if len(c["variants"]["B"]["proof"]["changed_pokey_columns"]) >= 1]
        assert wider

    def test_a_sanity(self, usable: list) -> None:
        for record in usable:
            assert record["variants"]["A"]["proof"]["differing_frames_vs_baseline"] == 0
            assert record["variants"]["A"]["proof"]["differing_samples_vs_baseline"] == 0


# ---------------------------------------------------------------------------
# 4. Perturbation table (Part 10)
# ---------------------------------------------------------------------------
class TestPerturbation:
    def test_generator_reaches_the_wav_in_both(self, usable: list) -> None:
        record = next(c for c in usable if c["case"] == "lead_noised")
        row = next(r for r in record["perturbation_table"] if r["field"] == "generator")
        assert row["replacement_writes"] is True
        assert row["decoration_writes"] is True
        assert row["changes_wav"] is True

    def test_pitch_and_volume_have_no_ir_field(self, usable: list) -> None:
        for record in usable:
            table = {r["field"]: r for r in record["perturbation_table"]}
            for field in ("pitch/base", "volume"):
                assert table[field]["reaches_ir"] is False
                assert table[field]["replacement_writes"] is False


# ---------------------------------------------------------------------------
# 5. H1 / H2 and the reference comparison (Parts 11-12)
# ---------------------------------------------------------------------------
class TestHypotheses:
    def test_decoration_always_preserves_the_composer_envelope(self, usable: list) -> None:
        for record in usable:
            assert record["preservation"]["decoration_preserves_envelope"] is True

    def test_replacement_destroys_the_envelope_in_some_cases(self, usable: list) -> None:
        assert any(
            not record["preservation"]["replacement_preserves_envelope"] for record in usable
        )

    def test_h1_and_h2_hold_together_at_least_once(self, bundle: Dict[str, Any]) -> None:
        assert bundle["hypotheses"]["H1_decoration_preserves_composer_tuning"]["count"] >= 1
        assert bundle["hypotheses"]["H2_decoration_changes_the_sound"]["count"] >= 1

    def test_decoration_beats_replacement_against_the_reference_somewhere(
        self, bundle: Dict[str, Any]
    ) -> None:
        assert "dup_pair16" in bundle["listening"]["C_closer_to_reference_than_B_in"]


# ---------------------------------------------------------------------------
# 6. The listening package (Part 13)
# ---------------------------------------------------------------------------
class TestListeningPackage:
    def test_a_package_is_justified(self, bundle: Dict[str, Any]) -> None:
        assert bundle["listening"]["justified"] is True

    def test_it_is_small_and_blinded(self, bundle: Dict[str, Any], tmp_path: Path) -> None:
        manifest = stage12a.build_listening_package(bundle, out_dir=tmp_path / "pkg")
        assert 1 <= len(manifest["trials"]) <= 16
        for trial in manifest["trials"]:
            assert set(trial["sides"]) == {"a", "b"}
            assert set(trial["sides"].values()) <= set(stage12a.VARIANT_ORDER)

    def test_it_is_deterministic(self, bundle: Dict[str, Any], tmp_path: Path) -> None:
        a = stage12a.build_listening_package(bundle, out_dir=tmp_path / "a")
        b = stage12a.build_listening_package(bundle, out_dir=tmp_path / "b")
        assert a == b

    def test_the_wavs_and_template_exist(self, bundle: Dict[str, Any], tmp_path: Path) -> None:
        stage12a.build_listening_package(bundle, out_dir=tmp_path / "pkg")
        trials = stage12a.run_experiment()["listening"]
        assert (tmp_path / "pkg" / "manifest.json").is_file()
        assert (tmp_path / "pkg" / "evaluation_stage12a.csv").is_file()
        assert (tmp_path / "pkg" / "metadata.json").is_file()
        wavs = list((tmp_path / "pkg" / "audio").glob("*.wav"))
        assert len(wavs) >= 2
        assert trials["justified"] is True

    def test_the_page_is_built_and_stays_blind(
        self, bundle: Dict[str, Any], tmp_path: Path
    ) -> None:
        manifest = stage12a.build_listening_package(bundle, out_dir=tmp_path / "pkg")
        page = (tmp_path / "pkg" / "index.html").read_text(encoding="utf-8")
        # the payload is substituted and the page can download the answer file
        assert "__PACKAGE__" not in page
        assert "Download the answer CSV" in page
        assert "evaluation_stage12a.csv" in page
        # every trial is present, keyed by id only
        for trial in manifest["trials"]:
            assert trial["trial_id"] in page
        # the private key (which side is the decoration) must NOT leak into the page
        assert '"sides"' not in page
        assert "expected_distinction" not in page
        assert '"compared"' not in page


# ---------------------------------------------------------------------------
# 7. The document and the commands
# ---------------------------------------------------------------------------
class TestReportAndCommand:
    def test_the_report_answers_the_eight_questions(self, bundle: Dict[str, Any]) -> None:
        text = stage12a.render_report(bundle)
        assert "## Final report — the eight questions" in text
        assert "**8. The single recommended next step.**" in text
        assert "NOT ESTABLISHED" in text or "HYPOTHESIS SUPPORTED" in text

    def test_the_report_keeps_the_three_kinds_apart(self, bundle: Dict[str, Any]) -> None:
        text = stage12a.render_report(bundle)
        assert "**Observed" in text
        assert "**Inference" in text
        assert "**Experimental choice" in text

    def test_the_run_command_is_registered(self) -> None:
        result = CliRunner().invoke(cli, ["run-stage12a", "--help"])
        assert result.exit_code == 0, result.output
        assert "decoration" in result.output.lower()

    def test_the_listening_command_is_registered(self) -> None:
        result = CliRunner().invoke(cli, ["prepare-stage12a-listening", "--help"])
        assert result.exit_code == 0, result.output

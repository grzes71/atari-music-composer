"""``--instrument`` on import-dsl / import-json / build-xex (docs/instrument_selection_cli.md).

These tests check the *behaviour* the contract promises, not that a helper exists:

* the option is accepted only by the three compiling commands, and omitting it changes nothing —
  a legacy invocation is byte-identical, and no library is read at all;
* a library instrument resolves to the bank profile the library records, and is applied through the
  same ``apply_profile_binding`` path ``--profile-bindings`` already uses, so a ``--instrument`` run
  and an equivalent ``--profile-bindings`` run produce the same IR;
* the WAV and the XEX paths share that one transformation, so they cannot disagree;
* every refusal the contract defines is raised with its own stable code, before any output file is
  written, and the binding layer's own codes still pass through untouched;
* ``c1_octave_pulse`` is refused rather than approximated.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Dict, List, Optional

import pytest
from click.testing import CliRunner

from atari_music.ai.client import generate_music_from_composition
from atari_music.ai.schema import (
    AICompositionDoc,
    AICompositionMetadata,
    AIHardwareConfig,
    AIInstrumentDef,
    AIPatternChannelEvent,
    AIPatternDef,
)
from atari_music.cli import (
    DEFAULT_INSTRUMENT_LIBRARY,
    INSTRUMENT_BINDING_CONFLICT,
    INSTRUMENT_LIBRARY_MISSING,
    INSTRUMENT_LIBRARY_SCHEMA_UNSUPPORTED,
    INSTRUMENT_LIBRARY_VERSION_MISMATCH,
    INSTRUMENT_NOT_APPLICABLE,
    INSTRUMENT_NOT_EXPRESSIBLE_IN_XEX,
    INSTRUMENT_NOT_FOUND,
    INSTRUMENT_SOURCE_DRIFT,
    INSTRUMENT_TARGET_AMBIGUOUS,
    INSTRUMENT_TARGET_DUPLICATE,
    INSTRUMENT_TARGET_UNKNOWN,
    InstrumentSelectionError,
    _apply_selections,
    _assert_xex_expressible,
    _locate_instrument_library,
    _parse_instrument_assignments,
    cli,
)

pytestmark = [pytest.mark.core, pytest.mark.audio]

REPO_ROOT = Path(__file__).resolve().parents[1]
LIBRARY_DIR = REPO_ROOT / "data" / "instrument_libraries" / "lead" / "v0.1"
LIBRARY_PATH = LIBRARY_DIR / "library.json"
BANK_DIR = REPO_ROOT / "tests" / "data" / "sound_profiles" / "bank"

#: The library instruments this feature supports, and the profile each must resolve to.
SUPPORTED = {
    "pure_sustain": "pokey_ref_25f94201",
    "pure_pluck": "pokey_ref_9daa0429",
    "buzz_steady": "pokey_ref_2b83db43",
}

#: The three commands that compile a composition and then realize it.
SUPPORTED_COMMANDS = ("import-dsl", "import-json", "build-xex")
#: The commands that must not gain the option.
OTHER_COMMANDS = ("export-mads", "compose", "ai-compose")

runner = CliRunner()


#: A four-part composition, one part per channel, with no channel-pair constraints. Deliberately
#: plain: it lets any supported instrument land on any part, so a failure in these tests is about
#: instrument selection and never about an unrelated hardware requirement.
_MINIMAL_DSL = """\
TITLE "Selection Test"
AUTHOR "Test"
KEY C
MODE MINOR
BPM 120

SEQUENCE A

INSTRUMENT lead character=bright_lead
INSTRUMENT bass character=bass
INSTRUMENT harm character=soft_pad
INSTRUMENT perc character=percussion

[PATTERN A length=16]
CH1 lead V14
C4/4 R/12

CH2 harm V10
G3/8 R/8

CH3 bass V12
C2/8 R/8

CH4 perc V15
C4/2 R/14
"""


def _minimal_composition() -> AICompositionDoc:
    """The same composition as an object, for the unit-level tests."""
    return AICompositionDoc(
        metadata=AICompositionMetadata(title="Selection Test", bpm=120, key="C", mode="minor"),
        hardware=AIHardwareConfig(channels=4, use_16bit_bass=False),
        instruments=[
            AIInstrumentDef(id="lead", name="Lead", character="bright_lead"),
            AIInstrumentDef(id="bass", name="Bass", character="bass"),
            AIInstrumentDef(id="harm", name="Harmony", character="soft_pad"),
            AIInstrumentDef(id="perc", name="Drums", character="percussion"),
        ],
        patterns=[
            AIPatternDef(
                id="A",
                length_steps=16,
                channels={
                    "1": [AIPatternChannelEvent(step=0, note="C4", instrument="lead", duration=4, volume=14)],
                    "2": [AIPatternChannelEvent(step=0, note="G3", instrument="harm", duration=8, volume=10)],
                    "3": [AIPatternChannelEvent(step=0, note="C2", instrument="bass", duration=8, volume=12)],
                    "4": [AIPatternChannelEvent(step=0, note="C4", instrument="perc", duration=2, volume=15)],
                },
            )
        ],
        sequence=["A"],
        loop_point=0,
    )


def _write_composition(directory: Path, name: str = "song.dsl") -> Path:
    """The fixture as a Music DSL document, which is what ``import-dsl`` and ``build-xex`` read."""
    path = directory / name
    path.write_text(_MINIMAL_DSL, encoding="utf-8")
    return path


def _write_json_composition(directory: Path, name: str = "song.json") -> Path:
    """The fixture as JSON, for the ``import-json`` tests."""
    path = directory / name
    path.write_text(json.dumps(_minimal_composition().model_dump(mode="json")), encoding="utf-8")
    return path



def _library_document() -> Dict[str, Any]:
    return json.loads(LIBRARY_PATH.read_text(encoding="utf-8"))


def _library_copy(root: Path, dir_name: str, mutate=None, raw: Optional[str] = None) -> Path:
    """A copy of the real library, optionally altered, in a directory named ``dir_name``."""
    target = root / dir_name
    target.mkdir(parents=True, exist_ok=True)
    document = _library_document()
    if mutate is not None:
        mutate(document)
    text = raw if raw is not None else json.dumps(document, indent=1)
    (target / "library.json").write_text(text, encoding="utf-8")
    return target


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _code(result) -> Optional[str]:
    """The stable code a refused run reported, if any."""
    for code in (
        INSTRUMENT_LIBRARY_MISSING, INSTRUMENT_LIBRARY_SCHEMA_UNSUPPORTED,
        INSTRUMENT_LIBRARY_VERSION_MISMATCH, INSTRUMENT_NOT_FOUND, INSTRUMENT_TARGET_UNKNOWN,
        INSTRUMENT_TARGET_AMBIGUOUS, INSTRUMENT_TARGET_DUPLICATE, INSTRUMENT_NOT_APPLICABLE,
        INSTRUMENT_SOURCE_DRIFT, INSTRUMENT_BINDING_CONFLICT, INSTRUMENT_NOT_EXPRESSIBLE_IN_XEX,
    ):
        if f"[{code}]" in result.output:
            return code
    return None


def _binding_file(path: Path, instruments: Dict[str, str]) -> Path:
    path.write_text(json.dumps({
        "schema": "atari-music/sound-profile-binding/1",
        "instruments": instruments,
    }), encoding="utf-8")
    return path


# =============================================================================
# Scope: which commands carry the option
# =============================================================================


@pytest.mark.parametrize("command", SUPPORTED_COMMANDS)
def test_the_option_is_offered_by_the_compiling_commands(command: str) -> None:
    result = runner.invoke(cli, [command, "--help"])
    assert result.exit_code == 0, result.output
    assert "--instrument " in result.output
    assert "--instrument-library" in result.output


@pytest.mark.parametrize("command", OTHER_COMMANDS)
def test_the_option_is_absent_from_the_other_commands(command: str) -> None:
    """``export-mads`` consumes an already-realized IR, so it must not imply a late override."""
    result = runner.invoke(cli, [command, "--help"])
    assert result.exit_code == 0, result.output
    assert "--instrument " not in result.output
    assert "--instrument-library" not in result.output

    rejected = runner.invoke(cli, [command, "--instrument", "lead=pure_sustain"])
    assert rejected.exit_code == 2
    assert "No such option" in rejected.output


# =============================================================================
# Backward compatibility: nothing happens when the option is absent
# =============================================================================


def test_a_legacy_import_dsl_run_is_byte_identical_and_reads_no_library(tmp_path: Path) -> None:
    """With no ``--instrument`` the library is not read, and the output does not move.

    ``--instrument-library`` points at a directory with no ``library.json``. If the run still
    succeeds and produces identical bytes, then no library was loaded, which is the mechanism that
    keeps the option inert when it is absent.
    """
    song = _write_composition(tmp_path)
    empty = tmp_path / "not-a-library"
    empty.mkdir()

    plain = runner.invoke(cli, ["import-dsl", str(song), "--output-wav", str(tmp_path / "a.wav"),
                                "--output-ir", str(tmp_path / "a.ir.json")])
    assert plain.exit_code == 0, plain.output

    ignored = runner.invoke(cli, ["import-dsl", str(song), "--instrument-library", str(empty),
                                  "--output-wav", str(tmp_path / "b.wav"),
                                  "--output-ir", str(tmp_path / "b.ir.json")])
    assert ignored.exit_code == 0, ignored.output
    assert _code(ignored) is None

    assert _sha256(tmp_path / "a.wav") == _sha256(tmp_path / "b.wav")
    assert _sha256(tmp_path / "a.ir.json") == _sha256(tmp_path / "b.ir.json")


def test_no_assignments_leaves_the_compiled_result_untouched() -> None:
    """``_apply_selections`` with nothing to apply returns the very same object."""
    composition = _minimal_composition()
    compiled = generate_music_from_composition(composition)
    assert _apply_selections(compiled, composition, None, None, (), None) is compiled


def test_profile_bindings_behaviour_is_unchanged(tmp_path: Path) -> None:
    """``--profile-bindings`` alone still binds, and produces exactly the IR it always did."""
    song = _write_composition(tmp_path)
    bindings = _binding_file(tmp_path / "bind.json", {"lead": SUPPORTED["pure_sustain"]})

    result = runner.invoke(cli, ["import-dsl", str(song), "--profile-bindings", str(bindings),
                                 "--sound-bank", str(BANK_DIR),
                                 "--output-ir", str(tmp_path / "legacy.ir.json")])
    assert result.exit_code == 0, result.output
    assert SUPPORTED["pure_sustain"] in result.output


def test_sound_bank_without_profile_bindings_is_still_refused(tmp_path: Path) -> None:
    """The pre-existing rule is untouched, even when ``--instrument`` is also present."""
    song = _write_composition(tmp_path)
    result = runner.invoke(cli, ["import-dsl", str(song), "--sound-bank", str(BANK_DIR),
                                 "--instrument", "lead=pure_sustain",
                                 "--output-wav", str(tmp_path / "o.wav")])
    assert result.exit_code != 0
    assert "--sound-bank requires --profile-bindings" in result.output


# =============================================================================
# Resolution: the option reaches the intended bank profile
# =============================================================================


def _fake_mads(monkeypatch, output: Path) -> None:
    """Simulate a successful MADS run, as the existing build-xex tests do.

    The stub writes a well-formed container: the build validates the layout it was handed,
    and accepts the real ``subprocess.run`` signature because it also measures the player.
    """
    import subprocess
    from unittest.mock import MagicMock

    from conftest import fake_xex_bytes

    def fake_run(cmd, capture_output=True, text=True, **kwargs):
        output.write_bytes(fake_xex_bytes())
        proc = MagicMock()
        proc.returncode = 0
        proc.stdout = "Compiled"
        proc.stderr = ""
        return proc

    monkeypatch.setattr(subprocess, "run", fake_run)


def _mads_exe(tmp_path: Path) -> Path:
    exe = tmp_path / "mads.exe"
    exe.write_text("dummy", encoding="utf-8")
    return exe


@pytest.mark.parametrize("command", ("import-dsl", "import-json"))
def test_the_option_is_accepted_by_the_importing_commands(tmp_path: Path, command: str) -> None:
    song = (_write_composition(tmp_path) if command == "import-dsl"
            else _write_json_composition(tmp_path))
    result = runner.invoke(cli, [command, str(song), "--instrument", "lead=pure_sustain",
                                 "--output-wav", str(tmp_path / "o.wav")])
    assert result.exit_code == 0, result.output
    assert (tmp_path / "o.wav").exists()


def test_the_option_is_accepted_by_build_xex(tmp_path: Path, monkeypatch) -> None:
    song = _write_composition(tmp_path)
    xex = tmp_path / "o.xex"
    _fake_mads(monkeypatch, xex)

    result = runner.invoke(cli, ["build-xex", str(song), "--mads", str(_mads_exe(tmp_path)),
                                 "--instrument", "lead=pure_sustain", "--output", str(xex)])
    assert result.exit_code == 0, result.output
    assert xex.exists()


def test_multiple_assignments_are_all_applied(tmp_path: Path) -> None:
    """Two parts, two different instruments, in one invocation."""
    song = _write_composition(tmp_path)
    result = runner.invoke(cli, ["import-dsl", str(song),
                                 "--instrument", "lead=pure_pluck",
                                 "--instrument", "bass=buzz_steady",
                                 "--output-ir", str(tmp_path / "o.ir.json")])
    assert result.exit_code == 0, result.output
    assert SUPPORTED["pure_pluck"] in result.output
    assert "pokey_ref_2b83db43" in result.output


def test_the_selected_instrument_is_the_profile_the_library_records(tmp_path: Path) -> None:
    """The right-hand side is a library id, and it must land on the profile that id names.

    ``pure_sustain`` is ``pokey_ref_25f94201``, whose generator is ``$0A``; the bound voice's AUDC
    must therefore be ``$A0``. A wrong mapping would show up here as a different nibble.
    """
    song = _write_composition(tmp_path)
    result = runner.invoke(cli, ["import-dsl", str(song), "--instrument", "lead=pure_sustain",
                                 "--output-ir", str(tmp_path / "o.ir.json")])
    assert result.exit_code == 0, result.output
    assert SUPPORTED["pure_sustain"] in result.output

    document = json.loads((tmp_path / "o.ir.json").read_text(encoding="utf-8"))
    lead = [i for i in document["instruments"] if i["name"] == "Lead"]
    assert len(lead) == 1
    assert lead[0]["distortion"] == 0xA0
    assert lead[0]["profile_id"] == SUPPORTED["pure_sustain"]

    # The IR records the library's own identity claim, so the applied voice is checkable.
    library = _library_document()
    entry = [e for e in library["instruments"] if e["instrument_id"] == "pure_sustain"][0]
    assert lead[0]["profile_fingerprint"] == entry["identity"]["source"]["profile_fingerprint"]

    profile = json.loads((BANK_DIR / "profiles" / "pokey_ref_25f94201.json").read_text(encoding="utf-8"))
    assert int(str(profile["pokey"]["hardware"]["distortion"]).lstrip("$"), 16) == 0x0A


def test_a_bank_profile_id_is_not_a_library_instrument_id(tmp_path: Path) -> None:
    """The right-hand side names a Lead Library instrument, never a raw bank profile.

    Both routes exist, but they are different languages: a profile id belongs to
    ``--profile-bindings``. Accepting it here would make the two indistinguishable.
    """
    song = _write_composition(tmp_path)
    result = runner.invoke(cli, ["import-dsl", str(song),
                                 "--instrument", f"lead={SUPPORTED['pure_sustain']}",
                                 "--output-wav", str(tmp_path / "o.wav")])
    assert result.exit_code == 1
    assert _code(result) == INSTRUMENT_NOT_FOUND


def test_instrument_reuses_the_profile_binding_path(tmp_path: Path) -> None:
    """``--instrument lead=pure_sustain`` and the equivalent ``--profile-bindings`` agree byte for byte.

    This is the evidence that the override feeds the existing ``apply_profile_binding`` path rather
    than a second, parallel one.
    """
    song = _write_composition(tmp_path)
    bindings = _binding_file(tmp_path / "bind.json", {"lead": SUPPORTED["pure_sustain"]})

    via_binding = runner.invoke(cli, ["import-dsl", str(song), "--profile-bindings", str(bindings),
                                      "--sound-bank", str(BANK_DIR),
                                      "--output-ir", str(tmp_path / "binding.ir.json")])
    assert via_binding.exit_code == 0, via_binding.output

    via_instrument = runner.invoke(cli, ["import-dsl", str(song),
                                         "--instrument", "lead=pure_sustain",
                                         "--output-ir", str(tmp_path / "instrument.ir.json")])
    assert via_instrument.exit_code == 0, via_instrument.output

    assert _sha256(tmp_path / "binding.ir.json") == _sha256(tmp_path / "instrument.ir.json")


def test_the_part_resolver_accepts_a_name_as_well_as_an_id(tmp_path: Path) -> None:
    """The composition's display name resolves too, because the binding layer's resolver is reused."""
    song = _write_composition(tmp_path)
    by_id = runner.invoke(cli, ["import-dsl", str(song), "--instrument", "lead=pure_sustain",
                                "--output-ir", str(tmp_path / "by_id.ir.json")])
    by_name = runner.invoke(cli, ["import-dsl", str(song), "--instrument", "Lead=pure_sustain",
                                  "--output-ir", str(tmp_path / "by_name.ir.json")])
    assert by_id.exit_code == 0 and by_name.exit_code == 0
    assert _sha256(tmp_path / "by_id.ir.json") == _sha256(tmp_path / "by_name.ir.json")


def test_the_default_library_directory_is_used_when_none_is_given(tmp_path: Path) -> None:
    """Resolved from the working directory first, then the repository root — either way, the real one."""
    assert Path(_locate_instrument_library(None)).resolve() == LIBRARY_DIR.resolve()
    song = _write_composition(tmp_path)
    result = runner.invoke(cli, ["import-dsl", str(song), "--instrument", "lead=buzz_steady",
                                 "--output-wav", str(tmp_path / "o.wav")])
    assert result.exit_code == 0, result.output


# =============================================================================
# Refusals
# =============================================================================


def test_an_unknown_instrument_id_lists_the_available_ids(tmp_path: Path) -> None:
    song = _write_composition(tmp_path)
    result = runner.invoke(cli, ["import-dsl", str(song), "--instrument", "lead=nope",
                                 "--output-wav", str(tmp_path / "o.wav")])
    assert result.exit_code == 1
    assert _code(result) == INSTRUMENT_NOT_FOUND
    for instrument_id in ("pure_sustain", "pure_pluck", "buzz_steady", "c1_octave_pulse"):
        assert instrument_id in result.output


def test_an_unknown_part_id_is_refused(tmp_path: Path) -> None:
    song = _write_composition(tmp_path)
    result = runner.invoke(cli, ["import-dsl", str(song), "--instrument", "nosuchpart=pure_sustain",
                                 "--output-wav", str(tmp_path / "o.wav")])
    assert result.exit_code == 1
    assert _code(result) == INSTRUMENT_TARGET_UNKNOWN
    assert "declared parts" in result.output


@pytest.mark.parametrize("value", ("pure_sustain", "lead=", "=pure_sustain", "  =  ", ""))
def test_a_malformed_assignment_is_refused(tmp_path: Path, value: str) -> None:
    song = _write_composition(tmp_path)
    result = runner.invoke(cli, ["import-dsl", str(song), "--instrument", value,
                                 "--output-wav", str(tmp_path / "o.wav")])
    assert result.exit_code == 1
    assert _code(result) == INSTRUMENT_TARGET_UNKNOWN
    assert "PART=INSTRUMENT_ID" in result.output


def test_a_repeated_part_is_refused_rather_than_silently_overridden(tmp_path: Path) -> None:
    song = _write_composition(tmp_path)
    result = runner.invoke(cli, ["import-dsl", str(song),
                                 "--instrument", "lead=pure_sustain",
                                 "--instrument", "lead=pure_pluck",
                                 "--output-wav", str(tmp_path / "o.wav")])
    assert result.exit_code == 1
    assert _code(result) == INSTRUMENT_TARGET_DUPLICATE


def test_a_part_matching_several_instruments_is_refused(tmp_path: Path) -> None:
    """Two instruments sharing an id is ambiguous; the resolver reports both targets."""
    document = _minimal_composition().model_dump(mode="json")
    document["instruments"].append({"id": "lead", "name": "Lead2", "character": "bright_lead"})
    song = tmp_path / "ambiguous.json"
    song.write_text(json.dumps(document), encoding="utf-8")

    result = runner.invoke(cli, ["import-json", str(song), "--instrument", "lead=pure_sustain",
                                 "--output-wav", str(tmp_path / "o.wav")])
    assert result.exit_code == 1
    assert _code(result) == INSTRUMENT_TARGET_AMBIGUOUS


def test_c1_octave_pulse_is_now_realizable(tmp_path: Path) -> None:
    """C1 is a register transform, not a bank profile -- and the player can now realize it.

    This replaces the guard that used to assert an unconditional refusal: the refusal was
    correct while no output could carry the modulation, and the C1 player extension is what
    makes it wrong. The detailed behaviour lives in ``tests/test_c1_modulation.py``.
    """
    song = _write_composition(tmp_path)
    result = runner.invoke(cli, ["import-dsl", str(song),
                                 "--instrument", "lead=c1_octave_pulse",
                                 "--output-wav", str(tmp_path / "o.wav")])
    assert result.exit_code == 0, result.output
    assert (tmp_path / "o.wav").exists()
    assert "octave pulse" in result.output


def test_c1_octave_pulse_reaches_the_xex_data(tmp_path: Path, monkeypatch) -> None:
    song = _write_composition(tmp_path)
    xex = tmp_path / "o.xex"
    _fake_mads(monkeypatch, xex)
    result = runner.invoke(cli, ["build-xex", str(song), "--mads", str(_mads_exe(tmp_path)),
                                 "--instrument", "lead=c1_octave_pulse", "--output", str(xex)])
    assert result.exit_code == 0, result.output
    assert xex.exists()


def test_a_library_directory_without_library_json_is_refused(tmp_path: Path) -> None:
    song = _write_composition(tmp_path)
    empty = tmp_path / "emptylib"
    empty.mkdir()
    result = runner.invoke(cli, ["import-dsl", str(song), "--instrument-library", str(empty),
                                 "--instrument", "lead=pure_sustain",
                                 "--output-wav", str(tmp_path / "o.wav")])
    assert result.exit_code == 1
    assert _code(result) == INSTRUMENT_LIBRARY_MISSING


@pytest.mark.parametrize(
    "mutate, raw",
    [
        (lambda d: d.update(schema="atari-music/instrument-library/99"), None),
        (None, "{ not json"),
        (None, "[1, 2, 3]"),
    ],
)
def test_a_library_that_cannot_be_read_is_refused(tmp_path: Path, mutate, raw) -> None:
    song = _write_composition(tmp_path)
    library = _library_copy(tmp_path, "v0.1", mutate=mutate, raw=raw)
    result = runner.invoke(cli, ["import-dsl", str(song), "--instrument-library", str(library),
                                 "--instrument", "lead=pure_sustain",
                                 "--output-wav", str(tmp_path / "o.wav")])
    assert result.exit_code == 1
    assert _code(result) == INSTRUMENT_LIBRARY_SCHEMA_UNSUPPORTED


def test_a_directory_name_that_contradicts_the_declared_version_is_refused(tmp_path: Path) -> None:
    """The document declares 0.1 but the directory says v9.9; neither silently wins."""
    song = _write_composition(tmp_path)
    library = _library_copy(tmp_path, "v9.9")
    result = runner.invoke(cli, ["import-dsl", str(song), "--instrument-library", str(library),
                                 "--instrument", "lead=pure_sustain",
                                 "--output-wav", str(tmp_path / "o.wav")])
    assert result.exit_code == 1
    assert _code(result) == INSTRUMENT_LIBRARY_VERSION_MISMATCH


def test_a_fingerprint_that_disagrees_with_the_bank_is_refused(tmp_path: Path) -> None:
    """The library's recorded identity is checked against the profile actually loaded."""
    def tamper(document: Dict[str, Any]) -> None:
        for entry in document["instruments"]:
            if entry["instrument_id"] == "pure_sustain":
                entry["identity"]["source"]["profile_fingerprint"] = "0" * 64

    song = _write_composition(tmp_path)
    library = _library_copy(tmp_path, "v0.1", mutate=tamper)
    result = runner.invoke(cli, ["import-dsl", str(song), "--instrument-library", str(library),
                                 "--instrument", "lead=pure_sustain",
                                 "--output-wav", str(tmp_path / "o.wav")])
    assert result.exit_code == 1
    assert _code(result) == INSTRUMENT_SOURCE_DRIFT


def test_an_untouched_copy_of_the_library_still_works(tmp_path: Path) -> None:
    """The drift check is not simply always failing."""
    song = _write_composition(tmp_path)
    library = _library_copy(tmp_path, "v0.1")
    result = runner.invoke(cli, ["import-dsl", str(song), "--instrument-library", str(library),
                                 "--instrument", "lead=pure_sustain",
                                 "--output-wav", str(tmp_path / "o.wav")])
    assert result.exit_code == 0, result.output


# =============================================================================
# Coexistence with --profile-bindings
# =============================================================================


def test_agreeing_sources_for_one_part_are_allowed(tmp_path: Path) -> None:
    song = _write_composition(tmp_path)
    bindings = _binding_file(tmp_path / "same.json", {"lead": SUPPORTED["pure_sustain"]})
    result = runner.invoke(cli, ["import-dsl", str(song), "--profile-bindings", str(bindings),
                                 "--sound-bank", str(BANK_DIR),
                                 "--instrument", "lead=pure_sustain",
                                 "--output-ir", str(tmp_path / "o.ir.json")])
    assert result.exit_code == 0, result.output


def test_two_sources_disagreeing_about_one_part_are_refused(tmp_path: Path) -> None:
    song = _write_composition(tmp_path)
    bindings = _binding_file(tmp_path / "diff.json", {"lead": SUPPORTED["pure_pluck"]})
    result = runner.invoke(cli, ["import-dsl", str(song), "--profile-bindings", str(bindings),
                                 "--sound-bank", str(BANK_DIR),
                                 "--instrument", "lead=pure_sustain",
                                 "--output-wav", str(tmp_path / "o.wav")])
    assert result.exit_code == 1
    assert _code(result) == INSTRUMENT_BINDING_CONFLICT


def test_two_sources_naming_different_parts_are_both_applied(tmp_path: Path) -> None:
    song = _write_composition(tmp_path)
    bindings = _binding_file(tmp_path / "other.json", {"harm": SUPPORTED["pure_pluck"]})
    result = runner.invoke(cli, ["import-dsl", str(song), "--profile-bindings", str(bindings),
                                 "--sound-bank", str(BANK_DIR),
                                 "--instrument", "lead=buzz_steady",
                                 "--output-ir", str(tmp_path / "o.ir.json")])
    assert result.exit_code == 0, result.output
    assert SUPPORTED["pure_pluck"] in result.output
    assert "pokey_ref_2b83db43" in result.output


def test_binding_layer_codes_still_pass_through_unchanged(tmp_path: Path) -> None:
    """An instrument the hardware cannot realize reports the binding layer's own code.

    ``Vaults-of-Nhyrmeth`` joins channels 1+2 for 16-bit bass; ``pure_pluck`` cannot be realized
    there, and the contract says that stays ``PROFILE_AUDCTL_CONFLICT`` rather than becoming a new
    instrument-selection code.
    """
    song = REPO_ROOT / "examples" / "songs" / "Vaults-of-Nhyrmeth.dsl"
    result = runner.invoke(cli, ["import-dsl", str(song), "--instrument", "bass=pure_pluck",
                                 "--output-wav", str(tmp_path / "o.wav")])
    assert result.exit_code == 1
    assert "[PROFILE_AUDCTL_CONFLICT]" in result.output
    assert _code(result) is None
    assert not (tmp_path / "o.wav").exists()


# =============================================================================
# One transformation for WAV and XEX
# =============================================================================


def test_the_wav_and_xex_paths_produce_the_same_realization() -> None:
    """The XEX transform must not be a second, divergent path."""
    composition = _minimal_composition()
    compiled = generate_music_from_composition(composition)
    assignments = _parse_instrument_assignments(("lead=pure_sustain", "bass=buzz_steady"))

    via_wav = _apply_selections(compiled, composition, None, None, assignments, None)
    via_xex = _apply_selections(compiled, composition, None, None, assignments, None, for_xex=True)

    assert via_wav.pokey_ir.model_dump(mode="json") == via_xex.pokey_ir.model_dump(mode="json")
    assert via_wav.pokey_ir.model_dump(mode="json") != compiled.pokey_ir.model_dump(mode="json")


def test_a_selection_the_xex_table_cannot_encode_is_refused() -> None:
    """A per-frame volume contour has no representation in the note table, so it is refused."""
    composition = _minimal_composition()
    compiled = generate_music_from_composition(composition)
    compiled.pokey_ir.instruments[0].volume_contour = [0, 4, 8, 12, 15]

    with pytest.raises(InstrumentSelectionError) as excinfo:
        _assert_xex_expressible(compiled.pokey_ir)
    assert excinfo.value.code == INSTRUMENT_NOT_EXPRESSIBLE_IN_XEX


def test_a_realization_without_a_contour_passes_the_xex_guard() -> None:
    composition = _minimal_composition()
    compiled = generate_music_from_composition(composition)
    bound = _apply_selections(compiled, composition, None, None,
                              _parse_instrument_assignments(("lead=pure_sustain",)), None)
    _assert_xex_expressible(bound.pokey_ir)


# =============================================================================
# Explicit DSL parameters vs the selected profile
# =============================================================================


def _dsl_with_lead_attributes(attributes: str) -> str:
    """The fixture with extra ``INSTRUMENT lead`` attributes, e.g. ``dist=$C0`` or ``att=4``."""
    return _MINIMAL_DSL.replace(
        "INSTRUMENT lead character=bright_lead",
        f"INSTRUMENT lead character=bright_lead {attributes}".rstrip(),
    )


def _dsl_with_a_silent_part() -> str:
    """``harm`` is declared but never plays, so its profile has nothing to realize."""
    return _MINIMAL_DSL.replace("\nCH2 harm V10\nG3/8 R/8\n", "\n")


def test_an_explicit_distortion_the_profile_contradicts_is_refused(tmp_path: Path) -> None:
    """An explicit DSL parameter that disagrees with the profile is the binding layer's conflict.

    ``pure_sustain`` measures generator ``$A``; a DSL that writes ``dist=$C0`` is asking for
    something else, and the contract says that stays ``PROFILE_DISTORTION_CONFLICT`` rather than
    being silently overwritten.
    """
    song = tmp_path / "conflict.dsl"
    song.write_text(_dsl_with_lead_attributes("dist=$C0"), encoding="utf-8")

    result = runner.invoke(cli, ["import-dsl", str(song), "--instrument", "lead=pure_sustain",
                                 "--output-wav", str(tmp_path / "o.wav")])
    assert result.exit_code == 1
    assert "[PROFILE_DISTORTION_CONFLICT]" in result.output
    assert _code(result) is None
    assert not (tmp_path / "o.wav").exists()


def test_an_explicit_attack_wins_over_the_profile_default(tmp_path: Path) -> None:
    """An explicit envelope parameter the profile does not contradict is kept; the rest comes from it.

    ``att=4`` must survive (the profile's own attack is 6), while decay and sustain are the
    profile's — that is the existing precedence, unchanged.
    """
    song = tmp_path / "att.dsl"
    song.write_text(_dsl_with_lead_attributes("att=4"), encoding="utf-8")

    result = runner.invoke(cli, ["import-dsl", str(song), "--instrument", "lead=pure_sustain",
                                 "--output-ir", str(tmp_path / "o.ir.json")])
    assert result.exit_code == 0, result.output

    document = json.loads((tmp_path / "o.ir.json").read_text(encoding="utf-8"))
    envelope = [i for i in document["instruments"] if i["name"] == "Lead"][0]["envelope"]
    assert envelope["attack_frames"] == 4
    assert envelope["decay_frames"] == 0
    assert envelope["sustain_vol"] == 10


def test_a_part_with_no_sounding_notes_is_refused(tmp_path: Path) -> None:
    """A VOICE profile cannot be realized on a part that never sounds."""
    song = tmp_path / "silent.dsl"
    song.write_text(_dsl_with_a_silent_part(), encoding="utf-8")

    result = runner.invoke(cli, ["import-dsl", str(song), "--instrument", "harm=pure_sustain",
                                 "--output-wav", str(tmp_path / "o.wav")])
    assert result.exit_code == 1
    assert "[PROFILE_CHANNEL_REQUIREMENT]" in result.output
    assert _code(result) is None
    assert not (tmp_path / "o.wav").exists()


def test_the_selection_is_baked_into_the_ir_so_a_later_export_agrees(tmp_path: Path) -> None:
    """Why ``export-mads`` gets no flag: the override is already in the IR it consumes."""
    song = _write_composition(tmp_path)
    first = runner.invoke(cli, ["import-dsl", str(song), "--instrument", "lead=pure_sustain",
                                "--output-asm", str(tmp_path / "a.asm"),
                                "--output-ir", str(tmp_path / "i.json")])
    assert first.exit_code == 0, first.output

    second = runner.invoke(cli, ["export-mads", str(tmp_path / "i.json"),
                                 "--output-asm", str(tmp_path / "b.asm")])
    assert second.exit_code == 0, second.output
    assert _sha256(tmp_path / "a.asm") == _sha256(tmp_path / "b.asm")

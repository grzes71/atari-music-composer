"""Tests for scripts/generate_instrument_test_suite.py using mocked subprocess execution."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = REPO_ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import generate_instrument_test_suite as suite  # noqa: E402
from atari_music.api import generate_music  # noqa: E402
from atari_music.instruments.planner import (  # noqa: E402
    arrange_ir_song,
    composition_musical_fingerprint,
    parse_channel_instrument_specs,
)
from atari_music.ir import IRSong  # noqa: E402

pytestmark = pytest.mark.core

FAKE_SECRET_KEY = "sk-test-secret-key-must-never-appear-in-logs"


def _write_env_file(
    path: Path,
    *,
    provider: str = "deepseek",
    api_key: Optional[str] = FAKE_SECRET_KEY,
    model: str = "deepseek-test-model",
) -> Path:
    lines = [f"AI_PROVIDER={provider}", f"AI_MODEL={model}"]
    if api_key is not None:
        lines.append(f"AI_API_KEY={api_key}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def _clear_ai_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for var in (
        "AI_PROVIDER",
        "AI_API_KEY",
        "AI_BASE_URL",
        "AI_MODEL",
        "DEEPSEEK_PROVIDER",
        "DEEPSEEK_API_KEY",
        "DEEPSEEK_BASE_URL",
        "DEEPSEEK_MODEL",
        "OPENAI_API_KEY",
        "OPENAI_BASE_URL",
        "OPENAI_MODEL",
    ):
        monkeypatch.delenv(var, raising=False)


def _flag_value(cmd: List[str], flag: str) -> str:
    idx = cmd.index(flag)
    return cmd[idx + 1]


def _flag_values(cmd: List[str], flag: str) -> List[str]:
    return [cmd[i + 1] for i, tok in enumerate(cmd) if tok == flag]


def _make_fake_subprocess_runner(
    *,
    fail_compose_style: Optional[str] = None,
    fail_arrange_target: Optional[tuple[str, str]] = None,
    corrupt_fingerprint_target: Optional[tuple[str, str]] = None,
    empty_wav_target: Optional[tuple[str, str]] = None,
) -> tuple[Callable[..., subprocess.CompletedProcess[str]], List[Dict[str, Any]]]:
    calls: List[Dict[str, Any]] = []
    base_songs = {
        "dark": generate_music(profile="dungeon", seed=101, length="short").pokey_ir,
        "action": generate_music(profile="action", seed=102, length="short").pokey_ir,
        "mystery": generate_music(profile="exploration", seed=103, length="short").pokey_ir,
        "experimental": generate_music(profile="title", seed=104, length="short").pokey_ir,
    }

    def fake_run(
        cmd: List[str],
        *,
        capture_output: bool = False,
        text: bool = False,
        check: bool = False,
        shell: bool = False,
        **kwargs: Any,
    ) -> subprocess.CompletedProcess[str]:
        calls.append({"cmd": list(cmd), "shell": shell})

        if "ai-compose" in cmd:
            out_path = Path(_flag_value(cmd, "-o"))
            style_name = out_path.parent.name
            if fail_compose_style == style_name:
                return subprocess.CompletedProcess(
                    cmd, returncode=1, stdout="", stderr=f"simulated ai-compose error for {style_name}"
                )
            out_path.parent.mkdir(parents=True, exist_ok=True)
            base_songs[style_name].to_json_file(out_path)
            return subprocess.CompletedProcess(cmd, returncode=0, stdout="ok", stderr="")

        if "arrange" in cmd:
            arrange_idx = cmd.index("arrange")
            src_comp = Path(cmd[arrange_idx + 1])
            style_name = src_comp.parent.name
            arr_json = Path(_flag_value(cmd, "--output-json"))
            wav_path = Path(_flag_value(cmd, "--output-wav"))
            xex_path = Path(_flag_value(cmd, "--output-xex"))
            variant_name = arr_json.parent.name

            if fail_arrange_target == (style_name, variant_name):
                return subprocess.CompletedProcess(
                    cmd,
                    returncode=2,
                    stdout="",
                    stderr=f"simulated arrange failure for {style_name}/{variant_name}",
                )

            arr_json.parent.mkdir(parents=True, exist_ok=True)
            src_ir = IRSong.from_json_file(src_comp)
            ch_specs = _flag_values(cmd, "--channel-instrument")
            ch_map = parse_channel_instrument_specs(ch_specs)
            arranged_ir, _ = arrange_ir_song(
                src_ir,
                channel_instruments=ch_map,
                program_change_policy=_flag_value(cmd, "--program-change-policy"),
            )
            if corrupt_fingerprint_target == (style_name, variant_name):
                # Deliberately alter a musical event duration to verify fingerprint mismatch detection.
                for pat in arranged_ir.patterns:
                    for ch_notes in pat.tracks.values():
                        if ch_notes:
                            ch_notes[0].duration = ch_notes[0].duration + 1
                            break
                    else:
                        continue
                    break

            arranged_ir.to_json_file(arr_json)
            if empty_wav_target == (style_name, variant_name):
                wav_path.write_bytes(b"")
            else:
                wav_path.write_bytes(b"RIFF\x24\x00\x00\x00WAVEfmt ")
            xex_path.write_bytes(b"\xff\xff\x00\x60\x01\x60\xea")
            return subprocess.CompletedProcess(cmd, returncode=0, stdout="arranged ok", stderr="")

        raise AssertionError(f"Unexpected subprocess command: {cmd}")

    return fake_run, calls


def test_full_suite_happy_path_mocked_subprocess(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Verify 4 ai-compose + 12 arrange runs, exact CLI flags, paths, no secrets, and identical fingerprints."""
    _clear_ai_env(monkeypatch)
    env_file = _write_env_file(tmp_path / ".env", provider="deepseek", model="deepseek-chat")
    out_dir = tmp_path / "instrument_tests"
    fake_run, calls = _make_fake_subprocess_runner()
    monkeypatch.setattr(subprocess, "run", fake_run)

    rc = suite.main(
        ["--output-dir", str(out_dir), "--seed", "77", "--env-file", str(env_file)]
    )
    assert rc == 0

    captured = capsys.readouterr()
    assert FAKE_SECRET_KEY not in captured.out
    assert FAKE_SECRET_KEY not in captured.err
    assert "compositions=4/4" in captured.out
    assert "arrangements_ok=12/12" in captured.out

    assert len(calls) == 16
    compose_calls = [c for c in calls if "ai-compose" in c["cmd"]]
    arrange_calls = [c for c in calls if "arrange" in c["cmd"]]
    assert len(compose_calls) == 4
    assert len(arrange_calls) == 12

    for call in calls:
        assert call["shell"] is False
        cmd = call["cmd"]
        assert "--output-asm" not in cmd
        assert "mock" not in cmd

    for call in compose_calls:
        cmd = call["cmd"]
        assert "--provider" in cmd
        assert _flag_value(cmd, "--provider") == "deepseek"
        assert "--output-wav" not in cmd
        assert "--output-ir" not in cmd
        assert "--seed" not in cmd

    for call in arrange_calls:
        cmd = call["cmd"]
        assert _flag_value(cmd, "--program-change-policy") == "replace"
        assert len(_flag_values(cmd, "--channel-instrument")) == 4

    manifest_path = out_dir / "manifest.json"
    assert manifest_path.is_file()
    manifest_raw = manifest_path.read_text(encoding="utf-8")
    assert FAKE_SECRET_KEY not in manifest_raw

    manifest = json.loads(manifest_raw)
    assert manifest["summary"] == {
        "compositions_ok": 4,
        "compositions_total": 4,
        "arrangements_ok": 12,
        "arrangements_total": 12,
        "wav_count": 12,
        "xex_count": 12,
        "error_count": 0,
    }
    assert manifest["provider"]["provider"] == "deepseek"
    assert manifest["provider"]["model"] == "deepseek-chat"
    assert manifest["provider"]["api_key_configured"] is True
    assert manifest["base_seed"] == 77
    assert manifest["ai_compose_supports_seed"] is False

    seen_seeds = [entry["seed"] for entry in manifest["compositions"]]
    assert len(set(seen_seeds)) == 4

    for comp in manifest["compositions"]:
        style = comp["style"]
        comp_path = out_dir / style / "composition.json"
        assert comp["status"] == "OK"
        assert Path(comp["composition_json"]) == comp_path
        assert comp_path.is_file()
        src_fp = comp["musical_fingerprint"]
        assert src_fp == composition_musical_fingerprint(IRSong.from_json_file(comp_path))

        assert len(comp["arrangements"]) == 3
        for var in comp["arrangements"]:
            v_name = var["variant"]
            v_dir = out_dir / style / v_name
            assert var["status"] == "OK"
            assert var["fingerprint_matches_source"] is True
            assert var["musical_fingerprint"] == src_fp
            assert Path(var["arrangement_json"]) == v_dir / "arrangement.json"
            assert Path(var["wav_path"]) == v_dir / f"{v_name}.wav"
            assert Path(var["xex_path"]) == v_dir / f"{v_name}.xex"
            assert Path(var["arrangement_json"]).stat().st_size > 0
            assert Path(var["wav_path"]).stat().st_size > 0
            assert Path(var["xex_path"]).stat().st_size > 0


def test_dry_run_executes_no_subprocesses_and_writes_no_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """``--dry-run`` inspects config safely, prints commands, and makes zero changes on disk."""
    _clear_ai_env(monkeypatch)
    env_file = _write_env_file(tmp_path / ".env", provider="openai", model="gpt-4o-mini")
    out_dir = tmp_path / "dry_out"

    def forbid_run(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("subprocess.run must not be called in --dry-run mode")

    monkeypatch.setattr(subprocess, "run", forbid_run)
    rc = suite.main(["--output-dir", str(out_dir), "--dry-run", "--env-file", str(env_file)])
    assert rc == 0
    assert not out_dir.exists()
    out = capsys.readouterr().out
    assert "[DRY-RUN]" in out
    assert FAKE_SECRET_KEY not in out


def test_only_flag_selects_single_style(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """``--only action`` generates 1 composition and 3 arrangements."""
    _clear_ai_env(monkeypatch)
    env_file = _write_env_file(tmp_path / ".env")
    out_dir = tmp_path / "only_action"
    fake_run, calls = _make_fake_subprocess_runner()
    monkeypatch.setattr(subprocess, "run", fake_run)

    rc = suite.main(["--output-dir", str(out_dir), "--only", "action", "--env-file", str(env_file)])
    assert rc == 0
    assert len(calls) == 4
    manifest = json.loads((out_dir / "manifest.json").read_text(encoding="utf-8"))
    assert [c["style"] for c in manifest["compositions"]] == ["action"]
    assert manifest["summary"]["arrangements_ok"] == 3


def test_overwrite_requires_force_flag(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Refuse overwriting existing outputs unless ``--force`` is provided."""
    _clear_ai_env(monkeypatch)
    env_file = _write_env_file(tmp_path / ".env")
    out_dir = tmp_path / "force_check"
    existing = out_dir / "dark" / "composition.json"
    existing.parent.mkdir(parents=True, exist_ok=True)
    existing.write_text('{"marker": "preserve"}\n', encoding="utf-8")

    fake_run, calls = _make_fake_subprocess_runner()
    monkeypatch.setattr(subprocess, "run", fake_run)

    rc_no_force = suite.main(
        ["--output-dir", str(out_dir), "--only", "dark", "--env-file", str(env_file)]
    )
    assert rc_no_force != 0
    assert len(calls) == 0
    assert existing.read_text(encoding="utf-8") == '{"marker": "preserve"}\n'

    rc_force = suite.main(
        ["--output-dir", str(out_dir), "--only", "dark", "--force", "--env-file", str(env_file)]
    )
    assert rc_force == 0
    assert len(calls) == 4


@pytest.mark.parametrize(
    ("provider", "api_key"),
    [
        ("mock", FAKE_SECRET_KEY),
        ("deepseek", ""),
        ("deepseek", "your_api_key_here"),
    ],
)
def test_aborts_upfront_without_real_provider(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    provider: str,
    api_key: str,
) -> None:
    """Mock, placeholder, or missing API keys fail upfront with zero subprocess calls and zero leaks."""
    _clear_ai_env(monkeypatch)
    env_file = _write_env_file(tmp_path / ".env", provider=provider, api_key=api_key)
    out_dir = tmp_path / "should_abort"

    def forbid_run(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("subprocess.run must not be called when provider config is invalid")

    monkeypatch.setattr(subprocess, "run", forbid_run)
    rc = suite.main(["--output-dir", str(out_dir), "--env-file", str(env_file)])
    assert rc != 0
    assert not out_dir.exists()
    captured = capsys.readouterr()
    assert FAKE_SECRET_KEY not in captured.err
    assert FAKE_SECRET_KEY not in captured.out


def test_compose_failure_skips_its_variants_and_continues_other_styles(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """When one ai-compose fails, skip its 3 variants while generating the other 3 styles cleanly."""
    _clear_ai_env(monkeypatch)
    env_file = _write_env_file(tmp_path / ".env")
    out_dir = tmp_path / "compose_fail"
    fake_run, calls = _make_fake_subprocess_runner(fail_compose_style="mystery")
    monkeypatch.setattr(subprocess, "run", fake_run)

    rc = suite.main(["--output-dir", str(out_dir), "--env-file", str(env_file)])
    assert rc != 0
    # 4 compose + 9 arrange (mystery skipped) = 13 calls
    assert len(calls) == 13

    manifest = json.loads((out_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["summary"]["compositions_ok"] == 3
    assert manifest["summary"]["arrangements_ok"] == 9
    assert manifest["summary"]["error_count"] == 1
    by_style = {c["style"]: c for c in manifest["compositions"]}
    assert by_style["mystery"]["status"] == "FAIL"
    assert all(v["status"] == "SKIPPED" for v in by_style["mystery"]["arrangements"])
    assert by_style["dark"]["status"] == "OK"
    assert by_style["action"]["status"] == "OK"
    assert by_style["experimental"]["status"] == "OK"


@pytest.mark.parametrize(
    ("runner_kwargs", "expected_substr"),
    [
        ({"fail_arrange_target": ("action", "variant_b")}, "simulated arrange failure"),
        ({"corrupt_fingerprint_target": ("action", "variant_b")}, "fingerprint mismatch"),
        ({"empty_wav_target": ("action", "variant_b")}, "empty (0 bytes)"),
    ],
)
def test_single_variant_failure_or_fingerprint_mismatch_continues_siblings(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    runner_kwargs: Dict[str, Any],
    expected_substr: str,
) -> None:
    """A single failing, empty, or musically-divergent variant fails cleanly while sibling variants succeed."""
    _clear_ai_env(monkeypatch)
    env_file = _write_env_file(tmp_path / ".env")
    out_dir = tmp_path / "variant_fail"
    fake_run, _ = _make_fake_subprocess_runner(**runner_kwargs)
    monkeypatch.setattr(subprocess, "run", fake_run)

    rc = suite.main(["--output-dir", str(out_dir), "--only", "action", "--env-file", str(env_file)])
    assert rc != 0

    manifest = json.loads((out_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["summary"]["compositions_ok"] == 1
    assert manifest["summary"]["arrangements_ok"] == 2
    assert manifest["summary"]["error_count"] == 1

    variants = {v["variant"]: v for v in manifest["compositions"][0]["arrangements"]}
    assert variants["variant_a"]["status"] == "OK"
    assert variants["variant_b"]["status"] == "FAIL"
    assert expected_substr in (variants["variant_b"]["error"] or "")
    assert variants["variant_c"]["status"] == "OK"

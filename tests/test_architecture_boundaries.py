"""Architectural boundary and CLI integrity guards for CORE modules and tests."""

from __future__ import annotations

import ast
import collections
from pathlib import Path
from typing import Dict, List, Set

import pytest
from click.testing import CliRunner

from atari_music.cli import cli

pytestmark = pytest.mark.core

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_PKG = REPO_ROOT / "src" / "atari_music"
TESTS_DIR = REPO_ROOT / "tests"

CORE_MODULES: Set[str] = {
    "__init__",
    "__main__",
    "cli",
    "api",
    "config",
    "logging_config",
    "constants",
    "player_budget",
    "ir_optimizer",
    "ai/__init__",
    "ai/schema",
    "ai/dsl",
    "ai/prompts",
    "ai/providers/__init__",
    "ai/providers/base",
    "ai/providers/mock",
    "ai/providers/openai",
    "ai/validation",
    "ai/composition",
    "ai/client",
    "ai/analysis",
    "ai/structure_analysis",
    "composer_v4",
    "profiles",
    "arrangement",
    "harmony_engine",
    "rhythm_engine",
    "contour_engine",
    "bass_engine",
    "counterpoint",
    "rhythm_ornament",
    "mutations",
    "music_ir",
    "serialization",
    "ir",
    "pokey_hw",
    "pokey_synth",
    "mads_exporter",
    "xex_layout",
    "sound_profiles/__init__",
    "sound_profiles/bank",
    "sound_profiles/binding",
}


def _imported_atari_music_targets(node: ast.AST) -> List[str]:
    targets: List[str] = []
    if isinstance(node, ast.Import):
        for alias in node.names:
            if alias.name.startswith("atari_music."):
                targets.append(alias.name[len("atari_music."):].replace(".", "/"))
    elif isinstance(node, ast.ImportFrom) and node.module:
        if node.module == "atari_music":
            for alias in node.names:
                targets.append(alias.name)
        elif node.module.startswith("atari_music."):
            targets.append(node.module[len("atari_music."):].replace(".", "/"))
    return targets


def _matches_non_core(target: str, non_core: Set[str]) -> bool:
    return target in non_core or any(target.startswith(f"{nc}/") for nc in non_core)


def test_core_modules_have_no_non_core_imports() -> None:
    """Verify CORE modules do not import LEGACY/EXPERIMENTAL modules.

    Only lazy imports inside hidden legacy/experimental CLI command functions in ``cli.py``
    are allowed so CLI dispatch remains intact without polluting ``CORE`` module loading.
    """
    all_mods = {
        p.relative_to(SRC_PKG).with_suffix("").as_posix()
        for p in SRC_PKG.rglob("*.py")
    }
    assert CORE_MODULES <= all_mods
    non_core = all_mods - CORE_MODULES

    violations: List[str] = []
    for mod in sorted(CORE_MODULES):
        path = SRC_PKG / f"{mod}.py"
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        if mod != "cli":
            for node in ast.walk(tree):
                for target in _imported_atari_music_targets(node):
                    if _matches_non_core(target, non_core):
                        violations.append(f"{mod}.py:{getattr(node, 'lineno', '?')} -> {target}")
        else:
            # cli.py must have ZERO top-level imports of non-core modules, and ZERO non-core
            # imports inside public CORE commands or shared helpers.
            public_core_cli_fns = {
                "_set_log_level",
                "_resolve_profile_binding",
                "_bind_result",
                "_apply_modulation_selection",
                "_apply_instrument_assignments",
                "_assert_xex_expressible",
                "_apply_selections",
                "_export_and_report",
                "cli",
                "compose_cmd",
                "compose_v4_cmd",
                "ai_compose_cmd",
                "import_json_cmd",
                "import_dsl_cmd",
                "build_xex_cmd",
                "export_mads_cmd",
                "analyze_cmd",
            }
            for node in tree.body:
                if isinstance(node, ast.FunctionDef) and node.name not in public_core_cli_fns:
                    # Only hidden legacy/experimental CLI command wrappers may lazy-import non-CORE
                    continue
                for sub in ast.walk(node):
                    for target in _imported_atari_music_targets(sub):
                        if _matches_non_core(target, non_core):
                            violations.append(f"cli.py:{getattr(sub, 'lineno', '?')} -> {target}")

    assert not violations, f"Unexpected CORE -> non-CORE imports: {violations}"


def test_cli_has_no_duplicate_commands_or_definitions() -> None:
    """Verify no shadowed function names or duplicate @cli.command registrations exist in cli.py."""
    cli_path = SRC_PKG / "cli.py"
    tree = ast.parse(cli_path.read_text(encoding="utf-8"), filename=str(cli_path))
    fn_lines: Dict[str, List[int]] = collections.defaultdict(list)
    cmd_lines: Dict[str, List[int]] = collections.defaultdict(list)

    for node in tree.body:
        if isinstance(node, ast.FunctionDef):
            fn_lines[node.name].append(node.lineno)
            for dec in node.decorator_list:
                dec_s = ast.unparse(dec)
                if "command(" in dec_s:
                    cmd_lines[dec_s].append(node.lineno)

    dup_fns = {k: v for k, v in fn_lines.items() if len(v) > 1}
    dup_cmds = {k: v for k, v in cmd_lines.items() if len(v) > 1}
    assert not dup_fns, f"Duplicate top-level functions in cli.py: {dup_fns}"
    assert not dup_cmds, f"Duplicate @cli.command registrations in cli.py: {dup_cmds}"


def test_stage12a_cli_commands_retain_active_options() -> None:
    """Verify deduplicated Stage 12A commands keep their active CLI interface including --seed."""
    runner = CliRunner()
    res_run = runner.invoke(cli, ["run-stage12a", "--help"])
    assert res_run.exit_code == 0, res_run.output
    assert "--reports-dir" in res_run.output

    res_prep = runner.invoke(cli, ["prepare-stage12a-listening", "--help"])
    assert res_prep.exit_code == 0, res_prep.output
    assert "--seed" in res_prep.output


def test_every_test_file_defines_category_markers() -> None:
    """Verify every tests/test_*.py uses module-level pytestmark or full per-test markers."""
    valid_cats = {"core", "experimental", "legacy"}
    missing: List[str] = []
    for path in sorted(TESTS_DIR.glob("test_*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        has_module_cat = any(
            isinstance(node, ast.Assign)
            and any(isinstance(t, ast.Name) and t.id == "pytestmark" for t in node.targets)
            and any(cat in ast.unparse(node.value) for cat in valid_cats)
            for node in tree.body
        )
        if has_module_cat:
            continue
        # Mixed files must decorate every test class or function explicitly
        for node in tree.body:
            if isinstance(node, ast.FunctionDef) and node.name.startswith("test_"):
                decs = " ".join(ast.unparse(d) for d in node.decorator_list)
                if not any(f"mark.{c}" in decs for c in valid_cats):
                    missing.append(f"{path.name}::{node.name}")
            elif isinstance(node, ast.ClassDef) and node.name.startswith("Test"):
                cls_decs = " ".join(ast.unparse(d) for d in node.decorator_list)
                if any(f"mark.{c}" in cls_decs for c in valid_cats):
                    continue
                for m in node.body:
                    if isinstance(m, ast.FunctionDef) and m.name.startswith("test_"):
                        m_decs = " ".join(ast.unparse(d) for d in m.decorator_list)
                        if not any(f"mark.{c}" in m_decs for c in valid_cats):
                            missing.append(f"{path.name}::{node.name}::{m.name}")
    assert not missing, f"Tests missing static category markers: {missing}"

"""Architectural boundary and CLI integrity guards for CORE modules and tests."""

from __future__ import annotations

import ast
import collections
from pathlib import Path
from typing import Dict, List, Mapping, Set

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
    "ai/prompt_library",
    "ai/critique",
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
    "frame_simulator",
    "pokey_hw",
    "pokey_synth",
    "mads_exporter",
    "xex_layout",
    "sound_profiles/__init__",
    "sound_profiles/bank",
    "sound_profiles/binding",
    "instruments/__init__",
    "instruments/models",
    "instruments/catalog",
    "instruments/runtime",
    "instruments/planner",
    "studio/__init__",
    "studio/models",
    "studio/loader",
    "studio/instruments",
    "studio/renderer",
    "studio/ui/__init__",
    "studio/ui/app",
    "studio/ui/worker",
    "studio/ui/channel_strip",
    "studio/ui/instrument_picker",
    "studio/ui/transport_bar",
    "studio/ui/main_window",
}

#: Hidden LEGACY CLI commands (`@cli.command(..., hidden=True)`) permitted to lazy-import
#: legacy pipeline modules inside their command body. Everything else in `cli.py` is audited
#: as CORE unless explicitly listed in ``EXPERIMENTAL_STAGE_CLI_COMMANDS``.
HIDDEN_LEGACY_CLI_COMMANDS: Set[str] = {
    "extract_cmd",
    "reanalyze_raw_cmd",
    "report_cmd",
    "stage3_cmd",
    "mine_archetypes_cmd",
    "generate_song_cmd",
    "run_experiment_cmd",
    "stage4_report_cmd",
    "prepare_listening_test_cmd",
    "stage5_report_cmd",
    "investigate_cmd",
    "compose_v2_cmd",
    "run_v2_experiment_cmd",
    "stage6_report_cmd",
    "prepare_listening_test_v2_cmd",
    "validate_listening_test_v2_cmd",
    "stage6_5_report_cmd",
    "audit_diversity_cmd",
    "compose_v3_cmd",
    "run_composer_v3_experiment_cmd",
    "stage7_report_cmd",
    "prepare_listening_test_v3_cmd",
    "stage7_1_report_cmd",
    "run_composer_v4_experiment_cmd",
    "stage8_report_cmd",
}

#: Explicit research CLI commands (Stages 9C..25) permitted to lazy-import experimental modules.
EXPERIMENTAL_STAGE_CLI_COMMANDS: Set[str] = {
    "prepare_listening_test_9c_cmd",
    "analyze_listening_test_9c_cmd",
    "analyze_listening_test_9d_cmd",
    "analyze_listening_test_9e_cmd",
    "prepare_rebinding_10a_cmd",
    "prepare_volume_contour_10b_cmd",
    "analyze_volume_contour_10b_cmd",
    "synthesize_stage11a_cmd",
    "run_stage11b_cmd",
    "run_stage12a_cmd",
    "prepare_stage12a_listening_cmd",
    "run_stage13a_cmd",
    "prepare_stage13a_listening_cmd",
    "synthesize_stage14_cmd",
    "analyze_stage15_cmd",
    "analyze_stage16_cmd",
    "analyze_stage17_cmd",
    "analyze_stage18_cmd",
    "analyze_stage19_cmd",
    "analyze_stage20_cmd",
    "analyze_stage21_cmd",
    "analyze_stage22_cmd",
    "analyze_stage23_cmd",
    "analyze_stage24_cmd",
    "analyze_stage25_cmd",
}


def _imported_atari_music_targets(node: ast.AST, current_mod: str) -> List[str]:
    """Resolve absolute and relative imports inside *current_mod* to `atari_music`-relative paths."""
    targets: List[str] = []
    if isinstance(node, ast.Import):
        for alias in node.names:
            if alias.name.startswith("atari_music."):
                targets.append(alias.name[len("atari_music."):].replace(".", "/"))
        return targets

    if not isinstance(node, ast.ImportFrom):
        return targets

    if node.level == 0:
        if node.module == "atari_music":
            for alias in node.names:
                if alias.name != "*":
                    targets.append(alias.name)
        elif node.module and node.module.startswith("atari_music."):
            rel_mod = node.module[len("atari_music."):].replace(".", "/")
            targets.append(rel_mod)
            for alias in node.names:
                if alias.name != "*":
                    targets.append(f"{rel_mod}/{alias.name}")
        return targets

    # Relative import (`level >= 1`): resolve against `atari_music` package hierarchy.
    # For both `ai/client` and `ai/__init__`, `__package__` relative to `atari_music` is `["ai"]`.
    pkg_parts = current_mod.split("/")[:-1]
    full_pkg = ["atari_music"] + pkg_parts
    up = node.level - 1
    if up > len(full_pkg):
        return targets

    base_parts = full_pkg[: len(full_pkg) - up]
    target_parts = list(base_parts)
    if node.module:
        target_parts.extend(node.module.split("."))

    if not target_parts or target_parts[0] != "atari_music":
        return targets

    rel_parts = target_parts[1:]
    if rel_parts:
        rel_mod = "/".join(rel_parts)
        targets.append(rel_mod)
        for alias in node.names:
            if alias.name != "*":
                targets.append(f"{rel_mod}/{alias.name}")
    else:
        for alias in node.names:
            if alias.name != "*":
                targets.append(alias.name)

    return targets


def _matches_non_core(target: str, non_core: Set[str]) -> bool:
    return target in non_core or any(target.startswith(f"{nc}/") for nc in non_core)


def _is_cli_command_decorator(dec: ast.expr) -> bool:
    if not isinstance(dec, ast.Call):
        return False
    func = dec.func
    return (
        isinstance(func, ast.Attribute)
        and isinstance(func.value, ast.Name)
        and func.value.id == "cli"
        and func.attr == "command"
    )


def _has_hidden_true_keyword(dec: ast.expr) -> bool:
    if not isinstance(dec, ast.Call):
        return False
    return any(
        kw.arg == "hidden" and isinstance(kw.value, ast.Constant) and kw.value.value is True
        for kw in dec.keywords
    )


def _is_exempt_cli_command(node: ast.FunctionDef) -> bool:
    """Return True only for explicitly registered hidden-legacy or research CLI command functions."""
    cmd_decorators = [d for d in node.decorator_list if _is_cli_command_decorator(d)]
    if not cmd_decorators:
        return False
    if node.name in EXPERIMENTAL_STAGE_CLI_COMMANDS:
        return True
    if node.name in HIDDEN_LEGACY_CLI_COMMANDS:
        return any(_has_hidden_true_keyword(d) for d in cmd_decorators)
    return False


def find_core_import_violations(
    sources_by_mod: Mapping[str, str],
    core_modules: Set[str] = CORE_MODULES,
) -> List[str]:
    """Return boundary violations where any CORE module imports a non-CORE module."""
    all_mods = set(sources_by_mod.keys())
    non_core = all_mods - core_modules
    violations: List[str] = []

    for mod in sorted(core_modules):
        src = sources_by_mod[mod]
        tree = ast.parse(src, filename=f"{mod}.py")
        if mod != "cli":
            for node in ast.walk(tree):
                for target in _imported_atari_music_targets(node, mod):
                    if _matches_non_core(target, non_core):
                        violations.append(f"{mod}.py:{getattr(node, 'lineno', '?')} -> {target}")
        else:
            for node in tree.body:
                if isinstance(node, ast.FunctionDef) and _is_exempt_cli_command(node):
                    continue
                for sub in ast.walk(node):
                    for target in _imported_atari_music_targets(sub, mod):
                        if _matches_non_core(target, non_core):
                            violations.append(f"cli.py:{getattr(sub, 'lineno', '?')} -> {target}")

    return violations


def _load_src_sources() -> Dict[str, str]:
    return {
        p.relative_to(SRC_PKG).with_suffix("").as_posix(): p.read_text(encoding="utf-8")
        for p in SRC_PKG.rglob("*.py")
    }


def test_core_modules_have_no_non_core_imports() -> None:
    """Verify CORE modules do not import LEGACY/EXPERIMENTAL modules via absolute or relative imports."""
    sources = _load_src_sources()
    assert CORE_MODULES <= set(sources.keys())
    violations = find_core_import_violations(sources, CORE_MODULES)
    assert not violations, f"Unexpected CORE -> non-CORE imports: {violations}"


def test_relative_import_legacy_is_detected() -> None:
    """Regression: relative import from CORE submodule to LEGACY module must be flagged."""
    sources = _load_src_sources()
    sources["ai/client"] = "from ..composer_v2 import deduplicate_pokey_patterns\n"
    violations = find_core_import_violations(sources, CORE_MODULES)
    assert any("ai/client.py:1 -> composer_v2" in v for v in violations), violations


def test_relative_import_experimental_is_detected() -> None:
    """Regression: relative import from CORE module to EXPERIMENTAL module must be flagged."""
    sources = _load_src_sources()
    sources["composer_v4"] = "from .stage15 import load_trace\n"
    violations = find_core_import_violations(sources, CORE_MODULES)
    assert any("composer_v4.py:1 -> stage15" in v for v in violations), violations


def test_relative_from_dot_import_module_is_detected() -> None:
    """Regression: `from . import module` and `from .. import module` non-CORE forms must be flagged."""
    sources = _load_src_sources()
    sources["composer_v4"] = "from . import stage15\n"
    sources["sound_profiles/binding"] = "from .. import composer_v2\n"
    violations = find_core_import_violations(sources, CORE_MODULES)
    assert any("composer_v4.py:1 -> stage15" in v for v in violations), violations
    assert any("sound_profiles/binding.py:1 -> composer_v2" in v for v in violations), violations


def test_relative_import_core_produces_no_false_positive() -> None:
    """Regression: valid relative imports between CORE modules must pass cleanly."""
    sources = _load_src_sources()
    sources["ai/client"] = (
        "from . import schema\n"
        "from .schema import AICompositionDoc\n"
        "from ..constants import SCALES\n"
        "from .. import ir_optimizer\n"
    )
    sources["sound_profiles/binding"] = "from . import bank\n"
    violations = find_core_import_violations(sources, CORE_MODULES)
    assert not violations, violations


def test_cli_unlisted_new_function_is_not_exempted() -> None:
    """Regression: any new CLI function or command not explicitly exempted is audited as CORE."""
    sources = _load_src_sources()
    sources["cli"] = (
        "import click\n"
        "cli = click.Group()\n"
        "\n"
        "def new_unlisted_helper() -> None:\n"
        "    from atari_music import stage15\n"
        "\n"
        "@cli.command('new-public-cmd')\n"
        "def new_public_cmd() -> None:\n"
        "    from atari_music.composer_v2 import compose_song_v2\n"
        "\n"
        "@cli.command('new-hidden-unlisted', hidden=True)\n"
        "def new_hidden_unlisted_cmd() -> None:\n"
        "    from . import generator\n"
    )
    violations = find_core_import_violations(sources, CORE_MODULES)
    violating_sites = {v.split(" -> ", 1)[0] for v in violations}
    assert violating_sites == {"cli.py:5", "cli.py:9", "cli.py:13"}, violations
    assert any("stage15" in v for v in violations)
    assert any("composer_v2" in v for v in violations)
    assert any("generator" in v for v in violations)


def test_cli_hidden_legacy_without_hidden_true_is_not_exempted() -> None:
    """Regression: HIDDEN_LEGACY_CLI_COMMANDS without hidden=True must be audited as CORE."""
    sources = _load_src_sources()
    sources["cli"] = (
        "import click\n"
        "cli = click.Group()\n"
        "\n"
        "@cli.command('stage3')\n"
        "def stage3_cmd() -> None:\n"
        "    from atari_music import stage3_reporter\n"
    )
    violations = find_core_import_violations(sources, CORE_MODULES)
    assert any("cli.py:6 -> stage3_reporter" in v for v in violations), violations


def test_instruments_subpackage_relative_imports_guarded() -> None:
    """Regression: relative imports inside instruments CORE subpackage resolve accurately."""
    sources = _load_src_sources()
    sources["instruments/runtime"] = (
        "from . import models\n"
        "from .. import stage15\n"
        "from ..composer_v2 import deduplicate_pokey_patterns\n"
    )
    violations = find_core_import_violations(sources, CORE_MODULES)
    assert any("instruments/runtime.py:2 -> stage15" in v for v in violations), violations
    assert any("instruments/runtime.py:3 -> composer_v2" in v for v in violations), violations
    assert not any("instruments/models" in v for v in violations), violations


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

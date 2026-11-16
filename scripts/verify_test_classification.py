"""Verify completeness and mutual exclusivity of pytest category markers across all tests.

Uses real pytest collection (`--collect-only`) with `addopts` overridden so `@pytest.mark.live`
tests and parametrized cases are included in the audit.
"""

from __future__ import annotations

import argparse
import io
import json
import sys
from collections import Counter
from contextlib import redirect_stdout
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Dict, List, Sequence, Set, Tuple

import pytest

CATEGORY_MARKERS: Tuple[str, ...] = ("core", "experimental", "legacy")


@dataclass(frozen=True)
class ClassificationReport:
    """Summary of real pytest item collection and marker invariants."""

    total_cases: int
    total_defs: int
    cases_by_category: Dict[str, int]
    defs_by_category: Dict[str, int]
    core_offline_cases: int
    core_live_cases: int
    audio_cases: int
    audio_defs: int
    live_cases: int
    missing_category: List[str]
    multiple_categories: Dict[str, List[str]]
    audio_without_core: List[str]

    @property
    def sum_categories_matches_total(self) -> bool:
        return sum(self.cases_by_category.values()) == self.total_cases

    @property
    def ok(self) -> bool:
        return (
            self.total_cases > 0
            and not self.missing_category
            and not self.multiple_categories
            and not self.audio_without_core
            and self.sum_categories_matches_total
        )


class _CollectionAuditor:
    """Pytest plugin recording collected items and their effective markers."""

    def __init__(self) -> None:
        self.items: List[pytest.Item] = []

    def pytest_collection_modifyitems(self, items: List[pytest.Item]) -> None:
        self.items = list(items)


def collect_and_audit(repo_root: Path | None = None) -> ClassificationReport:
    """Run real pytest collection (including `live` tests) and audit marker invariants."""
    root = repo_root or Path(__file__).resolve().parents[1]
    tests_dir = root / "tests"
    auditor = _CollectionAuditor()

    buf = io.StringIO()
    with redirect_stdout(buf):
        exit_code = pytest.main(
            [
                str(tests_dir),
                "--collect-only",
                "-q",
                "-o",
                "addopts=--strict-markers",
                f"--rootdir={root}",
            ],
            plugins=[auditor],
        )
    if exit_code != 0:
        raise RuntimeError(f"pytest collection failed with exit code {exit_code}:\n{buf.getvalue()}")

    cases_by_category: Counter[str] = Counter({k: 0 for k in CATEGORY_MARKERS})
    defs_by_category: Dict[str, Set[str]] = {k: set() for k in CATEGORY_MARKERS}
    all_defs: Set[str] = set()
    audio_defs: Set[str] = set()

    missing_category: List[str] = []
    multiple_categories: Dict[str, List[str]] = {}
    audio_without_core: List[str] = []

    core_offline_cases = 0
    core_live_cases = 0
    audio_cases = 0
    live_cases = 0

    for item in auditor.items:
        nodeid = item.nodeid
        base_def = nodeid.split("[", 1)[0]
        all_defs.add(base_def)

        markers = {mark.name for mark in item.iter_markers()}
        cats = sorted(m for m in markers if m in CATEGORY_MARKERS)

        if not cats:
            missing_category.append(nodeid)
        elif len(cats) > 1:
            multiple_categories[nodeid] = cats
        else:
            cat = cats[0]
            cases_by_category[cat] += 1
            defs_by_category[cat].add(base_def)
            if cat == "core":
                if "live" in markers:
                    core_live_cases += 1
                else:
                    core_offline_cases += 1

        if "live" in markers:
            live_cases += 1

        if "audio" in markers:
            audio_cases += 1
            audio_defs.add(base_def)
            if "core" not in cats:
                audio_without_core.append(nodeid)

    return ClassificationReport(
        total_cases=len(auditor.items),
        total_defs=len(all_defs),
        cases_by_category={k: cases_by_category[k] for k in CATEGORY_MARKERS},
        defs_by_category={k: len(defs_by_category[k]) for k in CATEGORY_MARKERS},
        core_offline_cases=core_offline_cases,
        core_live_cases=core_live_cases,
        audio_cases=audio_cases,
        audio_defs=len(audio_defs),
        live_cases=live_cases,
        missing_category=missing_category,
        multiple_categories=multiple_categories,
        audio_without_core=audio_without_core,
    )


def main(argv: Sequence[str] | None = None) -> int:
    """CLI entrypoint for automated test classification verification."""
    parser = argparse.ArgumentParser(description="Verify pytest category markers across tests/.")
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON report.")
    args = parser.parse_args(argv)

    report = collect_and_audit()
    if args.json:
        payload = asdict(report)
        payload["sum_categories_matches_total"] = report.sum_categories_matches_total
        payload["ok"] = report.ok
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print(f"Total collected pytest cases: {report.total_cases} ({report.total_defs} definitions)")
        for cat in CATEGORY_MARKERS:
            print(
                f"  {cat:12s}: {report.cases_by_category[cat]:4d} cases "
                f"({report.defs_by_category[cat]:4d} defs)"
            )
        print(f"  core offline: {report.core_offline_cases:4d} cases")
        print(f"  core live   : {report.core_live_cases:4d} cases (total live: {report.live_cases})")
        print(f"  audio       : {report.audio_cases:4d} cases ({report.audio_defs:4d} defs)")
        print(f"Sum matches total: {report.sum_categories_matches_total}")
        if report.missing_category:
            print(f"ERROR: Missing category marker ({len(report.missing_category)}):")
            for item in report.missing_category[:20]:
                print(f"  - {item}")
        if report.multiple_categories:
            print(f"ERROR: Multiple category markers ({len(report.multiple_categories)}):")
            for item, cats in list(report.multiple_categories.items())[:20]:
                print(f"  - {item}: {cats}")
        if report.audio_without_core:
            print(f"ERROR: Audio tests missing 'core' marker ({len(report.audio_without_core)}):")
            for item in report.audio_without_core[:20]:
                print(f"  - {item}")
        print(f"Status: {'PASS' if report.ok else 'FAIL'}")

    return 0 if report.ok else 1


if __name__ == "__main__":
    sys.exit(main())

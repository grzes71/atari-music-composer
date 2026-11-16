#!/usr/bin/env python
"""Automated Instrument System Test Suite Generator (AI Composition + Decoupled Arrangement).

Generates a practical validation suite for the Atari Music Composer Instrument System:
1. Generates up to 4 source AI compositions sequentially (``dark``, ``action``,
   ``mystery``, ``experimental``) using the real AI provider configured in ``.env``.
   Each composition is generated ONCE and saved solely as ``composition.json``.
2. Re-arranges each source composition 3 times sequentially (``variant_a``, ``variant_b``,
   ``variant_c``; 12 variants total) via ``atari-music arrange`` with distinct curated
   SSOT POKEY instrument matrices and ``--program-change-policy replace``.
3. Exports ``arrangement.json``, ``<variant>.wav``, and ``<variant>.xex`` for each variant
   (no ``.asm`` files are saved) and verifies file existence, non-zero sizes, and
   identical musical fingerprints (``composition_musical_fingerprint``).
4. Writes a secret-free ``<output_dir>/manifest.json`` summarizing provenance, parameters,
   fingerprints, artifact sizes, and per-step statuses.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass, field
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import sys
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence, Tuple
import warnings

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "src"))

import atari_music  # noqa: E402
from atari_music.api import _load_song_input_for_arrange  # noqa: E402
from atari_music.config import Config, PLACEHOLDER_KEY  # noqa: E402
from atari_music.instruments.planner import composition_musical_fingerprint  # noqa: E402

DEFAULT_OUTPUT_DIR = Path("output/instrument_tests")
DEFAULT_ENV_FILE = Path(".env")
DEFAULT_SEED = 42
PROGRAM_CHANGE_POLICY = "replace"
SUPPORTED_LIVE_PROVIDERS = frozenset({"openai", "deepseek"})
FORBIDDEN_MOCK_PROVIDERS = frozenset({"mock", "offline", "test"})


@dataclass(frozen=True)
class ArrangementVariantSpec:
    """One curated 4-channel POKEY instrument arrangement variant."""

    variant: str
    label: str
    channel_instruments: Dict[int, str]


@dataclass(frozen=True)
class CompositionStyleSpec:
    """Source composition specification and its 3 sound arrangement variants."""

    style: str
    prompt_style: str
    moods: Tuple[str, ...]
    bpm: int
    duration: float
    structure: str
    variants: Tuple[ArrangementVariantSpec, ArrangementVariantSpec, ArrangementVariantSpec]


@dataclass(frozen=True)
class AIProviderMetadata:
    """Non-secret metadata describing the active AI provider configuration."""

    provider: str
    model: str
    env_file: str
    api_key_configured: bool
    provider_source: str
    api_key_source: str
    model_source: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "provider": self.provider,
            "model": self.model,
            "env_file": self.env_file,
            "api_key_configured": self.api_key_configured,
            "provider_source": self.provider_source,
            "api_key_source": self.api_key_source,
            "model_source": self.model_source,
        }


class ProviderConfigError(RuntimeError):
    """Raised when no real non-mock AI provider is properly configured."""


@dataclass
class RunConfig:
    """Normalized execution options for the test suite generator."""

    output_dir: Path = DEFAULT_OUTPUT_DIR
    seed: int = DEFAULT_SEED
    only: Optional[str] = None
    dry_run: bool = False
    force: bool = False
    env_file: Path = DEFAULT_ENV_FILE


#: Canonical 4 styles × 3 verified SSOT instrument matrices (12 total variants).
TEST_SUITE_SPECS: Tuple[CompositionStyleSpec, ...] = (
    CompositionStyleSpec(
        style="dark",
        prompt_style="dark atmospheric dungeon synth on Atari 8-bit POKEY",
        moods=("dark", "brooding", "tense"),
        bpm=96,
        duration=24.0,
        structure="A-B-A",
        variants=(
            ArrangementVariantSpec(
                variant="variant_a",
                label="Deep 15kHz Dungeon",
                channel_instruments={
                    1: "bass_15khz_pure",
                    2: "harmony_soft_square",
                    3: "lead_pure_sustain",
                    4: "perc_kick_tight",
                },
            ),
            ArrangementVariantSpec(
                variant="variant_b",
                label="Gritty Poly4 Assault",
                channel_instruments={
                    1: "bass_poly4_punch",
                    2: "harmony_soft_square",
                    3: "lead_attack_bite",
                    4: "perc_snare_crisp",
                },
            ),
            ArrangementVariantSpec(
                variant="variant_c",
                label="Hollow Sub & Tom Pulse",
                channel_instruments={
                    1: "bass_15khz_pure",
                    2: "lead_pure_sustain",
                    3: "lead_attack_bite",
                    4: "perc_tom_pitched",
                },
            ),
        ),
    ),
    CompositionStyleSpec(
        style="action",
        prompt_style="fast energetic arcade action game theme on Atari 8-bit POKEY",
        moods=("energetic", "heroic", "driving"),
        bpm=144,
        duration=24.0,
        structure="A-B-A",
        variants=(
            ArrangementVariantSpec(
                variant="variant_a",
                label="Arcade Drive Punch",
                channel_instruments={
                    1: "bass_poly4_punch",
                    2: "harmony_soft_square",
                    3: "lead_attack_bite",
                    4: "perc_kick_tight",
                },
            ),
            ArrangementVariantSpec(
                variant="variant_b",
                label="15kHz Turbo Lead",
                channel_instruments={
                    1: "bass_15khz_pure",
                    2: "lead_attack_bite",
                    3: "lead_pure_sustain",
                    4: "perc_tom_pitched",
                },
            ),
            ArrangementVariantSpec(
                variant="variant_c",
                label="Crisp Hi-Hat Runner",
                channel_instruments={
                    1: "bass_poly4_punch",
                    2: "lead_pure_sustain",
                    3: "harmony_soft_square",
                    4: "perc_hihat_closed",
                },
            ),
        ),
    ),
    CompositionStyleSpec(
        style="mystery",
        prompt_style="mysterious exploration theme with sparse hypnotic motifs on Atari 8-bit POKEY",
        moods=("mysterious", "curious", "suspenseful"),
        bpm=108,
        duration=24.0,
        structure="A-B-A",
        variants=(
            ArrangementVariantSpec(
                variant="variant_a",
                label="Shimmering Shadow",
                channel_instruments={
                    1: "bass_15khz_pure",
                    2: "harmony_soft_square",
                    3: "lead_pure_sustain",
                    4: "perc_hihat_closed",
                },
            ),
            ArrangementVariantSpec(
                variant="variant_b",
                label="Poly4 & Pitched Tom",
                channel_instruments={
                    1: "bass_poly4_punch",
                    2: "harmony_soft_square",
                    3: "lead_pure_sustain",
                    4: "perc_tom_pitched",
                },
            ),
            ArrangementVariantSpec(
                variant="variant_c",
                label="Warm Pad Inversion",
                channel_instruments={
                    1: "bass_15khz_pure",
                    2: "lead_pure_sustain",
                    3: "harmony_soft_square",
                    4: "perc_snare_crisp",
                },
            ),
        ),
    ),
    CompositionStyleSpec(
        style="experimental",
        prompt_style="experimental algorithmic chiptune exploring contrasting rhythms and timbres on Atari 8-bit POKEY",
        moods=("experimental", "quirky", "unconventional"),
        bpm=128,
        duration=24.0,
        structure="A-B-A",
        variants=(
            ArrangementVariantSpec(
                variant="variant_a",
                label="Cybernetic Bite",
                channel_instruments={
                    1: "bass_poly4_punch",
                    2: "harmony_soft_square",
                    3: "lead_attack_bite",
                    4: "perc_snare_crisp",
                },
            ),
            ArrangementVariantSpec(
                variant="variant_b",
                label="Dual Lead 15kHz Toms",
                channel_instruments={
                    1: "bass_15khz_pure",
                    2: "lead_attack_bite",
                    3: "lead_pure_sustain",
                    4: "perc_tom_pitched",
                },
            ),
            ArrangementVariantSpec(
                variant="variant_c",
                label="Inverted Square Kick",
                channel_instruments={
                    1: "bass_poly4_punch",
                    2: "lead_pure_sustain",
                    3: "harmony_soft_square",
                    4: "perc_kick_tight",
                },
            ),
        ),
    ),
)

VALID_STYLES: Tuple[str, ...] = tuple(spec.style for spec in TEST_SUITE_SPECS)


def derive_style_seed(base_seed: int, style_index: int) -> int:
    """Derive a deterministic per-style seed from the base seed."""
    return int(base_seed) + (int(style_index) * 101)


def resolve_cli_prefix(python_executable: Optional[str] = None) -> List[str]:
    """Return the argv prefix used to invoke the ``atari-music`` CLI."""
    exe = python_executable or sys.executable
    return [exe, "-m", "atari_music"]


def inspect_real_ai_provider(env_file: Path = DEFAULT_ENV_FILE) -> AIProviderMetadata:
    """Validate that a real non-mock AI provider and key are configured without exposing secrets."""
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", UserWarning)
        cfg = Config.from_args(args=[], env_path=env_file, validate=False)

    provider = (cfg.ai_provider or "").strip().lower()
    model = (cfg.ai_model or "").strip() or "(default)"
    api_key = (cfg.ai_api_key or "").strip()
    env_label = str(env_file)

    if provider in FORBIDDEN_MOCK_PROVIDERS:
        raise ProviderConfigError(
            f"AI_PROVIDER='{provider}' is not allowed: this suite requires a real AI provider "
            f"({', '.join(sorted(SUPPORTED_LIVE_PROVIDERS))}) configured in {env_label}."
        )
    if provider not in SUPPORTED_LIVE_PROVIDERS:
        raise ProviderConfigError(
            f"Unsupported AI_PROVIDER='{provider}' for real composition generation. "
            f"Expected one of: {', '.join(sorted(SUPPORTED_LIVE_PROVIDERS))}."
        )
    if not api_key or api_key == PLACEHOLDER_KEY:
        raise ProviderConfigError(
            f"Missing valid AI_API_KEY in {env_label} or environment for provider '{provider}'. "
            "Configure AI_API_KEY before running this script."
        )

    return AIProviderMetadata(
        provider=provider,
        model=model,
        env_file=env_label,
        api_key_configured=True,
        provider_source=cfg.sources.get("AI_PROVIDER", "unknown"),
        api_key_source=cfg.sources.get("AI_API_KEY", "unknown"),
        model_source=cfg.sources.get("AI_MODEL", "unknown"),
    )


def select_style_specs(only: Optional[str]) -> List[CompositionStyleSpec]:
    """Select either all 4 style specs or the single style requested via ``--only``."""
    if only is None:
        return list(TEST_SUITE_SPECS)
    normalized = only.strip().lower()
    matched = [spec for spec in TEST_SUITE_SPECS if spec.style == normalized]
    if not matched:
        raise ValueError(f"Unknown style '{only}'. Valid styles: {', '.join(VALID_STYLES)}")
    return matched


def build_ai_compose_command(
    spec: CompositionStyleSpec,
    composition_json: Path,
    provider_meta: Optional[AIProviderMetadata],
    env_file: Path,
    cli_prefix: Sequence[str],
) -> List[str]:
    """Build the ``atari-music ai-compose`` command saving only ``composition.json``."""
    cmd: List[str] = [
        *cli_prefix,
        "ai-compose",
        "--style",
        spec.prompt_style,
    ]
    for mood_word in spec.moods:
        cmd.extend(["--mood", mood_word])
    cmd.extend(
        [
            "--duration",
            str(spec.duration),
            "--bpm",
            str(spec.bpm),
            "--channels",
            "4",
            "--structure",
            spec.structure,
            "--format",
            "json",
            "--use-instrument-catalog",
        ]
    )
    if provider_meta is not None:
        cmd.extend(["--provider", provider_meta.provider])
        if provider_meta.model and provider_meta.model != "(default)":
            cmd.extend(["--model", provider_meta.model])
    if env_file.exists() and env_file.is_file():
        cmd.extend(["--env-file", str(env_file)])
    cmd.extend(["-o", str(composition_json)])
    return cmd


def build_arrange_command(
    composition_json: Path,
    variant_spec: ArrangementVariantSpec,
    arrangement_json: Path,
    wav_path: Path,
    xex_path: Path,
    cli_prefix: Sequence[str],
) -> List[str]:
    """Build the ``atari-music arrange`` command outputting JSON, WAV, and XEX (no ASM)."""
    cmd: List[str] = [*cli_prefix, "arrange", str(composition_json)]
    for ch in sorted(variant_spec.channel_instruments):
        cmd.extend(["--channel-instrument", f"{ch}={variant_spec.channel_instruments[ch]}"])
    cmd.extend(
        [
            "--program-change-policy",
            PROGRAM_CHANGE_POLICY,
            "--output-json",
            str(arrangement_json),
            "--output-wav",
            str(wav_path),
            "--output-xex",
            str(xex_path),
        ]
    )
    return cmd


def _collect_existing_targets(output_dir: Path, specs: Sequence[CompositionStyleSpec]) -> List[Path]:
    """Return any target output artifacts that already exist on disk."""
    existing: List[Path] = []
    manifest_path = output_dir / "manifest.json"
    if manifest_path.exists():
        existing.append(manifest_path)
    for spec in specs:
        style_dir = output_dir / spec.style
        comp_path = style_dir / "composition.json"
        if comp_path.exists():
            existing.append(comp_path)
        for v_spec in spec.variants:
            v_dir = style_dir / v_spec.variant
            for artifact in (
                v_dir / "arrangement.json",
                v_dir / f"{v_spec.variant}.wav",
                v_dir / f"{v_spec.variant}.xex",
            ):
                if artifact.exists():
                    existing.append(artifact)
    return existing


def _read_git_commit() -> Optional[str]:
    """Best-effort lookup of the current short git commit SHA without spawning a subprocess."""
    git_dir = REPO_ROOT / ".git"
    head_path = git_dir / "HEAD"
    if not head_path.is_file():
        return None
    head_text = head_path.read_text(encoding="utf-8").strip()
    if head_text.startswith("ref: "):
        ref_rel = head_text[5:].strip()
        ref_path = git_dir / ref_rel
        if ref_path.is_file():
            sha = ref_path.read_text(encoding="utf-8").strip()
            return sha[:7] if sha else None
        packed = git_dir / "packed-refs"
        if packed.is_file():
            for line in packed.read_text(encoding="utf-8").splitlines():
                if line.startswith("#") or line.startswith("^") or not line.strip():
                    continue
                parts = line.split()
                if len(parts) == 2 and parts[1] == ref_rel:
                    return parts[0][:7]
        return None
    return head_text[:7] if len(head_text) >= 7 else (head_text or None)


def _verify_nonempty_file(path: Path) -> Tuple[bool, int, Optional[str]]:
    """Verify that *path* exists as a regular non-empty file."""
    if not path.exists():
        return False, 0, f"missing expected output file: {path}"
    if not path.is_file():
        return False, 0, f"expected file path is not a regular file: {path}"
    size = path.stat().st_size
    if size <= 0:
        return False, 0, f"expected output file is empty (0 bytes): {path}"
    return True, size, None


def _compute_song_fingerprint(song_path: Path) -> str:
    """Compute ``composition_musical_fingerprint`` from an AI composition or POKEY IR JSON."""
    ir_song, _, _ = _load_song_input_for_arrange(song_path)
    return composition_musical_fingerprint(ir_song)


def _format_subprocess_error(step_name: str, proc: subprocess.CompletedProcess[str]) -> str:
    """Format a bounded diagnostic message from a failed subprocess result."""
    detail = (proc.stderr or proc.stdout or "").strip()
    if len(detail) > 500:
        detail = detail[:500] + "..."
    return f"{step_name} failed with exit code {proc.returncode}" + (f": {detail}" if detail else "")


def run_test_suite(
    config: RunConfig,
    *,
    runner: Optional[Callable[..., subprocess.CompletedProcess[str]]] = None,
    cli_prefix: Optional[Sequence[str]] = None,
) -> Dict[str, Any]:
    """Execute (or dry-run) the 4-style × 3-variant test suite generation pipeline."""
    active_runner = runner if runner is not None else subprocess.run
    specs = select_style_specs(config.only)
    resolved_cli = list(cli_prefix) if cli_prefix is not None else resolve_cli_prefix()

    provider_meta: Optional[AIProviderMetadata] = None
    provider_error: Optional[str] = None
    try:
        provider_meta = inspect_real_ai_provider(config.env_file)
    except ProviderConfigError as exc:
        provider_error = str(exc)
        if not config.dry_run:
            raise

    existing_targets = _collect_existing_targets(config.output_dir, specs)
    if existing_targets and not config.force and not config.dry_run:
        sample = ", ".join(str(p) for p in existing_targets[:3])
        more = f" (+{len(existing_targets) - 3} more)" if len(existing_targets) > 3 else ""
        raise FileExistsError(
            f"Refusing to overwrite existing test suite artifacts ({sample}{more}). "
            "Pass --force to overwrite or choose a different --output-dir."
        )

    plan_entries: List[Dict[str, Any]] = []
    for idx, spec in enumerate(specs):
        style_seed = derive_style_seed(config.seed, idx)
        style_dir = config.output_dir / spec.style
        comp_json = style_dir / "composition.json"
        ai_cmd = build_ai_compose_command(spec, comp_json, provider_meta, config.env_file, resolved_cli)
        variant_plans: List[Dict[str, Any]] = []
        for v_spec in spec.variants:
            v_dir = style_dir / v_spec.variant
            arr_json = v_dir / "arrangement.json"
            wav_path = v_dir / f"{v_spec.variant}.wav"
            xex_path = v_dir / f"{v_spec.variant}.xex"
            arr_cmd = build_arrange_command(comp_json, v_spec, arr_json, wav_path, xex_path, resolved_cli)
            variant_plans.append(
                {
                    "variant": v_spec.variant,
                    "label": v_spec.label,
                    "channel_instruments": {str(k): v for k, v in v_spec.channel_instruments.items()},
                    "arrangement_json": str(arr_json),
                    "wav_path": str(wav_path),
                    "xex_path": str(xex_path),
                    "command": arr_cmd,
                }
            )
        plan_entries.append(
            {
                "style": spec.style,
                "seed": style_seed,
                "composition_json": str(comp_json),
                "command": ai_cmd,
                "variants": variant_plans,
            }
        )

    if config.dry_run:
        return {
            "dry_run": True,
            "output_dir": str(config.output_dir),
            "manifest_path": str(config.output_dir / "manifest.json"),
            "base_seed": config.seed,
            "ai_compose_supports_seed": False,
            "program_change_policy": PROGRAM_CHANGE_POLICY,
            "only_style": config.only,
            "force": config.force,
            "existing_targets_detected": len(existing_targets),
            "provider_ready": provider_meta is not None,
            "provider": provider_meta.to_dict() if provider_meta is not None else None,
            "provider_warning": provider_error,
            "plan": plan_entries,
        }

    assert provider_meta is not None
    config.output_dir.mkdir(parents=True, exist_ok=True)

    manifest_compositions: List[Dict[str, Any]] = []
    errors: List[Dict[str, Any]] = []
    compositions_ok = 0
    arrangements_ok = 0
    arrangements_total = 0
    wav_count = 0
    xex_count = 0

    for idx, spec in enumerate(specs):
        style_seed = derive_style_seed(config.seed, idx)
        style_dir = config.output_dir / spec.style
        style_dir.mkdir(parents=True, exist_ok=True)
        comp_json = style_dir / "composition.json"
        ai_cmd = build_ai_compose_command(spec, comp_json, provider_meta, config.env_file, resolved_cli)

        comp_status = "FAIL"
        comp_size = 0
        source_fp: Optional[str] = None
        comp_error: Optional[str] = None

        try:
            proc = active_runner(ai_cmd, capture_output=True, text=True, check=False, shell=False)
            if proc.returncode != 0:
                comp_error = _format_subprocess_error(f"ai-compose[{spec.style}]", proc)
            else:
                ok_file, comp_size, file_err = _verify_nonempty_file(comp_json)
                if not ok_file:
                    comp_error = file_err
                else:
                    source_fp = _compute_song_fingerprint(comp_json)
                    comp_status = "OK"
                    compositions_ok += 1
        except Exception as exc:  # pragma: no cover - defensive boundary
            comp_error = f"ai-compose[{spec.style}] raised exception: {exc}"

        if comp_error is not None:
            errors.append({"stage": "ai-compose", "style": spec.style, "error": comp_error})

        variant_records: List[Dict[str, Any]] = []
        for v_spec in spec.variants:
            arrangements_total += 1
            v_dir = style_dir / v_spec.variant
            arr_json = v_dir / "arrangement.json"
            wav_path = v_dir / f"{v_spec.variant}.wav"
            xex_path = v_dir / f"{v_spec.variant}.xex"
            arr_cmd = build_arrange_command(comp_json, v_spec, arr_json, wav_path, xex_path, resolved_cli)

            if comp_status != "OK":
                skip_reason = f"skipped because source composition '{spec.style}' failed"
                variant_records.append(
                    {
                        "variant": v_spec.variant,
                        "label": v_spec.label,
                        "channel_instruments": {str(k): v for k, v in v_spec.channel_instruments.items()},
                        "program_change_policy": PROGRAM_CHANGE_POLICY,
                        "status": "SKIPPED",
                        "arrangement_json": str(arr_json),
                        "arrangement_json_size_bytes": 0,
                        "wav_path": str(wav_path),
                        "wav_size_bytes": 0,
                        "xex_path": str(xex_path),
                        "xex_size_bytes": 0,
                        "musical_fingerprint": None,
                        "fingerprint_matches_source": False,
                        "command": arr_cmd,
                        "error": skip_reason,
                    }
                )
                continue

            v_dir.mkdir(parents=True, exist_ok=True)
            v_status = "FAIL"
            arr_size = 0
            wav_size = 0
            xex_size = 0
            variant_fp: Optional[str] = None
            fp_matches = False
            v_error: Optional[str] = None

            try:
                proc = active_runner(arr_cmd, capture_output=True, text=True, check=False, shell=False)
                if proc.returncode != 0:
                    v_error = _format_subprocess_error(f"arrange[{spec.style}/{v_spec.variant}]", proc)
                else:
                    ok_arr, arr_size, err_arr = _verify_nonempty_file(arr_json)
                    ok_wav, wav_size, err_wav = _verify_nonempty_file(wav_path)
                    ok_xex, xex_size, err_xex = _verify_nonempty_file(xex_path)
                    if ok_wav:
                        wav_count += 1
                    if ok_xex:
                        xex_count += 1
                    missing_errs = [e for e in (err_arr, err_wav, err_xex) if e is not None]
                    if missing_errs:
                        v_error = "; ".join(missing_errs)
                    else:
                        variant_fp = _compute_song_fingerprint(arr_json)
                        fp_matches = variant_fp == source_fp
                        if not fp_matches:
                            v_error = (
                                f"musical fingerprint mismatch for {spec.style}/{v_spec.variant}: "
                                f"source={source_fp}, arranged={variant_fp}"
                            )
                        else:
                            v_status = "OK"
                            arrangements_ok += 1
            except Exception as exc:  # pragma: no cover - defensive boundary
                v_error = f"arrange[{spec.style}/{v_spec.variant}] raised exception: {exc}"

            if v_error is not None:
                errors.append(
                    {
                        "stage": "arrange",
                        "style": spec.style,
                        "variant": v_spec.variant,
                        "error": v_error,
                    }
                )

            variant_records.append(
                {
                    "variant": v_spec.variant,
                    "label": v_spec.label,
                    "channel_instruments": {str(k): v for k, v in v_spec.channel_instruments.items()},
                    "program_change_policy": PROGRAM_CHANGE_POLICY,
                    "status": v_status,
                    "arrangement_json": str(arr_json),
                    "arrangement_json_size_bytes": arr_size,
                    "wav_path": str(wav_path),
                    "wav_size_bytes": wav_size,
                    "xex_path": str(xex_path),
                    "xex_size_bytes": xex_size,
                    "musical_fingerprint": variant_fp,
                    "fingerprint_matches_source": fp_matches,
                    "command": arr_cmd,
                    "error": v_error,
                }
            )

        manifest_compositions.append(
            {
                "style": spec.style,
                "prompt_style": spec.prompt_style,
                "moods": list(spec.moods),
                "bpm": spec.bpm,
                "duration": spec.duration,
                "structure": spec.structure,
                "seed": style_seed,
                "status": comp_status,
                "composition_json": str(comp_json),
                "size_bytes": comp_size,
                "musical_fingerprint": source_fp,
                "command": ai_cmd,
                "error": comp_error,
                "arrangements": variant_records,
            }
        )

    manifest_path = config.output_dir / "manifest.json"
    manifest: Dict[str, Any] = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "app_version": getattr(atari_music, "__version__", "unknown"),
        "git_commit": _read_git_commit(),
        "provider": provider_meta.to_dict(),
        "base_seed": config.seed,
        "ai_compose_supports_seed": False,
        "program_change_policy": PROGRAM_CHANGE_POLICY,
        "output_dir": str(config.output_dir),
        "only_style": config.only,
        "compositions": manifest_compositions,
        "summary": {
            "compositions_ok": compositions_ok,
            "compositions_total": len(specs),
            "arrangements_ok": arrangements_ok,
            "arrangements_total": arrangements_total,
            "wav_count": wav_count,
            "xex_count": xex_count,
            "error_count": len(errors),
        },
        "errors": errors,
        "manifest_path": str(manifest_path),
    }
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return manifest


def parse_args(argv: Optional[Sequence[str]] = None) -> RunConfig:
    """Parse CLI arguments for the automated instrument test suite generator."""
    parser = argparse.ArgumentParser(
        description=(
            "Generate 4 AI source compositions once each and re-arrange each into 3 POKEY "
            "sound variants (WAV + XEX + arranged JSON) with musical fingerprint verification."
        )
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help=f"Output root directory (default: {DEFAULT_OUTPUT_DIR})",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=DEFAULT_SEED,
        help=(
            "Base seed recorded in manifest (per-style seeds are deterministically derived; "
            "note: current ai-compose CLI has no --seed flag)"
        ),
    )
    parser.add_argument(
        "--only",
        choices=list(VALID_STYLES),
        default=None,
        help="Run only one style instead of all 4 styles",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print planned commands and layout without executing subprocesses or writing files",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Allow overwriting existing files in --output-dir",
    )
    parser.add_argument(
        "--env-file",
        type=Path,
        default=DEFAULT_ENV_FILE,
        help=f"Path to .env configuration file (default: {DEFAULT_ENV_FILE})",
    )
    ns = parser.parse_args(argv)
    return RunConfig(
        output_dir=ns.output_dir,
        seed=ns.seed,
        only=ns.only,
        dry_run=ns.dry_run,
        force=ns.force,
        env_file=ns.env_file,
    )


def _print_dry_run_summary(report: Mapping[str, Any]) -> None:
    print(f"[DRY-RUN] output_dir={report['output_dir']} base_seed={report['base_seed']}")
    if report["provider"] is not None:
        p = report["provider"]
        print(f"[DRY-RUN] provider={p['provider']} model={p['model']} api_key_configured={p['api_key_configured']}")
    else:
        print(f"[DRY-RUN] provider_ready=False warning={report['provider_warning']}")
    for entry in report["plan"]:
        print(f"[DRY-RUN] STYLE {entry['style']} (seed={entry['seed']}): {' '.join(entry['command'])}")
        for var in entry["variants"]:
            print(f"[DRY-RUN]   VARIANT {var['variant']}: {' '.join(var['command'])}")


def _print_run_summary(manifest: Mapping[str, Any]) -> None:
    s = manifest["summary"]
    print(
        f"Summary: compositions={s['compositions_ok']}/{s['compositions_total']}, "
        f"arrangements_ok={s['arrangements_ok']}/{s['arrangements_total']}, "
        f"wav_count={s['wav_count']}, xex_count={s['xex_count']}, "
        f"errors={s['error_count']}, manifest_path={manifest['manifest_path']}"
    )


def main(argv: Optional[Sequence[str]] = None) -> int:
    """CLI entrypoint returning 0 on complete success and non-zero on errors."""
    try:
        config = parse_args(argv)
        result = run_test_suite(config)
    except (ProviderConfigError, FileExistsError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    if result.get("dry_run"):
        _print_dry_run_summary(result)
        return 0

    _print_run_summary(result)
    return 0 if result["summary"]["error_count"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())

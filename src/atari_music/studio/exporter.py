"""Headless XEX export, toolchain preflight, and transactional commit service (PySide6-free)."""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import shutil
import tempfile
from typing import List, Optional, Tuple

from atari_music.api import MusicGenerationResult, arrange_song
from atari_music.instruments.planner import InstrumentPlanError
from atari_music.instruments.runtime import RuntimeDiagnostic
from atari_music.ir import resolve_audctl_mode
from atari_music.studio.instruments import InstrumentService
from atari_music.studio.models import (
    LoadedCompositionState,
    StudioArrangementConfig,
    ToolchainPaths,
    XexExportOptions,
    XexExportResult,
)
from atari_music.xex_layout import assign_roles, parse_xex

_SRC_PKG = Path(__file__).resolve().parents[1]
_REPO_ROOT = _SRC_PKG.parents[1]


def resolve_default_mads_path() -> Optional[Path]:
    """Locate bundled ``tools/mads/mads.exe`` or ``mads`` on ``PATH``."""
    bundled = _REPO_ROOT / "tools" / "mads" / "mads.exe"
    if bundled.is_file():
        return bundled
    for candidate_name in ("mads", "mads.exe"):
        found = shutil.which(candidate_name)
        if found:
            p = Path(found)
            if p.is_file():
                return p
    return None


def resolve_default_player_asm() -> Optional[Path]:
    """Locate ``player.asm`` matching ``build_xex_from_result`` search precedence."""
    for candidate in (
        Path.cwd() / "player.asm",
        _REPO_ROOT / "player.asm",
        _SRC_PKG / "asm" / "player.asm",
    ):
        if candidate.is_file():
            return candidate.resolve()
    return None


def _is_usable_executable(path: Path) -> bool:
    if not path.is_file():
        return False
    if os.name == "nt":
        return path.stat().st_size > 0
    return os.access(path, os.X_OK)


@dataclass(frozen=True)
class PreparedXexArrangement:
    """Single source-of-truth arranged IR and XEX validation result for one export."""

    config: StudioArrangementConfig
    arranged_result: Optional[MusicGenerationResult]
    effective_format_version: Optional[int]
    effective_uses_16bit_bass: bool
    effective_audctl: int
    resolved_target_backend: Optional[str]
    diagnostics: Tuple[RuntimeDiagnostic, ...]
    blocking_errors: Tuple[str, ...]
    warnings: Tuple[str, ...]

    @property
    def is_exportable(self) -> bool:
        return (
            self.arranged_result is not None
            and self.effective_format_version in (1, 2)
            and len(self.blocking_errors) == 0
        )


def _commit_staged_pairs(
    commit_pairs: List[Tuple[Path, Path]],
    stage_dir: Path,
) -> None:
    """Atomically replace staged artifacts onto destinations on the same volume with rollback.

    ``stage_dir`` must live under ``output_path.parent`` so all ``os.replace`` operations stay
    on the same filesystem. Any failure backs out newly placed destinations and restores
    pre-existing backups so targets are never left in a half-updated state.
    """
    backups: List[Tuple[Path, Path]] = []
    committed_new: List[Path] = []
    try:
        for idx, (_src, dst) in enumerate(commit_pairs):
            if dst.exists():
                bak = stage_dir / f".bak_{idx}_{dst.name}"
                os.replace(dst, bak)
                backups.append((dst, bak))

        backup_targets = {dst for dst, _ in backups}
        for src, dst in commit_pairs:
            os.replace(src, dst)
            if dst not in backup_targets:
                committed_new.append(dst)
    except Exception:
        for new_dst in reversed(committed_new):
            try:
                new_dst.unlink(missing_ok=True)
            except OSError:
                pass
        for orig_dst, bak_path in reversed(backups):
            try:
                if bak_path.exists():
                    os.replace(bak_path, orig_dst)
            except OSError:
                pass
        raise


class ExportService:
    """Orchestrates Studio XEX preparation, toolchain preflight, and safe MADS export."""

    def __init__(self, instrument_service: InstrumentService) -> None:
        self._instrument_service = instrument_service

    @staticmethod
    def preflight_toolchain(
        mads_bin: Optional[Path] = None,
        player_asm: Optional[Path] = None,
    ) -> ToolchainPaths:
        """Resolve and verify MADS assembler executable and ``player.asm`` without building."""
        mads_err: Optional[str] = None
        resolved_mads: Optional[Path] = None
        if mads_bin is not None:
            cand = Path(mads_bin)
            if not cand.exists():
                mads_err = f"MADS executable not found: {cand}"
            elif not _is_usable_executable(cand):
                mads_err = f"MADS path is not a usable executable file: {cand}"
            else:
                resolved_mads = cand
        else:
            auto_mads = resolve_default_mads_path()
            if auto_mads is None:
                mads_err = (
                    "MADS executable not found (checked tools/mads/mads.exe and system PATH). "
                    "Select a MADS binary explicitly."
                )
            elif not _is_usable_executable(auto_mads):
                mads_err = f"Detected MADS binary is not executable: {auto_mads}"
            else:
                resolved_mads = auto_mads

        asm_err: Optional[str] = None
        resolved_asm: Optional[Path] = None
        if player_asm is not None:
            cand_asm = Path(player_asm)
            if not cand_asm.is_file():
                asm_err = f"player.asm not found: {cand_asm}"
            else:
                resolved_asm = cand_asm.resolve()
        else:
            auto_asm = resolve_default_player_asm()
            if auto_asm is None:
                asm_err = (
                    "player.asm not found in current directory, repository root, or package data. "
                    "Select player.asm explicitly."
                )
            else:
                resolved_asm = auto_asm

        return ToolchainPaths(
            mads_bin=resolved_mads,
            player_asm=resolved_asm,
            mads_error=mads_err,
            player_asm_error=asm_err,
        )

    def prepare_xex_export(
        self,
        state: LoadedCompositionState,
        config: StudioArrangementConfig,
    ) -> PreparedXexArrangement:
        """Produce ONE arranged ``MusicGenerationResult`` and validate it for XEX export."""
        try:
            arranged_result = arrange_song(
                state.base_pokey_ir,
                channel_instruments=config.assigned_map() or None,
                program_change_policy=config.program_change_policy,
                instrument_catalog_path=self._instrument_service.catalog_path,
                player_version=config.player_version,
            )
        except InstrumentPlanError as exc:
            return PreparedXexArrangement(
                config=config,
                arranged_result=None,
                effective_format_version=None,
                effective_uses_16bit_bass=state.base_uses_16bit_bass,
                effective_audctl=resolve_audctl_mode(state.base_pokey_ir),
                resolved_target_backend=None,
                diagnostics=exc.diagnostics,
                blocking_errors=(str(exc),),
                warnings=(),
            )

        (
            effective_ver,
            resolved_target,
            diagnostics,
            blocking_errors,
            warnings,
        ) = self._instrument_service.validate_arranged_ir_for_xex(
            state, config, arranged_result.pokey_ir
        )

        return PreparedXexArrangement(
            config=config,
            arranged_result=arranged_result,
            effective_format_version=effective_ver,
            effective_uses_16bit_bass=bool(arranged_result.pokey_ir.uses_16bit_bass),
            effective_audctl=resolve_audctl_mode(arranged_result.pokey_ir),
            resolved_target_backend=resolved_target.backend,
            diagnostics=diagnostics,
            blocking_errors=blocking_errors,
            warnings=warnings,
        )

    def export_prepared_xex(
        self,
        prepared: PreparedXexArrangement,
        options: XexExportOptions,
    ) -> XexExportResult:
        """Compile and atomically commit *prepared* to XEX (+ optional ASM) on disk."""
        if not prepared.is_exportable or prepared.arranged_result is None or prepared.effective_format_version is None:
            reasons = "; ".join(prepared.blocking_errors) or "Current arrangement is not valid for XEX export."
            raise ValueError(f"Cannot export XEX: {reasons}")

        toolchain = self.preflight_toolchain(
            mads_bin=options.mads_bin,
            player_asm=options.player_asm,
        )
        if not toolchain.is_ready or toolchain.mads_bin is None or toolchain.player_asm is None:
            problems = [e for e in (toolchain.mads_error, toolchain.player_asm_error) if e]
            raise FileNotFoundError("; ".join(problems))

        output_path = Path(options.output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        eff_ver = prepared.effective_format_version

        with tempfile.TemporaryDirectory(
            dir=output_path.parent,
            prefix=f".{output_path.stem}_xexstage_",
        ) as tmp_str:
            stage_dir = Path(tmp_str)
            staged_xex = stage_dir / output_path.name

            built_path = prepared.arranged_result.build_xex(
                staged_xex,
                player_address=options.player_address,
                music_address=options.music_address,
                zp_base=options.zp_base,
                mads_bin=toolchain.mads_bin,
                player_asm=toolchain.player_asm,
                player_version=f"v{eff_ver}",
                keep_asm=options.keep_asm,
            )

            if not built_path.is_file() or built_path.stat().st_size == 0:
                raise RuntimeError(f"MADS produced missing or empty XEX output: {built_path}")

            xex_bytes = built_path.read_bytes()
            segments = assign_roles(
                parse_xex(xex_bytes),
                player_address=options.player_address,
                music_address=options.music_address,
            )
            seg_summary = tuple((s.start, s.end, s.role) for s in segments)

            commit_pairs: List[Tuple[Path, Path]] = [(built_path, output_path)]
            asm_target: Optional[Path] = None
            if options.keep_asm:
                staged_asm = built_path.with_suffix(".asm")
                if not staged_asm.is_file() or staged_asm.stat().st_size == 0:
                    raise RuntimeError(
                        f"Expected companion MADS assembly missing or empty: {staged_asm}"
                    )
                asm_target = output_path.with_suffix(".asm")
                commit_pairs.append((staged_asm, asm_target))

            _commit_staged_pairs(commit_pairs, stage_dir)

        return XexExportResult(
            xex_path=output_path,
            asm_path=asm_target,
            size_bytes=output_path.stat().st_size,
            format_version=eff_ver,
            uses_16bit_bass=prepared.effective_uses_16bit_bass,
            effective_audctl=prepared.effective_audctl,
            player_address=options.player_address,
            music_address=options.music_address,
            zp_base=options.zp_base,
            segments=seg_summary,
            warnings=prepared.warnings,
        )

    def export_xex(
        self,
        state: LoadedCompositionState,
        config: StudioArrangementConfig,
        options: XexExportOptions,
    ) -> XexExportResult:
        """Prepare once and export *state* + *config* cleanly as an Atari XEX binary."""
        prepared = self.prepare_xex_export(state, config)
        return self.export_prepared_xex(prepared, options)

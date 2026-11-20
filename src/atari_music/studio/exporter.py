"""Headless XEX export, toolchain preflight, and transactional commit service (PySide6-free)."""

from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import shutil
import tempfile
from typing import Any, Dict, List, Optional, Tuple

from atari_music.api import MusicGenerationResult, arrange_song
from atari_music.instruments.planner import InstrumentPlanError
from atari_music.instruments.runtime import RuntimeDiagnostic
from atari_music.ir import IRSong, resolve_audctl_mode, resolve_initial_channel_instruments
from atari_music.studio.instruments import (
    InstrumentService,
    resolve_xex_export_player_version,
)
from atari_music.studio.loader import canonical_ir_sha256
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
ARRANGEMENT_MANIFEST_SCHEMA_ID = "atari-music/xex-arrangement-manifest/1"


def companion_arrangement_json_path(output_path: Path) -> Path:
    """Return the companion ``<stem>.arrangement.json`` path for an exported ``.xex`` path."""
    p = Path(output_path)
    return p.with_suffix(".arrangement.json") if p.suffix else Path(f"{p}.arrangement.json")


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
    source_state: Optional[LoadedCompositionState] = None

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
            eff_player_version = resolve_xex_export_player_version(config)
            arranged_result = arrange_song(
                state.base_pokey_ir,
                channel_instruments=config.assigned_map() or None,
                program_change_policy=config.program_change_policy,
                instrument_catalog_path=self._instrument_service.catalog_path,
                player_version=eff_player_version,
            )
        except InstrumentPlanError as exc:
            err_diags = exc.diagnostics or (
                RuntimeDiagnostic(severity="ERROR", code=exc.code, message=str(exc)),
            )
            return PreparedXexArrangement(
                config=config,
                arranged_result=None,
                effective_format_version=None,
                effective_uses_16bit_bass=state.base_uses_16bit_bass,
                effective_audctl=resolve_audctl_mode(state.base_pokey_ir),
                resolved_target_backend=None,
                diagnostics=err_diags,
                blocking_errors=(str(exc),),
                warnings=(),
                source_state=state,
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
            source_state=state,
        )

    def _build_arrangement_manifest(
        self,
        prepared: PreparedXexArrangement,
        options: XexExportOptions,
        *,
        output_path: Path,
        asm_target: Optional[Path],
        json_target: Path,
        xex_size_bytes: int,
        segments: Tuple[Tuple[int, int, str], ...],
    ) -> Dict[str, Any]:
        """Construct a deterministic JSON manifest describing the exported XEX arrangement."""
        assert prepared.arranged_result is not None
        assert prepared.effective_format_version is not None

        arranged_res = prepared.arranged_result
        arranged_ir: IRSong = arranged_res.pokey_ir
        state = prepared.source_state
        config = prepared.config
        catalog = self._instrument_service.catalog

        init_idx_map = resolve_initial_channel_instruments(arranged_ir)
        idx_to_ir_inst = {idx: inst for idx, inst in enumerate(arranged_ir.instruments)}
        id_to_ir_inst = {inst.id: inst for inst in arranged_ir.instruments}

        channels_manifest: Dict[str, Any] = {}
        for ch in (1, 2, 3, 4):
            assigned_id = config.channel_instruments.get(ch)
            is_16bit_slave = ch == 2 and prepared.effective_uses_16bit_bass
            is_16bit_ch = ch in (1, 2) and prepared.effective_uses_16bit_bass
            ch_analysis = state.channels.get(ch) if state is not None else None

            active_notes = [
                n for pat in arranged_ir.patterns for n in pat.tracks.get(ch, ()) if not n.is_rest
            ]
            init_ir_inst = idx_to_ir_inst.get(init_idx_map.get(ch, 0))
            if active_notes:
                first_note_inst = id_to_ir_inst.get(active_notes[0].instrument_id)
                if first_note_inst is not None:
                    init_ir_inst = first_note_inst

            profile_id = assigned_id or (init_ir_inst.profile_id if init_ir_inst is not None else None)
            catalog_profile_info: Optional[Dict[str, Any]] = None
            if not is_16bit_slave and profile_id and catalog.has_profile(profile_id):
                prof, beh = catalog.resolve_profile_behavior(profile_id)
                catalog_profile_info = {
                    "instrument_id": prof.instrument_id,
                    "display_name": prof.display_name,
                    "family": prof.family,
                    "intended_roles": list(prof.intended_roles),
                    "base_distortion": int(prof.base_distortion),
                    "base_distortion_hex": f"${int(prof.base_distortion):02X}",
                    "waveform_family": prof.waveform_family,
                    "divider_mode": prof.hardware_constraints.divider_mode,
                    "preferred_clock_hz": prof.hardware_constraints.preferred_clock_hz,
                    "required_audctl_bits": int(prof.hardware_constraints.required_audctl_bits),
                    "poly4_safe_tuning": bool(prof.hardware_constraints.poly4_safe_tuning),
                    "midi_range": list(prof.hardware_constraints.midi_range),
                    "behavior_id": prof.behavior_id,
                    "runtime_tier": beh.required_runtime_tier if beh is not None else "core_v1",
                    "modulation_mode": beh.modulation_mode if beh is not None else "none",
                    "envelope": {
                        "attack_frames": int(prof.envelope.attack_frames),
                        "decay_frames": int(prof.envelope.decay_frames),
                        "sustain_vol": int(prof.envelope.sustain_vol),
                        "release_frames": int(prof.envelope.release_frames),
                        "peak_vol": int(prof.envelope.peak_vol),
                    },
                }

            if is_16bit_slave:
                assignment_mode = "locked_16bit_slave"
                eff_name = "Locked (CH1+CH2 16-bit slave)"
            elif assigned_id is not None and catalog_profile_info is not None:
                assignment_mode = "catalog_override"
                eff_name = f"{catalog_profile_info['display_name']} ({assigned_id})"
            elif init_ir_inst is not None:
                assignment_mode = "original"
                eff_name = init_ir_inst.name
            elif ch_analysis is not None:
                assignment_mode = "original"
                eff_name = ch_analysis.initial_instrument_name
            else:
                assignment_mode = "original"
                eff_name = "Default"

            channels_manifest[str(ch)] = {
                "channel": ch,
                "assigned_instrument_id": assigned_id,
                "assignment_mode": assignment_mode,
                "effective_instrument_name": eff_name,
                "role": (
                    ch_analysis.role
                    if ch_analysis is not None
                    else (init_ir_inst.role if init_ir_inst is not None else "melody")
                ),
                "active": ch_analysis.active if ch_analysis is not None else (len(active_notes) > 0),
                "note_count": ch_analysis.note_count if ch_analysis is not None else len(active_notes),
                "midi_min": ch_analysis.midi_min if ch_analysis is not None else None,
                "midi_max": ch_analysis.midi_max if ch_analysis is not None else None,
                "has_program_changes": (
                    ch_analysis.has_program_changes if ch_analysis is not None else False
                ),
                "program_change_count": (
                    ch_analysis.program_change_count if ch_analysis is not None else 0
                ),
                "is_16bit": is_16bit_ch,
                "catalog_profile": catalog_profile_info,
            }

        arranged_instruments_list: List[Dict[str, Any]] = []
        for inst in arranged_ir.instruments:
            arranged_instruments_list.append(
                {
                    "id": int(inst.id),
                    "name": inst.name,
                    "profile_id": inst.profile_id,
                    "behavior_id": inst.behavior_id,
                    "role": inst.role,
                    "distortion": int(inst.distortion),
                    "distortion_hex": f"${int(inst.distortion):02X}",
                    "is_16bit": bool(inst.is_16bit),
                    "audctl": int(inst.audctl) if inst.audctl is not None else None,
                    "audctl_hex": f"${int(inst.audctl):02X}" if inst.audctl is not None else None,
                    "modulation": int(inst.modulation),
                    "envelope": {
                        "attack_frames": int(inst.envelope.attack_frames),
                        "decay_frames": int(inst.envelope.decay_frames),
                        "sustain_vol": int(inst.envelope.sustain_vol),
                        "release_frames": int(inst.envelope.release_frames),
                    },
                }
            )

        return {
            "schema_id": ARRANGEMENT_MANIFEST_SCHEMA_ID,
            "composition": {
                "title": state.title if state is not None else arranged_ir.title,
                "author": state.author if state is not None else arranged_ir.author,
                "source_path": (
                    str(state.source_path)
                    if (state is not None and state.source_path is not None)
                    else None
                ),
                "source_kind": state.source_kind if state is not None else None,
                "key": state.key if state is not None else arranged_ir.key,
                "mode": state.mode if state is not None else arranged_ir.mode,
                "tempo_bpm": int(state.tempo_bpm if state is not None else arranged_ir.tempo_bpm),
                "frames_per_tick": int(arranged_ir.frames_per_tick),
                "pattern_count": len(arranged_ir.patterns),
                "sequence_length": len(arranged_ir.sequence),
                "duration_seconds": round(float(arranged_res.metadata.duration), 4),
                "base_uses_16bit_bass": (
                    bool(state.base_uses_16bit_bass)
                    if state is not None
                    else bool(arranged_ir.uses_16bit_bass)
                ),
                "base_ir_sha256": state.base_ir_sha256 if state is not None else None,
                "musical_fingerprint": state.musical_fingerprint if state is not None else None,
                "arranged_ir_sha256": canonical_ir_sha256(arranged_ir),
            },
            "arrangement": {
                "target_backend": config.target_backend,
                "resolved_target_backend": prepared.resolved_target_backend,
                "requested_player_version": config.player_version,
                "effective_format_version": int(prepared.effective_format_version),
                "program_change_policy": config.program_change_policy,
                "effective_uses_16bit_bass": bool(prepared.effective_uses_16bit_bass),
                "effective_audctl": int(prepared.effective_audctl),
                "effective_audctl_hex": f"${int(prepared.effective_audctl):02X}",
                "channel_assignments": {
                    str(ch): config.channel_instruments.get(ch) for ch in (1, 2, 3, 4)
                },
                "channels": channels_manifest,
                "arranged_instruments": arranged_instruments_list,
            },
            "export": {
                "xex_file": output_path.name,
                "asm_file": asm_target.name if asm_target is not None else None,
                "arrangement_json_file": json_target.name,
                "xex_size_bytes": int(xex_size_bytes),
                "music_data_size_bytes": int(arranged_res.metadata.memory_size_bytes),
                "format_version": int(prepared.effective_format_version),
                "player_address": int(options.player_address),
                "player_address_hex": f"${int(options.player_address):04X}",
                "music_address": (
                    int(options.music_address) if options.music_address is not None else None
                ),
                "music_address_hex": (
                    f"${int(options.music_address):04X}"
                    if options.music_address is not None
                    else None
                ),
                "zp_base": int(options.zp_base),
                "zp_base_hex": f"${int(options.zp_base):02X}",
                "segments": [
                    {
                        "start": int(start),
                        "end": int(end),
                        "start_hex": f"${int(start):04X}",
                        "end_hex": f"${int(end):04X}",
                        "size_bytes": int(end - start + 1),
                        "role": role,
                    }
                    for start, end, role in segments
                ],
            },
            "diagnostics": {
                "warnings": list(prepared.warnings),
                "items": [
                    {
                        "severity": d.severity,
                        "code": d.code,
                        "message": d.message,
                        "channel": d.channel,
                        "instrument_id": d.instrument_id,
                    }
                    for d in prepared.diagnostics
                ],
            },
        }

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

            json_target: Optional[Path] = None
            if options.keep_arrangement_json:
                staged_json = companion_arrangement_json_path(built_path)
                json_target = companion_arrangement_json_path(output_path)
                manifest = self._build_arrangement_manifest(
                    prepared,
                    options,
                    output_path=output_path,
                    asm_target=asm_target,
                    json_target=json_target,
                    xex_size_bytes=len(xex_bytes),
                    segments=seg_summary,
                )
                staged_json.write_text(
                    json.dumps(manifest, indent=2, ensure_ascii=False) + "\n",
                    encoding="utf-8",
                )
                commit_pairs.append((staged_json, json_target))

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
            arrangement_json_path=json_target,
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

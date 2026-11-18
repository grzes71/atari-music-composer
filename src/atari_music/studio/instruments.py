"""Instrument catalog lookup and runtime compatibility service for Studio (PySide6-free)."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Dict, List, Mapping, Optional, Sequence, Tuple

from atari_music.instruments.catalog import (
    InstrumentCatalog,
    load_instrument_catalog,
)
from atari_music.instruments.planner import (
    InstrumentPlanError,
    arrange_ir_song,
    resolve_export_format_version,
)
from atari_music.instruments.runtime import (
    TARGET_V1_XEX,
    TARGET_V2_ITER1_XEX,
    TARGET_WAV_PREVIEW,
    ChannelAssignmentRequest,
    POKEYRuntime,
    RuntimeDiagnostic,
    TargetCapability,
)
from atari_music.ir import (
    IRSong,
    resolve_audctl_mode,
    resolve_initial_channel_instruments,
    song_requires_v2,
)
from atari_music.mads_exporter import (
    FormatVersionError,
    ModulationNotExpressibleError,
    StreamValidationError,
    VolumeContourNotExpressibleError,
    export_mads_asm,
)
from atari_music.studio.models import (
    ArrangementEvaluation,
    CatalogOptionStatus,
    ChannelSlotEvaluation,
    LoadedCompositionState,
    StudioArrangementConfig,
    StudioTargetName,
)

_TARGET_CAPABILITY_MAP: Mapping[StudioTargetName, TargetCapability] = {
    "xex_v2": TARGET_V2_ITER1_XEX,
    "xex_v1": TARGET_V1_XEX,
    "wav": TARGET_WAV_PREVIEW,
}


def _is_stale_stage_a_xex_v2_notice(
    diag: RuntimeDiagnostic,
    resolved_target: TargetCapability,
    effective_format_version: int,
) -> bool:
    """Return True strictly for the Stage-A planning notice on ``xex_v2`` during XEX v2 export.

    ``TARGET_V2_ITER1_XEX`` retains ``is_implemented=False`` to preserve Stage-A runtime
    contracts, whereas Stage C/D implemented full v2 compilation in ``mads_exporter``
    (``SONG_FORMAT_VERSION_2``) and ``player.asm`` (``SONG_FORMAT_VERSION_V2``). Suppressing
    this single warning ONLY when ``resolved_target`` is ``xex_v2`` and
    ``effective_format_version == 2`` avoids misleading Studio users without hiding unrelated
    hardware warnings (e.g., ``MIDI_RANGE_EXCEEDED``) or non-XEX planned targets (``asap``).
    """
    return (
        diag.severity == "WARNING"
        and diag.code == "TARGET_NOT_IMPLEMENTED"
        and resolved_target.backend == "xex_v2"
        and effective_format_version == 2
    )


class InstrumentService:
    """Stateless wrapper around ``InstrumentCatalog``, ``POKEYRuntime``, and ``arrange_ir_song``."""

    def __init__(self, catalog_path: Optional[Path] = None) -> None:
        self._catalog_path = catalog_path
        self._catalog: InstrumentCatalog = load_instrument_catalog(catalog_path)
        self._catalog_digest = hashlib.sha256(
            self._catalog.to_deterministic_json().encode("utf-8")
        ).hexdigest()

    @property
    def catalog_path(self) -> Optional[Path]:
        return self._catalog_path

    @property
    def catalog(self) -> InstrumentCatalog:
        return self._catalog

    @property
    def catalog_digest(self) -> str:
        return self._catalog_digest

    def _effective_target(self, config: StudioArrangementConfig) -> TargetCapability:
        if config.player_version == "v1" and config.target_backend == "xex_v2":
            return TARGET_V1_XEX
        return _TARGET_CAPABILITY_MAP[config.target_backend]

    @staticmethod
    def _channel_has_active_notes(song: IRSong, ch: int) -> bool:
        return any(
            not note.is_rest
            for pat in song.patterns
            for note in pat.tracks.get(ch, ())
        )

    def _effective_ch1_is_16bit(
        self,
        state: LoadedCompositionState,
        config: StudioArrangementConfig,
    ) -> bool:
        ch1_id = config.channel_instruments.get(1)
        if ch1_id is not None and self._catalog.has_profile(ch1_id):
            prof1 = self._catalog.get_profile(ch1_id)
            return prof1.hardware_constraints.divider_mode == "16bit_ch12"
        if state.base_pokey_ir.uses_16bit_bass:
            return True
        init_map = resolve_initial_channel_instruments(state.base_pokey_ir)
        inst_idx = init_map.get(1, 0)
        if 0 <= inst_idx < len(state.base_pokey_ir.instruments):
            return bool(state.base_pokey_ir.instruments[inst_idx].is_16bit)
        return False

    def _build_requests(
        self,
        state: LoadedCompositionState,
        assigned_map: Mapping[int, str],
    ) -> List[ChannelAssignmentRequest]:
        requests: List[ChannelAssignmentRequest] = []
        for ch, inst_id in sorted(assigned_map.items()):
            ch_stats = state.channels[ch]
            requests.append(
                ChannelAssignmentRequest(
                    channel=ch,
                    instrument_ids=(inst_id,),
                    midi_min=ch_stats.midi_min,
                    midi_max=ch_stats.midi_max,
                )
            )
        return requests

    def _evaluate_channel_option(
        self,
        state: LoadedCompositionState,
        config: StudioArrangementConfig,
        target: TargetCapability,
        ch: int,
        inst_id: str,
        ch2_locked: bool,
        ch2_lock_reason: Optional[str],
    ) -> CatalogOptionStatus:
        prof, beh = self._catalog.resolve_profile_behavior(inst_id)
        tier = beh.required_runtime_tier if beh else "core_v1"

        if ch == 2 and ch2_locked:
            return CatalogOptionStatus(
                instrument_id=prof.instrument_id,
                display_name=prof.display_name,
                family=prof.family,
                intended_roles=prof.intended_roles,
                base_distortion=prof.base_distortion,
                divider_mode=prof.hardware_constraints.divider_mode,
                preferred_clock_hz=prof.hardware_constraints.preferred_clock_hz,
                channels_allowed=prof.hardware_constraints.channels_allowed,
                midi_range=prof.hardware_constraints.midi_range,
                behavior_id=prof.behavior_id,
                tier=tier,
                compatible=False,
                status="BLOCKED_CONFLICT",
                reason=ch2_lock_reason,
                midi_warning=None,
            )

        cand_assigned = dict(config.assigned_map())
        cand_assigned[ch] = inst_id
        # Wait: when evaluating CH1 candidates on a 16-bit baseline, CH2 may not be assigned anyway;
        # still test directly through POKEYRuntime.resolve + arrange_ir_song.
        requests = self._build_requests(state, cand_assigned)
        rt_report = POKEYRuntime.resolve(requests, self._catalog, target=target)

        err_msgs = [d.message for d in rt_report.diagnostics if d.severity == "ERROR"]
        warn_msgs = [
            d.message
            for d in rt_report.diagnostics
            if d.severity == "WARNING" and d.channel == ch and d.instrument_id == inst_id
        ]

        compatible = rt_report.is_compatible
        status = rt_report.status

        if compatible:
            try:
                arrange_ir_song(
                    state.base_pokey_ir,
                    channel_instruments=cand_assigned,
                    program_change_policy=config.program_change_policy,
                    catalog=self._catalog,
                    player_version=config.player_version,
                )
            except InstrumentPlanError as exc:
                compatible = False
                status = "BLOCKED_CONFLICT"
                err_msgs.append(str(exc))

        return CatalogOptionStatus(
            instrument_id=prof.instrument_id,
            display_name=prof.display_name,
            family=prof.family,
            intended_roles=prof.intended_roles,
            base_distortion=prof.base_distortion,
            divider_mode=prof.hardware_constraints.divider_mode,
            preferred_clock_hz=prof.hardware_constraints.preferred_clock_hz,
            channels_allowed=prof.hardware_constraints.channels_allowed,
            midi_range=prof.hardware_constraints.midi_range,
            behavior_id=prof.behavior_id,
            tier=tier,
            compatible=compatible,
            status=status,
            reason="; ".join(err_msgs) if err_msgs else None,
            midi_warning="; ".join(warn_msgs) if warn_msgs else None,
        )

    def evaluate_arrangement(
        self,
        state: LoadedCompositionState,
        config: StudioArrangementConfig,
        *,
        include_catalog_options: bool = True,
    ) -> ArrangementEvaluation:
        """Validate *config* against *state* using ``POKEYRuntime`` and ``arrange_ir_song``."""
        target = self._effective_target(config)
        assigned_map = config.assigned_map()
        ch1_is_16bit = self._effective_ch1_is_16bit(state, config)

        ch2_locked = ch1_is_16bit
        ch2_lock_reason: Optional[str] = None
        if ch2_locked:
            if config.channel_instruments.get(1) is not None:
                ch2_lock_reason = (
                    f"Unavailable: CH1 uses '{config.channel_instruments[1]}' "
                    "(divider_mode='16bit_ch12' pairs CH1+CH2)."
                )
            else:
                ch2_lock_reason = (
                    "Unavailable: composition uses 16-bit CH1+CH2 bass coupling "
                    "(base uses_16bit_bass=True)."
                )

        # Evaluate full cross-channel configuration via POKEYRuntime + arrange_ir_song
        blocking_errors: List[str] = []
        warnings: List[str] = []
        diagnostics: List[RuntimeDiagnostic] = []

        if ch2_locked and config.channel_instruments.get(2) is not None:
            blocking_errors.append(
                f"Channel 2 cannot be assigned ('{config.channel_instruments[2]}') while CH1 uses 16-bit CH1+CH2 mode."
            )

        requests = self._build_requests(state, assigned_map)
        rt_report = (
            POKEYRuntime.resolve(requests, self._catalog, target=target)
            if requests
            else None
        )
        if rt_report is not None:
            diagnostics.extend(rt_report.diagnostics)
            for d in rt_report.diagnostics:
                if d.severity == "ERROR":
                    if d.message not in blocking_errors:
                        blocking_errors.append(d.message)
                elif d.severity == "WARNING":
                    if d.message not in warnings:
                        warnings.append(d.message)

        effective_format_version: Optional[int] = None
        effective_uses_16bit = ch1_is_16bit
        effective_audctl = resolve_audctl_mode(state.base_pokey_ir)
        v2_reasons: Tuple[str, ...] = state.base_v2_reasons

        try:
            arranged_ir, _ = arrange_ir_song(
                state.base_pokey_ir,
                channel_instruments=assigned_map or None,
                program_change_policy=config.program_change_policy,
                catalog=self._catalog,
                player_version=config.player_version,
            )
            effective_format_version = resolve_export_format_version(
                arranged_ir, config.player_version
            )
            effective_uses_16bit = bool(arranged_ir.uses_16bit_bass)
            effective_audctl = resolve_audctl_mode(arranged_ir)
            v2_reasons = tuple(song_requires_v2(arranged_ir))
        except InstrumentPlanError as exc:
            msg = str(exc)
            if msg not in blocking_errors:
                blocking_errors.append(msg)

        ch_slots: Dict[int, ChannelSlotEvaluation] = {}
        for ch in (1, 2, 3, 4):
            assigned_id = config.channel_instruments.get(ch)
            ch_available = not (ch == 2 and ch2_locked)
            lock_reason = ch2_lock_reason if ch == 2 and ch2_locked else None

            if not ch_available:
                eff_label = "Locked (CH1+CH2 16-bit slave)"
                eff_16 = True
            elif assigned_id is not None and self._catalog.has_profile(assigned_id):
                prof = self._catalog.get_profile(assigned_id)
                eff_label = f"{prof.display_name} ({prof.instrument_id})"
                eff_16 = prof.hardware_constraints.divider_mode in ("16bit_ch12", "16bit_ch34")
            else:
                orig_name = state.channels[ch].initial_instrument_name
                eff_label = f"{orig_name} (Original)"
                eff_16 = bool(ch == 1 and state.base_uses_16bit_bass)

            options: Tuple[CatalogOptionStatus, ...] = ()
            if include_catalog_options:
                options = tuple(
                    self._evaluate_channel_option(
                        state,
                        config,
                        target,
                        ch,
                        prof.instrument_id,
                        ch2_locked,
                        ch2_lock_reason,
                    )
                    for prof in self._catalog.instruments
                )

            ch_diags = tuple(d for d in diagnostics if d.channel == ch)
            ch_slots[ch] = ChannelSlotEvaluation(
                channel=ch,
                available_for_assignment=ch_available,
                lock_reason=lock_reason,
                effective_instrument_label=eff_label,
                effective_is_16bit=eff_16,
                options=options,
                diagnostics=ch_diags,
            )

        return ArrangementEvaluation(
            is_valid=(len(blocking_errors) == 0),
            effective_format_version=effective_format_version,
            effective_uses_16bit_bass=effective_uses_16bit,
            effective_audctl=effective_audctl,
            v2_reasons=v2_reasons,
            channels=ch_slots,
            diagnostics=tuple(diagnostics),
            blocking_errors=tuple(blocking_errors),
            warnings=tuple(warnings),
        )

    def _collect_arranged_channel_requests(
        self,
        state: LoadedCompositionState,
        config: StudioArrangementConfig,
        arranged_ir: IRSong,
    ) -> List[ChannelAssignmentRequest]:
        """Collect active catalog profiles from *arranged_ir* (overrides + preserved switches)."""
        inst_by_id = {inst.id: inst for inst in arranged_ir.instruments}
        init_map = resolve_initial_channel_instruments(arranged_ir)
        assigned_map = config.assigned_map()
        requests: List[ChannelAssignmentRequest] = []

        for ch in (1, 2, 3, 4):
            has_notes = self._channel_has_active_notes(arranged_ir, ch)
            if ch == 2 and arranged_ir.uses_16bit_bass and not has_notes and ch not in assigned_map:
                continue

            ordered_pids: List[str] = []

            def _record(ir_inst_id: int) -> None:
                ir_inst = inst_by_id.get(ir_inst_id)
                if (
                    ir_inst is not None
                    and ir_inst.profile_id
                    and self._catalog.has_profile(ir_inst.profile_id)
                    and ir_inst.profile_id not in ordered_pids
                ):
                    ordered_pids.append(ir_inst.profile_id)

            if ch in init_map and (has_notes or ch in assigned_map):
                _record(init_map[ch])
            for pat in arranged_ir.patterns:
                for note in pat.tracks.get(ch, ()):
                    if not note.is_rest or note.pending_program_changes:
                        _record(note.instrument_id)
                    for pc_id in note.pending_program_changes:
                        _record(pc_id)

            if ordered_pids:
                ch_stats = state.channels[ch]
                requests.append(
                    ChannelAssignmentRequest(
                        channel=ch,
                        instrument_ids=tuple(ordered_pids),
                        midi_min=ch_stats.midi_min,
                        midi_max=ch_stats.midi_max,
                    )
                )
        return requests

    def validate_arranged_ir_for_xex(
        self,
        state: LoadedCompositionState,
        config: StudioArrangementConfig,
        arranged_ir: IRSong,
    ) -> Tuple[
        Optional[int],
        TargetCapability,
        Tuple[RuntimeDiagnostic, ...],
        Tuple[str, ...],
        Tuple[str, ...],
    ]:
        """Validate a concrete *arranged_ir* for XEX compilation against its resolved format version.

        Uses ``resolve_export_format_version(arranged_ir, config.player_version)`` so ``auto``,
        ``v1``, and ``v2`` resolve identically to ``build_xex`` without duplicating version logic,
        then validates runtime capabilities and in-memory MADS expressibility (including
        ``volume_contour`` and modulations) strictly on *arranged_ir*.
        """
        blocking_errors: List[str] = []
        warnings: List[str] = []
        kept_diagnostics: List[RuntimeDiagnostic] = []

        try:
            effective_ver = resolve_export_format_version(arranged_ir, config.player_version)
        except InstrumentPlanError as exc:
            return None, TARGET_V1_XEX, (), (str(exc),), ()

        if effective_ver == 1:
            v2_reasons = song_requires_v2(arranged_ir)
            if v2_reasons:
                blocking_errors.append(
                    "selected arrangement requires format v2 (" + "; ".join(v2_reasons) + ")"
                )
            resolved_target = TARGET_V1_XEX
        else:
            resolved_target = TARGET_V2_ITER1_XEX

        requests = self._collect_arranged_channel_requests(state, config, arranged_ir)
        if requests:
            rt_report = POKEYRuntime.resolve(requests, self._catalog, target=resolved_target)
            for diag in rt_report.diagnostics:
                if _is_stale_stage_a_xex_v2_notice(diag, resolved_target, effective_ver):
                    continue
                kept_diagnostics.append(diag)
                if diag.severity == "ERROR":
                    if diag.message not in blocking_errors:
                        blocking_errors.append(diag.message)
                elif diag.severity == "WARNING":
                    if diag.message not in warnings:
                        warnings.append(diag.message)

        try:
            # Side-effect free (output_path=None): exercises authoritative volume_contour,
            # modulation, and v1/v2 exporter rules directly on arranged_ir.
            export_mads_asm(arranged_ir, output_path=None, format_version=effective_ver)
        except (
            FormatVersionError,
            StreamValidationError,
            VolumeContourNotExpressibleError,
            ModulationNotExpressibleError,
        ) as exc:
            msg = str(exc)
            if msg not in blocking_errors:
                blocking_errors.append(msg)

        return (
            effective_ver,
            resolved_target,
            tuple(kept_diagnostics),
            tuple(blocking_errors),
            tuple(warnings),
        )

    def evaluate_for_xex(
        self,
        state: LoadedCompositionState,
        config: StudioArrangementConfig,
    ) -> ArrangementEvaluation:
        """Fast lightweight XEX readiness evaluation for UI controls without audio simulation."""
        # Always evaluate against XEX rules rather than TARGET_WAV_PREVIEW, while respecting
        # effective format version resolution (auto/v1/v2).
        assigned_map = config.assigned_map()
        blocking_errors: List[str] = []
        warnings: List[str] = []
        diagnostics: Tuple[RuntimeDiagnostic, ...] = ()
        effective_format_version: Optional[int] = None
        effective_uses_16bit = self._effective_ch1_is_16bit(state, config)
        effective_audctl = resolve_audctl_mode(state.base_pokey_ir)
        v2_reasons: Tuple[str, ...] = state.base_v2_reasons

        try:
            arranged_ir, _ = arrange_ir_song(
                state.base_pokey_ir,
                channel_instruments=assigned_map or None,
                program_change_policy=config.program_change_policy,
                catalog=self._catalog,
                player_version=config.player_version,
            )
            effective_uses_16bit = bool(arranged_ir.uses_16bit_bass)
            effective_audctl = resolve_audctl_mode(arranged_ir)
            v2_reasons = tuple(song_requires_v2(arranged_ir))
            (
                effective_format_version,
                _resolved_target,
                diagnostics,
                xex_errors,
                xex_warnings,
            ) = self.validate_arranged_ir_for_xex(state, config, arranged_ir)
            blocking_errors.extend(xex_errors)
            warnings.extend(xex_warnings)
        except InstrumentPlanError as exc:
            blocking_errors.append(str(exc))

        return ArrangementEvaluation(
            is_valid=(len(blocking_errors) == 0),
            effective_format_version=effective_format_version,
            effective_uses_16bit_bass=effective_uses_16bit,
            effective_audctl=effective_audctl,
            v2_reasons=v2_reasons,
            channels={},
            diagnostics=diagnostics,
            blocking_errors=tuple(blocking_errors),
            warnings=tuple(warnings),
        )

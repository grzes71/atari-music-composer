"""Background-safe WAV arrangement and cache service for Studio (PySide6-free)."""

from __future__ import annotations

import os
from pathlib import Path
import tempfile
from typing import Dict, Optional

from atari_music.api import arrange_song
from atari_music.instruments.planner import InstrumentPlanError
from atari_music.studio.instruments import (
    InstrumentService,
    resolve_studio_target_and_player_version,
)
from atari_music.studio.loader import canonical_ir_sha256
from atari_music.studio.models import (
    CachedRenderEntry,
    LoadedCompositionState,
    RenderCacheKey,
    StudioArrangementConfig,
)


class RenderService:
    """Renders arranged compositions to cached temporary WAV files using POKEY Synth."""

    def __init__(
        self,
        instrument_service: InstrumentService,
        *,
        sample_rate: int = 44100,
    ) -> None:
        self._instrument_service = instrument_service
        self._sample_rate = int(sample_rate)
        self._temp_dir = tempfile.TemporaryDirectory(prefix="atari_music_studio_")
        self._cache: Dict[str, CachedRenderEntry] = {}

    @property
    def cache_dir(self) -> Path:
        return Path(self._temp_dir.name)

    def build_cache_key(
        self,
        state: LoadedCompositionState,
        config: StudioArrangementConfig,
    ) -> RenderCacheKey:
        """Compute deterministic multi-parameter cache key for *state* and *config*."""
        assigned = tuple(sorted(config.assigned_map().items()))
        try:
            _eff_target, eff_player_version = resolve_studio_target_and_player_version(config)
        except InstrumentPlanError:
            eff_player_version = config.player_version
        return RenderCacheKey(
            base_ir_sha256=state.base_ir_sha256,
            assigned_channels=assigned,
            program_change_policy=config.program_change_policy,
            player_version=eff_player_version,
            sample_rate=self._sample_rate,
            catalog_digest=self._instrument_service.catalog_digest,
        )

    def get_cached(
        self,
        state: LoadedCompositionState,
        config: StudioArrangementConfig,
    ) -> Optional[CachedRenderEntry]:
        """Return cached WAV metadata if already rendered for this exact configuration."""
        digest = self.build_cache_key(state, config).digest()
        entry = self._cache.get(digest)
        if entry is not None and entry.wav_path.is_file() and entry.wav_path.stat().st_size > 0:
            return CachedRenderEntry(
                cache_key=entry.cache_key,
                wav_path=entry.wav_path,
                duration_seconds=entry.duration_seconds,
                format_version=entry.format_version,
                uses_16bit_bass=entry.uses_16bit_bass,
                memory_size_bytes=entry.memory_size_bytes,
                config=entry.config,
                arranged_ir_sha256=entry.arranged_ir_sha256,
                from_cache=True,
                diagnostics=entry.diagnostics,
            )
        return None

    def render_preview(
        self,
        state: LoadedCompositionState,
        config: StudioArrangementConfig,
    ) -> CachedRenderEntry:
        """Validate, arrange (on immutable copy), and render WAV preview."""
        evaluation = self._instrument_service.evaluate_arrangement(
            state,
            config,
            include_catalog_options=False,
        )
        if not evaluation.is_valid:
            reasons = "; ".join(evaluation.blocking_errors) or "Invalid instrument configuration."
            raise ValueError(f"Cannot render invalid configuration: {reasons}")

        existing = self.get_cached(state, config)
        if existing is not None:
            return existing

        digest = self.build_cache_key(state, config).digest()
        target_wav = self.cache_dir / f"{digest}.wav"
        tmp_wav = self.cache_dir / f"{digest}.tmp.wav"

        eff_target, eff_player_version = resolve_studio_target_and_player_version(config)
        arranged = arrange_song(
            state.base_pokey_ir,
            channel_instruments=config.assigned_map() or None,
            program_change_policy=config.program_change_policy,
            instrument_catalog_path=self._instrument_service.catalog_path,
            player_version=eff_player_version,
            target=eff_target,
        )
        arranged.render_wav(tmp_wav, sample_rate=self._sample_rate)
        os.replace(tmp_wav, target_wav)

        entry = CachedRenderEntry(
            cache_key=digest,
            wav_path=target_wav,
            duration_seconds=float(arranged.metadata.duration),
            format_version=int(arranged.metadata.format_version),
            uses_16bit_bass=bool(arranged.metadata.uses_16bit_bass),
            memory_size_bytes=int(arranged.metadata.memory_size_bytes),
            config=config,
            arranged_ir_sha256=canonical_ir_sha256(arranged.pokey_ir),
            from_cache=False,
            diagnostics=evaluation.warnings,
        )
        self._cache[digest] = entry
        return entry

    def cleanup(self) -> None:
        """Release temporary preview directory and cache references."""
        self._cache.clear()
        self._temp_dir.cleanup()

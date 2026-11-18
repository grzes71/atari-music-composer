"""Integration tests for Phase 3 Stage 4.3: MainWindow A/B Comparison, render queue & playback."""

from __future__ import annotations

from collections import deque
import math
import os
from pathlib import Path
import struct
import threading
import time
from typing import Callable, Optional
import wave

import pytest

PySide6 = pytest.importorskip("PySide6")

from PySide6.QtCore import QIODevice  # noqa: E402
from PySide6.QtWidgets import QApplication, QTabWidget, QVBoxLayout  # noqa: E402

from atari_music.studio.models import CachedRenderEntry, StudioArrangementConfig  # noqa: E402
from atari_music.studio.renderer import RenderService  # noqa: E402
from atari_music.studio.ui.audio_player import (  # noqa: E402
    AUDIO_ERR_NO_DEVICE,
    AudioPlaybackError,
    DualPcmStreamDevice,
    PcmFormatSpec,
    QtAudio,
    WavPcmData,
    convert_pcm_data,
    negotiate_device_format,
)
from atari_music.studio.ui.ab_panel import ABComparisonPanel  # noqa: E402
from atari_music.studio.ui.main_window import MainWindow  # noqa: E402
from atari_music.studio.ui.preset_bar import PresetBarWidget  # noqa: E402

pytestmark = pytest.mark.core

REPO_ROOT = Path(__file__).resolve().parents[1]
SONG_8BIT = REPO_ROOT / "examples" / "ai" / "action_fast.json"
SONG_16BIT = REPO_ROOT / "examples" / "songs" / "wybierak-2.dsl"


@pytest.fixture(scope="module")
def qapp():
    if "QT_QPA_PLATFORM" not in os.environ:
        os.environ["QT_QPA_PLATFORM"] = "offscreen"
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    yield app


def _wait_until(app: QApplication, predicate, timeout_s: float = 20.0) -> None:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        app.processEvents()
        if predicate():
            return
        time.sleep(0.015)
    raise AssertionError("Timed out waiting for Qt / worker condition")


class _FakeABAudioBackend:
    """Hardware-free AudioSinkBackend supporting position stepping for MainWindow A/B tests."""

    def __init__(self, *, has_device: bool = True, buffer_ms: int = 100) -> None:
        self.has_device = has_device
        self.buffer_ms = buffer_ms
        self._callback: Optional[Callable[[QtAudio.State, QtAudio.Error], None]] = None
        self._stream: Optional[DualPcmStreamDevice] = None
        self._spec: Optional[PcmFormatSpec] = None
        self._state: QtAudio.State = QtAudio.State.StoppedState
        self._error: QtAudio.Error = QtAudio.Error.NoError
        self._buffer_size_bytes: int = 0
        self._queued = bytearray()
        self._processed_bytes: int = 0
        self._volume: float = 1.0
        self.start_calls: int = 0
        self.release_calls: int = 0

    def has_output_device(self) -> bool:
        return self.has_device

    def set_state_callback(self, callback: Callable[[QtAudio.State, QtAudio.Error], None]) -> None:
        self._callback = callback

    def negotiate_and_prepare(self, wav: WavPcmData, stream: DualPcmStreamDevice) -> PcmFormatSpec:
        if not self.has_device:
            raise AudioPlaybackError("No audio output device is available.", code=AUDIO_ERR_NO_DEVICE)
        spec = negotiate_device_format(wav, is_supported_fn=lambda _s: True)
        pcm = convert_pcm_data(wav, spec)
        if not stream.isOpen():
            stream.open(QIODevice.OpenModeFlag.ReadOnly | QIODevice.OpenModeFlag.Unbuffered)
        stream.set_pcm_data(pcm, spec.frame_bytes)
        self._spec = spec
        self._stream = stream
        raw_buf = int(round((spec.bytes_per_second * self.buffer_ms) / 1000.0))
        self._buffer_size_bytes = max(spec.frame_bytes, (raw_buf // spec.frame_bytes) * spec.frame_bytes)
        self._queued.clear()
        self._processed_bytes = 0
        self._error = QtAudio.Error.NoError
        self._state = QtAudio.State.StoppedState
        return spec

    def _emit_state(self, st: QtAudio.State, err: QtAudio.Error = QtAudio.Error.NoError) -> None:
        self._state = st
        self._error = err
        if self._callback is not None:
            self._callback(st, err)

    def _fill(self) -> None:
        if self._stream is None or self._buffer_size_bytes <= 0:
            return
        space = self._buffer_size_bytes - len(self._queued)
        if space > 0 and not self._stream.atEnd():
            chunk = self._stream.read(space)
            if chunk:
                self._queued.extend(chunk)

    def start(self, stream: DualPcmStreamDevice) -> None:
        self.start_calls += 1
        self._stream = stream
        self._processed_bytes = 0
        self._queued.clear()
        self._fill()
        self._emit_state(QtAudio.State.ActiveState)

    def advance_ms(self, delta_ms: int) -> None:
        if self._state != QtAudio.State.ActiveState or self._spec is None:
            return
        step_bytes = int(round((delta_ms * self._spec.bytes_per_second) / 1000.0))
        step_bytes = (step_bytes // self._spec.frame_bytes) * self._spec.frame_bytes
        rem = step_bytes
        while rem > 0:
            self._fill()
            if not self._queued:
                break
            take = min(rem, len(self._queued))
            del self._queued[:take]
            self._processed_bytes += take
            rem -= take
        self._fill()
        if not self._queued and (self._stream is None or self._stream.atEnd()):
            self._emit_state(QtAudio.State.IdleState)

    def suspend(self) -> None:
        if self._state == QtAudio.State.ActiveState:
            self._emit_state(QtAudio.State.SuspendedState)

    def resume(self) -> None:
        if self._state == QtAudio.State.SuspendedState:
            self._emit_state(QtAudio.State.ActiveState)

    def stop(self) -> None:
        self._queued.clear()
        self._emit_state(QtAudio.State.StoppedState)

    def reset(self) -> None:
        self._queued.clear()
        self._processed_bytes = 0
        self._state = QtAudio.State.StoppedState

    def processed_usecs(self) -> int:
        if self._spec is None or self._spec.bytes_per_second <= 0:
            return 0
        return int(round((self._processed_bytes * 1_000_000.0) / self._spec.bytes_per_second))

    def buffer_size(self) -> int:
        return self._buffer_size_bytes

    def bytes_free(self) -> int:
        return max(0, self._buffer_size_bytes - len(self._queued))

    def state(self) -> QtAudio.State:
        return self._state

    def error(self) -> QtAudio.Error:
        return self._error

    def set_volume(self, volume: float) -> None:
        self._volume = volume

    def release(self) -> None:
        self.release_calls += 1
        self._queued.clear()
        self._processed_bytes = 0
        self._state = QtAudio.State.StoppedState


def _write_pcm_wav(path: Path, *, duration_s: float = 2.0, freq_hz: float = 440.0) -> Path:
    sr = 44100
    frames = max(1, int(round(sr * duration_s)))
    buf = bytearray()
    for i in range(frames):
        val = int(0.25 * 32767 * math.sin(2.0 * math.pi * freq_hz * (i / sr)))
        buf.extend(struct.pack("<h", val))
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sr)
        wf.writeframes(bytes(buf))
    return path


def test_ab_panel_placement_save_load_validation_and_preset_sync(
    qapp: QApplication,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    win = MainWindow(audio_backend=_FakeABAudioBackend(), presets_dir=tmp_path / "presets")
    try:
        # 1. Workspace uses Tab-Based layout: ActionBar -> PresetBar -> QTabWidget (Instruments default, A/B in Tab 1) -> Transport
        central_layout = win.centralWidget().layout()
        assert isinstance(central_layout, QVBoxLayout)
        widgets = [central_layout.itemAt(i).widget() for i in range(central_layout.count())]
        preset_idx = next(i for i, w in enumerate(widgets) if isinstance(w, PresetBarWidget))
        tabs_idx = next(i for i, w in enumerate(widgets) if isinstance(w, QTabWidget))
        assert tabs_idx == preset_idx + 1
        assert win._tabs.currentIndex() == 0
        assert win._tabs.tabText(0) == "Instruments"
        assert win._tabs.tabText(1) == "A/B Comparison"
        assert win._ab_panel.isAncestorOf(win._tabs.widget(1)) is False
        assert win._tabs.widget(1).isAncestorOf(win._ab_panel) is True

        # 2. Before loading composition, A/B controls are disabled
        card_a = win._ab_panel.slot_card("A")
        card_b = win._ab_panel.slot_card("B")
        assert card_a._save_btn.isEnabled() is False
        assert card_b._save_btn.isEnabled() is False
        assert win._ab_panel._switch_btn.isEnabled() is False

        # Forbid rendering throughout Save/Load/Preset sync checks
        monkeypatch.setattr(
            RenderService,
            "render_preview",
            lambda *_a, **_kw: (_ for _ in ()).throw(AssertionError("Save/Load must never auto-render!")),
        )

        # 3. Load composition and Save independent snapshots into A and B
        win.load_composition_file(SONG_8BIT)
        base_fp = win.state.musical_fingerprint  # type: ignore[union-attr]

        win.set_channel_instrument(1, "lead_pure_sustain")
        win.set_channel_instrument(4, "perc_kick_tight")
        st_a = win.save_comparison_slot("A")
        assert st_a is not None and st_a.render_status == "not_rendered"
        assert st_a.matches_editor is True
        cfg_a_expected = win.working_config.model_copy(deep=True)

        # Edit editor -> A keeps its snapshot and switches to 'Differs from editor'
        win.set_channel_instrument(1, "lead_attack_bite")
        win._player_ver_combo.setCurrentIndex(win._player_ver_combo.findData("v2"))
        win._pc_policy_combo.setCurrentIndex(win._pc_policy_combo.findData("remove"))
        win._target_combo.setCurrentIndex(win._target_combo.findData("wav"))
        qapp.processEvents()

        assert win.comparison_session.get_variant("A").config == cfg_a_expected  # type: ignore[union-attr]
        assert card_a._match_label.text() == "Differs from editor"

        st_b = win.save_comparison_slot("B")
        assert st_b is not None and st_b.matches_editor is True
        cfg_b_expected = win.working_config.model_copy(deep=True)
        assert cfg_a_expected != cfg_b_expected

        # 4. Save invalid configuration (v1 player on v2 features) -> allowed on Save, Render B blocked
        win._player_ver_combo.setCurrentIndex(win._player_ver_combo.findData("v1"))
        qapp.processEvents()
        st_b_invalid = win.save_comparison_slot("B")
        assert st_b_invalid is not None and st_b_invalid.is_valid_arrangement is False
        assert card_b._render_btn.isEnabled() is False
        assert "Blocked:" in card_b._detail_label.text()

        # Restore B to valid cfg_b_expected, then Load A -> syncs ALL ChannelStrips + combos without rendering
        win._working_config = cfg_b_expected
        win.save_comparison_slot("B")
        loaded_a = win.load_comparison_slot("A")
        qapp.processEvents()
        assert loaded_a == cfg_a_expected
        assert win.working_config == cfg_a_expected
        assert win._channel_strips[1]._combo.currentData() == "lead_pure_sustain"
        assert win._channel_strips[4]._combo.currentData() == "perc_kick_tight"
        assert win._pc_policy_combo.currentData() == cfg_a_expected.program_change_policy
        assert win._player_ver_combo.currentData() == cfg_a_expected.player_version
        assert win._target_combo.currentData() == cfg_a_expected.target_backend
        assert card_a._match_label.text() == "Matches editor"
        assert card_b._match_label.text() == "Differs from editor"

        # Switching editor to B via Load B preserves A cleanly
        assert win.load_comparison_slot("B") == cfg_b_expected
        qapp.processEvents()
        assert card_a._match_label.text() == "Differs from editor"
        assert card_b._match_label.text() == "Matches editor"
        assert win.state.musical_fingerprint == base_fp  # type: ignore[union-attr]
    finally:
        win.close()


def test_ab_unified_serialized_render_queue_cache_and_identical_variants(
    qapp: QApplication,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    backend = _FakeABAudioBackend()
    win = MainWindow(audio_backend=backend, presets_dir=tmp_path / "presets")

    render_calls: list[tuple[Optional[str], str]] = []
    active_workers = 0
    max_concurrent = 0
    lock = threading.Lock()
    release_first_worker = threading.Event()
    first_worker_entered = threading.Event()
    call_idx = 0

    def _controlled_render(self: RenderService, state, config):
        nonlocal active_workers, max_concurrent, call_idx
        key = self.build_cache_key(state, config).digest()
        with lock:
            call_idx += 1
            my_idx = call_idx
            active_workers += 1
            max_concurrent = max(max_concurrent, active_workers)
            render_calls.append((config.channel_instruments.get(1), key))
        try:
            if my_idx == 1:
                first_worker_entered.set()
                assert release_first_worker.wait(timeout=10.0)
            wav_p = self.cache_dir / f"{key}.wav"
            _write_pcm_wav(wav_p, duration_s=1.0 + 0.1 * my_idx, freq_hz=440.0 + 50.0 * my_idx)
            from atari_music.studio.models import CachedRenderEntry

            entry = CachedRenderEntry(
                cache_key=key,
                wav_path=wav_p,
                duration_seconds=1.0 + 0.1 * my_idx,
                format_version=2,
                uses_16bit_bass=False,
                memory_size_bytes=512,
                config=config,
                arranged_ir_sha256=f"ir_{my_idx}",
                from_cache=False,
            )
            self._cache[key] = entry
            return entry
        finally:
            with lock:
                active_workers -= 1

    monkeypatch.setattr(RenderService, "render_preview", _controlled_render)

    try:
        win.load_composition_file(SONG_8BIT)

        # Save A (lead_pure_sustain), B1 (lead_attack_bite) -> replaced by B2 (bass_15khz_pure) while queued
        win.set_channel_instrument(1, "lead_pure_sustain")
        win.save_comparison_slot("A")
        cfg_a = win.working_config.model_copy(deep=True)

        win.set_channel_instrument(1, "lead_attack_bite")
        win.save_comparison_slot("B")

        win.set_channel_instrument(1, "bass_15khz_pure")
        cfg_ed = win.working_config.model_copy(deep=True)

        # Enqueue Render A (blocks on worker 1), then queue Render B (B1), then re-save B as B_new (lead_pure_pluck)
        win.render_comparison_slot("A")
        assert first_worker_entered.wait(timeout=5.0)
        win.render_comparison_slot("B")
        win._working_config = cfg_a.with_channel(1, "lead_pure_pluck")
        win.save_comparison_slot("B")  # drops queued old B job
        win.render_comparison_slot("B")  # queues updated B job

        # Also queue Editor Preview behind Render A and Render B (all 3 in ONE serialized queue!)
        win._working_config = cfg_ed
        win._reevaluate_and_refresh_ui()
        win.render_current_preview()
        assert win._is_rendering is True

        # Unblock worker 1 -> queue drains FIFO cleanly with max_concurrent == 1: A -> B(updated) -> Editor
        release_first_worker.set()
        _wait_until(
            qapp,
            lambda: (
                win._active_render_job is None
                and not win._pending_render_queue
                and not win._is_rendering
            ),
        )

        assert max_concurrent == 1
        assert [ch1 for ch1, _ in render_calls] == ["lead_pure_sustain", "lead_pure_pluck", "bass_15khz_pure"]
        assert win.comparison_session.slot_status("A", state=win.state).render_status == "ready"
        assert win.comparison_session.slot_status("B", state=win.state).render_status == "ready"
        assert win.last_rendered_entry is not None and win.last_rendered_entry.config == cfg_ed
        assert win.active_listen_slot is None
        assert win.active_listen_entry is None

        # Switch to Listen A and confirm Render B does NOT disturb playback or _last_rendered_entry
        assert win.listen_comparison_slot("A") is True
        assert win.active_listen_slot == "A"
        assert win._transport.audio_player.is_playing() is True
        active_wav_during_listen_a = win._transport._loaded_wav
        ed_before = win.last_rendered_entry

        # Re-save B with same config as A -> instant cache hit, zero worker invoked, shares identical WAV file!
        calls_before = len(render_calls)
        win._working_config = cfg_a
        win.save_comparison_slot("B")
        st_b_shared = win.comparison_session.slot_status("B", state=win.state)
        assert st_b_shared.render_status == "ready"
        assert st_b_shared.variant.rendered_entry.wav_path == active_wav_during_listen_a  # type: ignore[union-attr]
        win.render_comparison_slot("B")
        assert len(render_calls) == calls_before  # zero extra render calls!
        assert win.last_rendered_entry is ed_before
        assert win.active_listen_slot == "A"
        assert win._transport._loaded_wav == active_wav_during_listen_a
        assert win._transport.audio_player.is_playing() is True
    finally:
        release_first_worker.set()
        win.close()


def test_ab_stale_worker_results_generation_and_b1_b2_b1_recovery(
    qapp: QApplication,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    win = MainWindow(audio_backend=_FakeABAudioBackend(), presets_dir=tmp_path / "presets")

    def _stub_entry(cfg, wav_path: Path, key: str):
        from atari_music.studio.models import CachedRenderEntry

        _write_pcm_wav(wav_path, duration_s=1.5)
        return CachedRenderEntry(
            cache_key=key,
            wav_path=wav_path,
            duration_seconds=1.5,
            format_version=2,
            uses_16bit_bass=False,
            memory_size_bytes=512,
            config=cfg,
            arranged_ir_sha256="ir_stub",
        )

    try:
        win.load_composition_file(SONG_8BIT)
        cfg_b1 = win.working_config.with_channel(1, "lead_pure_sustain")
        cfg_b2 = win.working_config.with_channel(1, "lead_attack_bite")

        key_b1 = win._render_service.build_cache_key(win.state, cfg_b1).digest()
        entry_b1 = _stub_entry(cfg_b1, tmp_path / "b1.wav", key_b1)
        win._working_config = cfg_b1
        win.save_comparison_slot("B")

        # 1. Simulate in-flight worker B1 -> slot overwritten by B2 -> stale B1 arrives -> MUST be rejected!
        from atari_music.studio.ui.main_window import _RenderJob

        job_b1 = _RenderJob(
            request_id=9001,
            target="B",
            composition_generation=win._composition_generation,
            composition_sha256=win.state.base_ir_sha256,  # type: ignore[union-attr]
            state=win.state,  # type: ignore[arg-type]
            config=cfg_b1,
            expected_cache_key=key_b1,
        )
        win._render_jobs_by_id[9001] = job_b1
        win._active_render_job = job_b1

        win._working_config = cfg_b2
        win.save_comparison_slot("B")
        win._on_render_finished(9001, entry_b1)
        st_b_after_mismatch = win.comparison_session.slot_status("B", state=win.state)
        assert st_b_after_mismatch.render_status == "not_rendered"

        # 2. Special case B1 -> B2 -> B1 before worker B1 completes -> valid B1 accepted!
        win._render_jobs_by_id[9002] = _RenderJob(
            request_id=9002,
            target="B",
            composition_generation=win._composition_generation,
            composition_sha256=win.state.base_ir_sha256,  # type: ignore[union-attr]
            state=win.state,  # type: ignore[arg-type]
            config=cfg_b1,
            expected_cache_key=key_b1,
        )
        win._working_config = cfg_b2
        win.save_comparison_slot("B")
        win._working_config = cfg_b1
        win.save_comparison_slot("B")
        win._on_render_finished(9002, entry_b1)
        st_b_recovered = win.comparison_session.slot_status("B", state=win.state)
        assert st_b_recovered.render_status == "ready"
        assert st_b_recovered.variant.rendered_entry.wav_path == entry_b1.wav_path  # type: ignore[union-attr]

        # 3. Open new composition while a job from previous generation finishes late -> ignored safely!
        old_gen = win._composition_generation
        old_state = win.state
        win._render_jobs_by_id[9003] = _RenderJob(
            request_id=9003,
            target="editor",
            composition_generation=old_gen,
            composition_sha256=old_state.base_ir_sha256,  # type: ignore[union-attr]
            state=old_state,  # type: ignore[arg-type]
            config=cfg_b1,
            expected_cache_key=key_b1,
        )
        win.load_composition_file(SONG_16BIT)
        assert win._composition_generation > old_gen
        assert win.comparison_session.get_variant("A") is None
        assert win.comparison_session.get_variant("B") is None
        assert win.active_listen_slot is None
        assert win.last_rendered_entry is None

        win._on_render_finished(9003, entry_b1)
        assert win.last_rendered_entry is None
        assert win._transport._loaded_wav is None
        assert win.comparison_session.get_variant("B") is None
    finally:
        win.close()


def test_ab_listen_switch_state_preservation_and_entry_separation(
    qapp: QApplication,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    backend = _FakeABAudioBackend(buffer_ms=100)
    win = MainWindow(audio_backend=backend, presets_dir=tmp_path / "presets")

    wav_a = _write_pcm_wav(tmp_path / "slot_a_3s.wav", duration_s=3.0, freq_hz=440.0)
    wav_b = _write_pcm_wav(tmp_path / "slot_b_1s.wav", duration_s=1.0, freq_hz=660.0)
    wav_ed = _write_pcm_wav(tmp_path / "editor_2s.wav", duration_s=2.0, freq_hz=550.0)

    from atari_music.studio.models import CachedRenderEntry

    def _entry(cfg, path: Path, dur: float, key: str) -> CachedRenderEntry:
        e = CachedRenderEntry(
            cache_key=key,
            wav_path=path,
            duration_seconds=dur,
            format_version=2,
            uses_16bit_bass=False,
            memory_size_bytes=512,
            config=cfg,
            arranged_ir_sha256=f"ir_{key}",
        )
        win._render_service._cache[key] = e
        return e

    # Switch/Listen/Render Guard: zero render_preview invocations allowed
    monkeypatch.setattr(
        RenderService,
        "render_preview",
        lambda *_a, **_kw: (_ for _ in ()).throw(AssertionError("Listen/Switch must not trigger render_preview!")),
    )

    try:
        win.load_composition_file(SONG_8BIT)
        cfg_a = win.working_config.with_channel(1, "lead_pure_sustain")
        cfg_b = win.working_config.with_channel(1, "lead_attack_bite")
        cfg_ed = win.working_config.with_channel(1, "bass_15khz_pure")

        key_a = win._render_service.build_cache_key(win.state, cfg_a).digest()
        key_b = win._render_service.build_cache_key(win.state, cfg_b).digest()
        key_ed = win._render_service.build_cache_key(win.state, cfg_ed).digest()

        entry_a = _entry(cfg_a, wav_a, 3.0, key_a)
        entry_b = _entry(cfg_b, wav_b, 1.0, key_b)
        entry_ed = _entry(cfg_ed, wav_ed, 2.0, key_ed)

        # Save A & B (cache hits promote both to Ready without rendering)
        win._working_config = cfg_a
        win.save_comparison_slot("A")
        win._working_config = cfg_b
        win.save_comparison_slot("B")

        # Run Editor Render Preview (cache hit) -> sets _last_rendered_entry, active_listen stays None
        win._working_config = cfg_ed
        win._reevaluate_and_refresh_ui()
        win.render_current_preview()
        assert win.last_rendered_entry is not None
        assert win.last_rendered_entry.cache_key == entry_ed.cache_key
        assert win.active_listen_slot is None
        assert win.active_listen_entry is None

        # Listen A -> switches transport to A, _last_rendered_entry untouched!
        assert win.listen_comparison_slot("A") is True
        assert win.active_listen_slot == "A"
        assert win.active_listen_entry is not None and win.active_listen_entry.wav_path == wav_a
        assert win.last_rendered_entry.cache_key == entry_ed.cache_key
        assert win._transport.audio_player.is_playing() is True

        # Advance A past 1.0s (e.g. 2200 ms) and Switch A/B -> clamps to shorter B (1000 - 100 = 900 ms), keeps Playing!
        win._transport.seek(2200)
        assert win.switch_ab_listen() is True
        assert win.active_listen_slot == "B"
        assert win.active_listen_entry.wav_path == wav_b
        assert win.last_rendered_entry.cache_key == entry_ed.cache_key
        assert win._transport.audio_player.is_playing() is True
        assert 850 <= win._transport.audio_player.position() <= 900

        # Pause B -> Switch A/B back to A -> preserves Paused at ~900 ms WITHOUT calling backend.start()!
        win._transport.pause()
        paused_pos = win._transport.audio_player.position()
        starts_before = backend.start_calls
        assert win.switch_ab_listen() is True
        assert backend.start_calls == starts_before
        assert win.active_listen_slot == "A"
        assert win._transport.audio_player.is_paused() is True
        assert abs(win._transport.audio_player.position() - paused_pos) <= 2

        # Failed switch to missing WAV B preserves active listen A and playback!
        wav_b.unlink()
        assert win.listen_comparison_slot("B") is False
        assert win.active_listen_slot == "A"
        assert win.comparison_session.active_listen_slot == "A"
        assert win.active_listen_entry.wav_path == wav_a
        assert win._transport._loaded_wav == wav_a
        assert win._transport.audio_player.is_paused() is True

        # Unrendered/empty target on Switch cannot auto-render or steal active listen
        win._working_config = cfg_a.with_channel(3, "harmony_soft_square")
        win.save_comparison_slot("B")
        assert win.switch_ab_listen() is False
        assert win.active_listen_slot == "A"
    finally:
        win.close()


def test_ab_composition_reload_and_window_close_worker_teardown(
    qapp: QApplication,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    backend = _FakeABAudioBackend()
    win = MainWindow(audio_backend=backend, presets_dir=tmp_path / "presets")

    worker_started = threading.Event()
    allow_worker_finish = threading.Event()
    worker_exited = threading.Event()

    def _slow_render(self: RenderService, state, config):
        from atari_music.studio.models import CachedRenderEntry

        key = self.build_cache_key(state, config).digest()
        worker_started.set()
        allow_worker_finish.wait(timeout=10.0)
        try:
            return CachedRenderEntry(
                cache_key=key,
                wav_path=tmp_path / f"{key}.wav",
                duration_seconds=1.0,
                format_version=2,
                uses_16bit_bass=False,
                memory_size_bytes=256,
                config=config,
                arranged_ir_sha256="ir_late",
            )
        finally:
            worker_exited.set()

    monkeypatch.setattr(RenderService, "render_preview", _slow_render)

    win.load_composition_file(SONG_8BIT)
    win.set_channel_instrument(1, "lead_pure_sustain")
    win.save_comparison_slot("A")
    win.render_comparison_slot("A")
    assert worker_started.wait(timeout=5.0)

    # Close MainWindow cleanly WHILE background A worker is still running!
    win.close()
    assert win._closing is True
    assert win._pending_render_queue == deque()
    assert win._transport.audio_player.is_loaded() is False

    # Now let the worker finish after window shutdown and pump Qt events -> must NOT crash or mutate session!
    allow_worker_finish.set()
    assert worker_exited.wait(timeout=5.0)
    qapp.processEvents()
    assert win.comparison_session.get_variant("A") is None or (
        win.comparison_session.get_variant("A").rendered_entry is None  # type: ignore[union-attr]
    )
    assert win.active_listen_slot is None
    assert win.active_listen_entry is None


def test_ab_preset_apply_live_composition_swap_and_render_failure_isolation(
    qapp: QApplication,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    backend = _FakeABAudioBackend(buffer_ms=100)
    win = MainWindow(audio_backend=backend, presets_dir=tmp_path / "presets")

    wav_b = _write_pcm_wav(tmp_path / "slot_b_ready.wav", duration_s=1.5, freq_hz=520.0)
    worker1_started = threading.Event()
    release_worker1 = threading.Event()
    fail_render_a = False

    def _custom_render(self: RenderService, state, config):
        key = self.build_cache_key(state, config).digest()
        if fail_render_a and config.channel_instruments.get(1) == "lead_pure_sustain":
            raise RuntimeError("Simulated Variant A synth failure")
        if state.base_ir_sha256 == sha_song1:
            worker1_started.set()
            release_worker1.wait(timeout=10.0)
        wav_p = self.cache_dir / f"{key}.wav"
        _write_pcm_wav(wav_p, duration_s=1.0, freq_hz=440.0)
        entry = CachedRenderEntry(
            cache_key=key,
            wav_path=wav_p,
            duration_seconds=1.0,
            format_version=2,
            uses_16bit_bass=False,
            memory_size_bytes=512,
            config=config,
            arranged_ir_sha256=f"ir_{key}",
        )
        self._cache[key] = entry
        return entry

    try:
        win.load_composition_file(SONG_8BIT)
        sha_song1 = win.state.base_ir_sha256  # type: ignore[union-attr]

        # 1. Save Preset and verify PresetBar Apply updates editor & A/B matches_editor WITHOUT altering slots or rendering
        win.set_channel_instrument(1, "lead_pure_sustain")
        win.save_comparison_slot("A")
        cfg_a = win.working_config.model_copy(deep=True)
        win.save_current_preset("Slot A Preset", overwrite=True)

        win.set_channel_instrument(1, "lead_attack_bite")
        assert win._ab_panel.slot_card("A")._match_label.text() == "Differs from editor"
        win.load_preset("slot-a-preset")
        win.apply_loaded_preset()
        qapp.processEvents()
        assert win.working_config == cfg_a
        assert win._ab_panel.slot_card("A")._match_label.text() == "Matches editor"

        # 2. Invalid variant (v1 player with v2 perc_snare_crisp) refuses programmatic render_comparison_slot cleanly
        win.set_channel_instrument(4, "perc_snare_crisp")
        win._player_ver_combo.setCurrentIndex(win._player_ver_combo.findData("v1"))
        qapp.processEvents()
        win.save_comparison_slot("B")
        win.render_comparison_slot("B")
        assert win._active_render_job is None
        assert "Cannot render Variant B" in win._ab_panel._status_label.text()

        # Restore valid A & ready cached B; start active Listen B playback, then fail Render A -> Listen B stays alive!
        win._working_config = cfg_a
        win._reevaluate_and_refresh_ui()
        win.save_comparison_slot("A")

        cfg_b = StudioArrangementConfig(
            channel_instruments={1: "bass_15khz_pure", 2: "harmony_soft_square", 3: None, 4: None}
        )
        win._working_config = cfg_b
        win._reevaluate_and_refresh_ui()
        win.save_comparison_slot("B")
        key_b = win._render_service.build_cache_key(win.state, cfg_b).digest()
        win._render_service._cache[key_b] = CachedRenderEntry(
            cache_key=key_b,
            wav_path=wav_b,
            duration_seconds=1.5,
            format_version=2,
            uses_16bit_bass=False,
            memory_size_bytes=512,
            config=cfg_b,
            arranged_ir_sha256="ir_b_live",
        )
        win.comparison_session.sync_from_cache(win.state)
        assert win.listen_comparison_slot("B") is True
        assert win.active_listen_slot == "B"
        assert win._transport.audio_player.is_playing() is True

        fail_render_a = True
        monkeypatch.setattr(RenderService, "render_preview", _custom_render)
        # Ensure SONG_8BIT worker for A raises immediately instead of waiting on event
        sha_song1 = "__skip_wait__"
        win.render_comparison_slot("A")
        _wait_until(qapp, lambda: win._active_render_job is None and not win._pending_render_queue)
        assert "Render A failed" in win._ab_panel._status_label.text()
        assert win.active_listen_slot == "B"
        assert win._transport._loaded_wav == wav_b
        assert win._transport.audio_player.is_playing() is True

        # 3. Real live background worker on SONG_8BIT interrupted by opening SONG_16BIT:
        # global cache preserves B's cache entry while session resets cleanly and stale result is ignored!
        fail_render_a = False
        sha_song1 = win.state.base_ir_sha256  # type: ignore[union-attr]
        win.render_comparison_slot("A")
        assert worker1_started.wait(timeout=5.0)

        win.load_composition_file(SONG_16BIT)
        assert win.comparison_session.get_variant("A") is None
        assert win.comparison_session.get_variant("B") is None
        assert win.active_listen_slot is None
        # Global cache was NOT wiped by load_composition_file
        assert key_b in win._render_service._cache

        # Release old worker -> finishes safely without altering SONG_16BIT session or transport
        release_worker1.set()
        _wait_until(qapp, lambda: not win._open_workers)
        qapp.processEvents()
        assert win.comparison_session.get_variant("A") is None
        assert win._transport._loaded_wav is None
    finally:
        release_worker1.set()
        win.close()


def test_tab_workspace_layout_geometry_and_state_continuity(
    qapp: QApplication,
    tmp_path: Path,
) -> None:
    backend = _FakeABAudioBackend(buffer_ms=100)
    win = MainWindow(audio_backend=backend, presets_dir=tmp_path / "presets")
    wav_a = _write_pcm_wav(tmp_path / "tab_switch_a.wav", duration_s=2.0, freq_hz=440.0)
    try:
        # 1. Verify all 4 tabs and default active Instruments tab
        tab_titles = [win._tabs.tabText(i) for i in range(win._tabs.count())]
        assert tab_titles == ["Instruments", "A/B Comparison", "Arrangement", "Diagnostics"]
        assert win._tabs.currentIndex() == 0

        # Open composition -> Instruments tab remains active default
        win.load_composition_file(SONG_16BIT)
        assert win._tabs.currentIndex() == 0

        # Populate A/B + playback + validation diagnostics
        win.save_comparison_slot("A")
        cfg_a = win.working_config.model_copy(deep=True)
        key_a = win._render_service.build_cache_key(win.state, cfg_a).digest()
        win._render_service._cache[key_a] = CachedRenderEntry(
            cache_key=key_a,
            wav_path=wav_a,
            duration_seconds=2.0,
            format_version=2,
            uses_16bit_bass=True,
            memory_size_bytes=512,
            config=cfg_a,
            arranged_ir_sha256="ir_tab_a",
        )
        win.comparison_session.sync_from_cache(win.state)
        assert win.listen_comparison_slot("A") is True
        win._transport.seek(600)
        pos_before_switch = win._transport.audio_player.position()

        # Verify global controls, A/B state, and active audio playback persist across ALL tabs
        win.show()
        for tab_idx in (1, 2, 3, 0):
            win._tabs.setCurrentIndex(tab_idx)
            qapp.processEvents()
            assert win._open_btn.isVisible() is True
            assert win._revert_btn.isVisible() is True
            assert win._render_btn.isVisible() is True
            assert win._export_xex_btn.isVisible() is True
            assert win._preset_bar.isVisible() is True
            assert win._transport.isVisible() is True
            assert win._transport.audio_player.is_playing() is True
            assert win._transport.audio_player.position() >= pos_before_switch
            assert win.active_listen_slot == "A"
            assert win.comparison_session.get_variant("A") is not None

        # Switching to Diagnostics tab exposes populated hardware warnings & channel summaries
        win._tabs.setCurrentIndex(3)
        qapp.processEvents()
        diag_text = win._diag_details.toPlainText()
        assert "=== Validation & Hardware Warnings ===" in diag_text
        assert "=== Channel Compatibility (CH1-CH4) ===" in diag_text

        # Real widget geometry checks at 1366x768, 1120x1026 (clamped by display if needed), and 900x680
        central = win.centralWidget()
        for target_w, target_h in ((1366, 768), (1120, 1026), (900, 680)):
            win.resize(target_w, target_h)
            qapp.processEvents()
            c_rect = central.rect()
            assert central.width() <= target_w + 20
            for ctrl in (
                win._open_btn,
                win._revert_btn,
                win._render_btn,
                win._export_xex_btn,
                win._preset_bar,
                win._tabs,
                win._transport,
            ):
                assert ctrl.isVisible() is True
                tl = ctrl.mapTo(central, ctrl.rect().topLeft())
                br = ctrl.mapTo(central, ctrl.rect().bottomRight())
                assert tl.x() >= 0 and tl.y() >= 0
                assert br.x() <= c_rect.width() + 1
                assert br.y() <= c_rect.height() + 1

            # Verify A/B Comparison controls stay visible on tab 1 even in 900x680 restricted view
            win._tabs.setCurrentIndex(1)
            qapp.processEvents()
            assert win._ab_panel.slot_card("A")._save_btn.isVisible() is True
            assert win._ab_panel.slot_card("B")._listen_btn.isVisible() is True
            assert win._render_btn.isVisible() is True
            assert win._transport.isVisible() is True
            win._tabs.setCurrentIndex(0)
            qapp.processEvents()
    finally:
        win.close()

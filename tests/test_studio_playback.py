"""Tests for Phase 3 Stage 2 standalone PCM StudioAudioPlayer (deterministic + real QAudioSink)."""

from __future__ import annotations

import math
import os
from pathlib import Path
import struct
from typing import Callable, Iterable, List, Optional, Set
import wave

import pytest

PySide6 = pytest.importorskip("PySide6")

from PySide6.QtCore import QIODevice  # noqa: E402
from PySide6.QtMultimedia import QAudioFormat, QMediaDevices  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from atari_music.studio.ui.audio_player import (  # noqa: E402
    AUDIO_ERR_EMPTY_WAV,
    AUDIO_ERR_FILE_NOT_FOUND,
    AUDIO_ERR_INVALID_WAV,
    AUDIO_ERR_NO_DEVICE,
    AUDIO_ERR_SINK_INIT,
    AUDIO_ERR_UNSUPPORTED_DEVICE_FORMAT,
    AUDIO_ERR_UNSUPPORTED_WAV,
    AudioPlaybackError,
    DualPcmStreamDevice,
    PcmFormatSpec,
    QtAudio,
    StudioAudioPlayer,
    WavPcmData,
    convert_pcm_data,
    load_wav_pcm,
    negotiate_device_format,
)

pytestmark = pytest.mark.core


@pytest.fixture(scope="module")
def qapp():
    if "QT_QPA_PLATFORM" not in os.environ:
        os.environ["QT_QPA_PLATFORM"] = "offscreen"
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    yield app


def _write_pcm_wav(
    path: Path,
    *,
    sample_rate: int = 44100,
    channels: int = 1,
    sample_width: int = 2,
    duration_s: float = 1.0,
    freq_hz: float = 440.0,
    tag_bytes: Optional[bytes] = None,
) -> Path:
    frame_count = max(1, int(round(sample_rate * duration_s)))
    if tag_bytes is not None:
        raw = tag_bytes
    else:
        buf = bytearray()
        for i in range(frame_count):
            val = int(round(0.35 * 32767.0 * math.sin(2.0 * math.pi * freq_hz * (i / sample_rate))))
            for _ in range(channels):
                if sample_width == 1:
                    u8 = max(0, min(255, (val >> 8) + 128))
                    buf.append(u8)
                elif sample_width == 2:
                    buf.extend(struct.pack("<h", val))
                elif sample_width == 3:
                    val24 = val << 8
                    buf.extend(int(val24).to_bytes(3, "little", signed=True))
                elif sample_width == 4:
                    buf.extend(struct.pack("<i", val << 16))
        raw = bytes(buf)

    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(channels)
        wf.setsampwidth(sample_width)
        wf.setframerate(sample_rate)
        wf.writeframes(raw)
    return path


class FakeAudioSinkBackend:
    """Realistic in-memory sink backend mirroring QAudioSink buffering, suspend/resume, reset, and EOF."""

    def __init__(
        self,
        *,
        has_device: bool = True,
        supported_specs: Optional[Iterable[PcmFormatSpec]] = None,
        buffer_ms: int = 200,
        fail_on_init: bool = False,
        fail_on_start: bool = False,
    ) -> None:
        self.has_device = has_device
        self.supported_specs: Optional[Set[PcmFormatSpec]] = (
            set(supported_specs) if supported_specs is not None else None
        )
        self.buffer_ms = int(buffer_ms)
        self.fail_on_init = fail_on_init
        self.fail_on_start = fail_on_start

        self._callback: Optional[Callable[[QtAudio.State, QtAudio.Error], None]] = None
        self._stream: Optional[DualPcmStreamDevice] = None
        self._spec: Optional[PcmFormatSpec] = None
        self._state: QtAudio.State = QtAudio.State.StoppedState
        self._error: QtAudio.Error = QtAudio.Error.NoError
        self._buffer_size_bytes: int = 0
        self._queued_chunks: bytearray = bytearray()
        self._processed_bytes: int = 0
        self._volume: float = 1.0
        self.reset_calls: int = 0
        self.start_calls: int = 0
        self.suspend_calls: int = 0
        self.resume_calls: int = 0
        self.stop_calls: int = 0
        self.release_calls: int = 0
        self.played_bytes: bytearray = bytearray()

    def has_output_device(self) -> bool:
        return self.has_device

    def set_state_callback(self, callback: Callable[[QtAudio.State, QtAudio.Error], None]) -> None:
        self._callback = callback

    def negotiate_and_prepare(self, wav: WavPcmData, stream: DualPcmStreamDevice) -> PcmFormatSpec:
        if not self.has_device:
            raise AudioPlaybackError("No audio output device available.", code=AUDIO_ERR_NO_DEVICE)
        if self.fail_on_init:
            raise AudioPlaybackError("Simulated sink init failure.", code=AUDIO_ERR_SINK_INIT)

        if self.supported_specs is None:
            spec = negotiate_device_format(wav, is_supported_fn=lambda _s: True)
        else:
            spec = negotiate_device_format(wav, is_supported_fn=lambda s: s in self.supported_specs)

        pcm = convert_pcm_data(wav, spec)
        if not stream.isOpen():
            stream.open(QIODevice.OpenModeFlag.ReadOnly | QIODevice.OpenModeFlag.Unbuffered)
        stream.set_pcm_data(pcm, spec.frame_bytes)
        self._spec = spec
        self._stream = stream
        raw_buf = int(round((spec.bytes_per_second * self.buffer_ms) / 1000.0))
        self._buffer_size_bytes = max(spec.frame_bytes, (raw_buf // spec.frame_bytes) * spec.frame_bytes)
        self._queued_chunks.clear()
        self._processed_bytes = 0
        self._error = QtAudio.Error.NoError
        self._state = QtAudio.State.StoppedState
        return spec

    def _emit_state(self, st: QtAudio.State, err: QtAudio.Error = QtAudio.Error.NoError) -> None:
        self._state = st
        self._error = err
        if self._callback is not None:
            self._callback(st, err)

    def _fill_from_stream(self) -> None:
        if self._stream is None or self._buffer_size_bytes <= 0:
            return
        space = self._buffer_size_bytes - len(self._queued_chunks)
        if space > 0 and not self._stream.atEnd():
            chunk = self._stream.read(space)
            if chunk:
                self._queued_chunks.extend(chunk)

    def start(self, stream: DualPcmStreamDevice) -> None:
        if self.fail_on_start:
            raise AudioPlaybackError("Simulated sink start failure.", code=AUDIO_ERR_SINK_INIT)
        self.start_calls += 1
        self._stream = stream
        self._processed_bytes = 0
        self._queued_chunks.clear()
        self._fill_from_stream()
        self._emit_state(QtAudio.State.ActiveState)

    def advance_ms(self, delta_ms: int) -> None:
        """Advance hardware clock by *delta_ms*, draining buffer and pulling next PCM frames."""
        if self._state != QtAudio.State.ActiveState or self._spec is None:
            return
        step_bytes = int(round((delta_ms * self._spec.bytes_per_second) / 1000.0))
        step_bytes = (step_bytes // self._spec.frame_bytes) * self._spec.frame_bytes
        if step_bytes <= 0:
            return

        remaining_to_consume = step_bytes
        while remaining_to_consume > 0:
            self._fill_from_stream()
            if not self._queued_chunks:
                break
            take = min(remaining_to_consume, len(self._queued_chunks))
            self.played_bytes.extend(self._queued_chunks[:take])
            del self._queued_chunks[:take]
            self._processed_bytes += take
            remaining_to_consume -= take

        self._fill_from_stream()
        if not self._queued_chunks and (self._stream is None or self._stream.atEnd()):
            self._emit_state(QtAudio.State.IdleState)

    def trigger_underrun_idle(self) -> None:
        """Simulate transient IdleState while stream still has unread bytes."""
        self._emit_state(QtAudio.State.IdleState, QtAudio.Error.UnderrunError)

    def trigger_fatal_error(self) -> None:
        self._emit_state(QtAudio.State.StoppedState, QtAudio.Error.IOError)

    def suspend(self) -> None:
        self.suspend_calls += 1
        if self._state == QtAudio.State.ActiveState:
            self._emit_state(QtAudio.State.SuspendedState)

    def resume(self) -> None:
        self.resume_calls += 1
        if self._state == QtAudio.State.SuspendedState:
            self._emit_state(QtAudio.State.ActiveState)

    def stop(self) -> None:
        self.stop_calls += 1
        self._queued_chunks.clear()
        self._emit_state(QtAudio.State.StoppedState)

    def reset(self) -> None:
        self.reset_calls += 1
        self._queued_chunks.clear()
        self._processed_bytes = 0
        self._state = QtAudio.State.StoppedState

    def processed_usecs(self) -> int:
        if self._spec is None or self._spec.bytes_per_second <= 0:
            return 0
        return int(round((self._processed_bytes * 1_000_000.0) / self._spec.bytes_per_second))

    def buffer_size(self) -> int:
        return self._buffer_size_bytes

    def bytes_free(self) -> int:
        return max(0, self._buffer_size_bytes - len(self._queued_chunks))

    def state(self) -> QtAudio.State:
        return self._state

    def error(self) -> QtAudio.Error:
        return self._error

    def set_volume(self, volume: float) -> None:
        self._volume = volume

    def release(self) -> None:
        self.release_calls += 1
        self._queued_chunks.clear()
        self._processed_bytes = 0
        self._state = QtAudio.State.StoppedState


# ===========================================================================
# Group A: Deterministic tests (FakeAudioSinkBackend — zero hardware needed)
# ===========================================================================


def test_load_wav_validation_and_immediate_handle_release(qapp: QApplication, tmp_path: Path) -> None:
    wav_ok = _write_pcm_wav(tmp_path / "ok.wav", sample_rate=44100, channels=1, sample_width=2, duration_s=1.0)
    backend = FakeAudioSinkBackend()
    player = StudioAudioPlayer(backend=backend)
    try:
        assert player.load(wav_ok) is True
        assert player.is_loaded() is True
        assert player.duration() == 1000
        assert player.position() == 0

        # File handle MUST already be closed so Windows unlink/rename succeeds immediately even while playing!
        assert player.play() is True
        renamed = tmp_path / "renamed.wav"
        os.replace(wav_ok, renamed)
        assert renamed.is_file() and not wav_ok.exists()
        renamed.unlink()
        assert not renamed.exists()
    finally:
        player.release()

    # Error cases
    with pytest.raises(AudioPlaybackError) as exc_missing:
        load_wav_pcm(tmp_path / "missing.wav")
    assert exc_missing.value.code == AUDIO_ERR_FILE_NOT_FOUND

    bad_wav = tmp_path / "bad.wav"
    bad_wav.write_text("not a wav file", encoding="utf-8")
    with pytest.raises(AudioPlaybackError) as exc_bad:
        load_wav_pcm(bad_wav)
    assert exc_bad.value.code == AUDIO_ERR_INVALID_WAV

    empty_wav = tmp_path / "empty.wav"
    with wave.open(str(empty_wav), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(44100)
        wf.writeframes(b"")
    with pytest.raises(AudioPlaybackError) as exc_empty:
        load_wav_pcm(empty_wav)
    assert exc_empty.value.code == AUDIO_ERR_EMPTY_WAV

    # Corrupt frame alignment (5 bytes for 4-byte stereo 16-bit frame)
    corrupt_wav = tmp_path / "corrupt_align.wav"
    _write_pcm_wav(corrupt_wav, channels=2, sample_width=2, tag_bytes=b"\x01\x02\x03\x04\x05")
    with pytest.raises(AudioPlaybackError) as exc_corrupt:
        load_wav_pcm(corrupt_wav)
    assert exc_corrupt.value.code == AUDIO_ERR_INVALID_WAV

    # Unsupported 64-bit sample width (crafted minimal RIFF/WAVE PCM header)
    unsupported_wav = tmp_path / "64bit.wav"
    pcm_dummy = b"\x00" * 16
    fmt_chunk = struct.pack("<4sIHHIIHH", b"fmt ", 16, 1, 1, 44100, 44100 * 8, 8, 64)
    data_chunk = struct.pack("<4sI", b"data", len(pcm_dummy)) + pcm_dummy
    riff_body = b"WAVE" + fmt_chunk + data_chunk
    unsupported_wav.write_bytes(struct.pack("<4sI", b"RIFF", len(riff_body)) + riff_body)
    with pytest.raises(AudioPlaybackError) as exc_unsup:
        load_wav_pcm(unsupported_wav)
    assert exc_unsup.value.code == AUDIO_ERR_UNSUPPORTED_WAV


def test_pcm_stream_device_never_reads_or_seeks_partial_frames(qapp: QApplication) -> None:
    stream = DualPcmStreamDevice()
    stream.open(QIODevice.OpenModeFlag.ReadOnly | QIODevice.OpenModeFlag.Unbuffered)
    # 3 frames of 4 bytes each = 12 bytes, plus 2 trailing partial bytes ignored on load
    raw = b"AAAABBBBCCCCXX"
    stream.set_pcm_data(raw, frame_bytes=4)
    assert stream.size() == 12

    # Unaligned seek rounds down to frame boundary
    assert stream.seek(7) is True
    assert stream.pos() == 4

    # Asking for less than one full frame returns empty; asking for 7 returns 4 (1 full frame)
    assert bytes(stream.read(3)) == b""
    assert bytes(stream.read(7)) == b"BBBB"
    assert stream.pos() == 8
    assert bytes(stream.read(8)) == b"CCCC"
    assert stream.is_exhausted() is True
    stream.close()


def test_format_negotiation_zero_copy_native_and_safe_resampling(qapp: QApplication, tmp_path: Path) -> None:
    wav_mono_44k = _write_pcm_wav(tmp_path / "mono44k.wav", sample_rate=44100, channels=1, sample_width=2, duration_s=0.5)
    wav_24bit = _write_pcm_wav(tmp_path / "mono24bit.wav", sample_rate=22050, channels=1, sample_width=3, duration_s=0.5)

    # Case 1: Native format supported -> zero conversion
    backend_native = FakeAudioSinkBackend(
        supported_specs=[PcmFormatSpec(44100, 1, 2, "Int16")]
    )
    player_native = StudioAudioPlayer(backend=backend_native)
    assert player_native.load(wav_mono_44k) is True
    assert player_native.active_format() == PcmFormatSpec(44100, 1, 2, "Int16")
    assert player_native._stream.size() == load_wav_pcm(wav_mono_44k).frame_count * 2
    player_native.release()

    # Case 2: Device supports ONLY 48kHz stereo Int16 -> converts & resamples cleanly preserving duration
    stereo_48k = PcmFormatSpec(48000, 2, 2, "Int16")
    backend_conv = FakeAudioSinkBackend(supported_specs=[stereo_48k])
    player_conv = StudioAudioPlayer(backend=backend_conv)
    assert player_conv.load(wav_mono_44k) is True
    assert player_conv.active_format() == stereo_48k
    assert abs(player_conv.duration() - 500) <= 5
    player_conv.release()

    # Case 3: 24-bit WAV converted cleanly to supported Int16
    stereo_44k = PcmFormatSpec(44100, 2, 2, "Int16")
    backend_24 = FakeAudioSinkBackend(supported_specs=[stereo_44k])
    player_24 = StudioAudioPlayer(backend=backend_24)
    assert player_24.load(wav_24bit) is True
    assert player_24.active_format() == stereo_44k
    assert abs(player_24.duration() - 500) <= 5
    player_24.release()

    # Case 4: Unsupported format combination -> clean error signal, no crash
    backend_bad = FakeAudioSinkBackend(supported_specs=[PcmFormatSpec(96000, 8, 4, "Float")])
    player_bad = StudioAudioPlayer(backend=backend_bad)
    errors: List[str] = []
    player_bad.error_occurred.connect(errors.append)
    assert player_bad.load(wav_mono_44k) is False
    assert errors and AUDIO_ERR_UNSUPPORTED_DEVICE_FORMAT in errors[0]


def test_device_errors_and_missing_device_handled_cleanly(qapp: QApplication, tmp_path: Path) -> None:
    wav_p = _write_pcm_wav(tmp_path / "tone.wav", duration_s=0.5)

    for kwargs, expected_code in (
        ({"has_device": False}, AUDIO_ERR_NO_DEVICE),
        ({"fail_on_init": True}, AUDIO_ERR_SINK_INIT),
    ):
        backend = FakeAudioSinkBackend(**kwargs)
        player = StudioAudioPlayer(backend=backend)
        errs: List[str] = []
        player.error_occurred.connect(errs.append)
        assert player.load(wav_p) is False
        assert player.is_loaded() is False
        assert errs and expected_code in errs[0]
        assert expected_code in (player.last_error() or "")

    # Runtime start error
    backend_start = FakeAudioSinkBackend(fail_on_start=True)
    player_start = StudioAudioPlayer(backend=backend_start)
    errs_start: List[str] = []
    player_start.error_occurred.connect(errs_start.append)
    assert player_start.load(wav_p) is True
    assert player_start.play() is False
    assert errs_start and AUDIO_ERR_SINK_INIT in errs_start[0]

    # Hardware I/O error mid-playback stops cleanly
    backend_io = FakeAudioSinkBackend()
    player_io = StudioAudioPlayer(backend=backend_io)
    io_errs: List[str] = []
    player_io.error_occurred.connect(io_errs.append)
    assert player_io.load(wav_p) is True
    assert player_io.play() is True
    backend_io.trigger_fatal_error()
    assert player_io.is_playing() is False
    assert io_errs


def test_three_position_metrics_pause_resume_seek_stop_and_eof(qapp: QApplication, tmp_path: Path) -> None:
    # Build two distinct 2-byte PCM halves so we can prove post-seek audio contains ZERO pre-seek frames!
    half_frames = 44100  # 1.0s first half, 1.0s second half -> 2.0s total
    first_half = struct.pack("<h", 1111) * half_frames
    second_half = struct.pack("<h", 22222) * half_frames
    wav_p = _write_pcm_wav(
        tmp_path / "distinct_halves.wav",
        sample_rate=44100,
        channels=1,
        sample_width=2,
        tag_bytes=first_half + second_half,
    )

    backend = FakeAudioSinkBackend(buffer_ms=200)
    player = StudioAudioPlayer(backend=backend)
    eof_events: List[int] = []
    states: List[str] = []
    player.end_of_media.connect(lambda: eof_events.append(1))
    player.playback_state_changed.connect(states.append)

    assert player.load(wav_p) is True
    assert player.duration() == 2000

    # 1. Seek while stopped (before Play)
    assert player.seek(400) == 400
    assert player.position() == 400
    assert player.playback_state() == "stopped"

    # 2. Play from 400 ms and advance 300 ms: read_position leads processed, audible <= processed
    assert player.play() is True
    backend.advance_ms(300)
    read_ms = player.read_position()
    proc_ms = player.processed_position()
    audible_ms = player.position()
    assert read_ms > proc_ms
    assert 400 <= audible_ms <= proc_ms
    # Audible position lags by buffered queue (200 ms) so UI never systematically leads audio!
    assert audible_ms == pytest.approx(500, abs=5)

    # 3. Pause freezes exact audible position and uses suspend(); Resume continues smoothly
    player.pause()
    assert player.is_paused() is True
    assert backend.suspend_calls == 1
    frozen = player.position()
    backend.advance_ms(500)  # must be ignored while suspended
    assert player.position() == frozen

    assert player.resume() is True
    assert backend.resume_calls == 1
    assert player.is_playing() is True

    # 4. Seek while paused -> MUST reset sink buffer so post-resume audio has zero pre-seek samples!
    player.pause()
    backend.played_bytes.clear()
    res_seek = player.seek(1200)  # well into second half (value 22222)
    assert res_seek == 1200
    assert backend.reset_calls >= 1
    assert player.is_paused() is True
    assert player.position() == 1200
    assert player.resume() is True
    backend.advance_ms(100)
    resumed_samples = struct.unpack("<" + "h" * (len(backend.played_bytes) // 2), backend.played_bytes)
    assert all(s == 22222 for s in resumed_samples)

    # 5. Seek while playing -> resets sink buffer before restarting at new offset
    prev_resets = backend.reset_calls
    backend.played_bytes.clear()
    assert player.seek(1500) == 1500
    assert backend.reset_calls > prev_resets
    backend.advance_ms(100)
    seek_play_samples = struct.unpack("<" + "h" * (len(backend.played_bytes) // 2), backend.played_bytes)
    assert all(s == 22222 for s in seek_play_samples)

    # 6. Transient IdleState / underrun when stream NOT exhausted MUST NOT trigger EOF!
    player.seek(200)
    backend.trigger_underrun_idle()
    assert player.is_playing() is True
    assert eof_events == []

    # 7. Stop returns to 0 ms and does NOT emit EOF
    player.stop()
    assert player.playback_state() == "stopped"
    assert player.position() == 0
    assert eof_events == []

    # 8. Genuine EOF reaches duration(), emits end_of_media, and subsequent Play starts from 0 ms!
    player.seek(1800)
    assert player.play() is True
    backend.advance_ms(300)  # exhausts remaining 200 ms + buffer
    assert eof_events == [1]
    assert player.playback_state() == "stopped"
    assert player.at_end() is True
    assert player.position() == 2000

    # Replay after EOF starts cleanly from beginning (0 ms)
    backend.played_bytes.clear()
    assert player.play() is True
    assert player.at_end() is False
    backend.advance_ms(100)
    replayed = struct.unpack("<" + "h" * (len(backend.played_bytes) // 2), backend.played_bytes)
    assert all(s == 1111 for s in replayed)

    # 9. Multiple load() / release() cycles remain clean
    wav_2 = _write_pcm_wav(tmp_path / "second.wav", duration_s=0.4)
    assert player.load(wav_2) is True
    assert player.duration() == 400
    assert player.position() == 0
    player.release()
    player.release()
    assert player.is_loaded() is False


def test_prepare_paused_at_never_starts_sink_aligns_resumes_and_cleans_up(
    qapp: QApplication,
    tmp_path: Path,
) -> None:
    # Distinct sample halves across stereo channels (4 bytes per frame): first half=1111, second half=22222
    wav_path = tmp_path / "paused_prep.wav"
    sr = 44100
    half_frames = sr  # 1.0 s per half -> 2.0 s total
    frames_bytes = (struct.pack("<hh", 1111, -1111) * half_frames) + (
        struct.pack("<hh", 22222, -22222) * half_frames
    )
    with wave.open(str(wav_path), "wb") as wf:
        wf.setnchannels(2)
        wf.setsampwidth(2)
        wf.setframerate(sr)
        wf.writeframes(frames_bytes)

    backend = FakeAudioSinkBackend(buffer_ms=150)
    player = StudioAudioPlayer(backend=backend)
    states: List[str] = []
    positions: List[int] = []
    player.playback_state_changed.connect(states.append)
    player.position_changed.connect(positions.append)

    try:
        assert player.load(wav_path) is True
        states.clear()
        positions.clear()

        # 1. prepare_paused_at sets paused without EVER calling sink.start() and aligns to 4-byte stereo frame
        aligned = player.prepare_paused_at(1253)
        assert backend.start_calls == 0
        assert backend.played_bytes == bytearray()
        assert player.playback_state() == "paused"
        assert player.is_paused() is True
        assert player._stream.pos() % 4 == 0
        assert player.position() == aligned
        assert player.processed_position() == aligned
        assert states == ["paused"]
        assert positions == [aligned]

        # 2. Repeated seek() after prepare_paused_at keeps start_calls == 0 and updates paused cursor cleanly
        seek1 = player.seek(400)
        seek2 = player.seek(1400)
        assert backend.start_calls == 0
        assert seek1 == 400 and seek2 == 1400
        assert player.position() == 1400
        assert player.is_paused() is True

        # 3. Calling prepare_paused_at again leaves zero stale state or duplicate "paused" signals
        states.clear()
        aligned2 = player.prepare_paused_at(1150)
        assert backend.start_calls == 0
        assert aligned2 == 1150
        assert player.position() == 1150
        assert states == []  # already paused, no spurious signal bounce

        # 4. resume() starts sink strictly at the prepared second-half PCM offset (samples == +/-22222)
        assert player.resume() is True
        assert backend.start_calls == 1
        assert player.is_playing() is True
        backend.advance_ms(80)
        samples = struct.unpack("<" + "h" * (len(backend.played_bytes) // 2), backend.played_bytes)
        assert len(samples) > 0
        assert all(abs(s) == 22222 for s in samples)

        # 5. Calling prepare_paused_at from playing stops & resets sink cleanly without calling start()
        starts_before = backend.start_calls
        resets_before = backend.reset_calls
        player.prepare_paused_at(200)
        assert backend.start_calls == starts_before
        assert backend.reset_calls > resets_before
        assert player.is_paused() is True
        assert player.position() == 200

        # 6. stop() after prepare_paused_at resets to 0 ms and next play starts from 0 ms (samples +/-1111)
        player.stop()
        assert player.playback_state() == "stopped"
        assert player.position() == 0
        assert player._pending_restart_from_pause is False
        backend.played_bytes.clear()
        assert player.play() is True
        backend.advance_ms(60)
        restarted = struct.unpack("<" + "h" * (len(backend.played_bytes) // 2), backend.played_bytes)
        assert all(abs(s) == 1111 for s in restarted)

        # 7. release() after prepare_paused_at cleans up completely
        player.prepare_paused_at(900)
        releases_before = backend.release_calls
        player.release()
        assert backend.release_calls > releases_before
        assert player.is_loaded() is False
        assert player.playback_state() == "stopped"
    finally:
        player.release()


# ===========================================================================
# Group B: Real QAudioSink integration tests (skipped only when OS has no audio device)
# ===========================================================================


def _has_real_audio_device() -> bool:
    app = QApplication.instance()
    if app is None:
        return False
    return not QMediaDevices.defaultAudioOutput().isNull()


def _spin_qt_ms(app: QApplication, ms: int) -> None:
    import time

    deadline = time.monotonic() + (ms / 1000.0)
    while time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.01)


def test_real_qaudiosink_playback_pause_seek_eof_and_file_unlock(
    qapp: QApplication,
    tmp_path: Path,
) -> None:
    if not _has_real_audio_device():
        pytest.skip("No physical/virtual audio output device available in environment")

    wav_long = _write_pcm_wav(tmp_path / "real_long.wav", duration_s=1.2)
    wav_short = _write_pcm_wav(tmp_path / "real_short.wav", duration_s=0.35)

    player = StudioAudioPlayer()
    player.set_volume(0.0)
    errs: List[str] = []
    eof_hits: List[int] = []
    player.error_occurred.connect(errs.append)
    player.end_of_media.connect(lambda: eof_hits.append(1))
    try:
        # 1. Load and immediately remove file on disk while playing (zero Windows WinError 32!)
        assert player.load(wav_long) is True
        assert player.duration() == 1200
        wav_long.unlink()
        assert not wav_long.exists()

        # 2. Play, Pause, Seek while paused, Resume, Seek while playing, Stop
        assert player.play() is True
        _spin_qt_ms(qapp, 250)
        assert player.is_playing() is True

        player.pause()
        assert player.is_paused() is True
        paused_pos = player.position()
        _spin_qt_ms(qapp, 120)
        assert player.position() == paused_pos

        assert player.seek(700) == 700
        assert player.is_paused() is True
        assert player.position() == 700
        assert player.resume() is True
        _spin_qt_ms(qapp, 150)

        assert player.seek(900) == 900
        assert player.is_playing() is True
        assert player.position() >= 900

        player.stop()
        assert player.playback_state() == "stopped"
        assert player.position() == 0

        # 3. Natural EOF on short WAV + Replay from 0
        assert player.load(wav_short) is True
        assert player.play() is True
        _spin_qt_ms(qapp, 950)
        assert len(eof_hits) == 1
        assert player.playback_state() == "stopped"
        assert player.position() == player.duration()

        assert player.play() is True
        assert player.is_playing() is True
        player.stop()
        assert errs == []
    finally:
        player.release()
        qapp.processEvents()

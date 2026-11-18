"""Self-contained PCM audio playback engine built on QAudioSink and QIODevice (zero QMediaPlayer)."""

from __future__ import annotations

import array
from dataclasses import dataclass
from pathlib import Path
import struct
import sys
from typing import Callable, List, Optional, Protocol, Tuple
import wave

from PySide6.QtCore import QMutex, QMutexLocker, QObject, QIODevice, QTimer, Signal, Slot
from PySide6.QtMultimedia import QAudioDevice, QAudioFormat, QAudioSink, QMediaDevices

try:
    from PySide6.QtMultimedia import QtAudio
except ImportError:  # Qt < 6.7 compatibility fallback
    from PySide6.QtMultimedia import QAudio as QtAudio  # type: ignore[no-redef]

AUDIO_ERR_FILE_NOT_FOUND = "FILE_NOT_FOUND"
AUDIO_ERR_FILE_READ = "FILE_READ_ERROR"
AUDIO_ERR_INVALID_WAV = "INVALID_WAV"
AUDIO_ERR_EMPTY_WAV = "EMPTY_WAV"
AUDIO_ERR_UNSUPPORTED_WAV = "UNSUPPORTED_WAV"
AUDIO_ERR_NO_DEVICE = "NO_AUDIO_DEVICE"
AUDIO_ERR_UNSUPPORTED_DEVICE_FORMAT = "UNSUPPORTED_DEVICE_FORMAT"
AUDIO_ERR_SINK_INIT = "AUDIO_SINK_ERROR"

_SUPPORTED_SAMPLE_FORMATS: Tuple[Tuple[str, QAudioFormat.SampleFormat], ...] = (
    ("Int16", QAudioFormat.SampleFormat.Int16),
    ("Int32", QAudioFormat.SampleFormat.Int32),
    ("Float", QAudioFormat.SampleFormat.Float),
    ("UInt8", QAudioFormat.SampleFormat.UInt8),
)


class AudioPlaybackError(ValueError):
    """Structured error raised when loading, negotiating, or playing WAV PCM audio."""

    def __init__(self, message: str, *, code: str) -> None:
        super().__init__(f"[{code}] {message}")
        self.code = code


@dataclass(frozen=True)
class PcmFormatSpec:
    """Explicit PCM stream format negotiated for an audio output backend."""

    sample_rate: int
    channels: int
    sample_width: int  # bytes per sample per channel (1, 2, or 4)
    sample_format_name: str  # "UInt8", "Int16", "Int32", or "Float"

    @property
    def frame_bytes(self) -> int:
        return self.channels * self.sample_width

    @property
    def bytes_per_second(self) -> int:
        return self.sample_rate * self.frame_bytes


@dataclass(frozen=True)
class WavPcmData:
    """In-memory PCM payload decoded and validated from a closed WAV file."""

    path: Path
    sample_rate: int
    channels: int
    sample_width: int  # original WAV sample width in bytes (1, 2, 3, or 4)
    pcm_bytes: bytes
    frame_bytes: int
    frame_count: int
    duration_ms: int


def _inspect_wav_data_chunk_size(raw_bytes: bytes) -> Optional[int]:
    """Return raw RIFF 'data' chunk byte size if present in *raw_bytes*, else None."""
    if len(raw_bytes) < 12 or raw_bytes[:4] != b"RIFF" or raw_bytes[8:12] != b"WAVE":
        return None
    offset = 12
    total = len(raw_bytes)
    while offset + 8 <= total:
        chunk_id = raw_bytes[offset : offset + 4]
        (chunk_size,) = struct.unpack_from("<I", raw_bytes, offset + 4)
        payload_start = offset + 8
        if chunk_id == b"data":
            return min(chunk_size, max(0, total - payload_start))
        # RIFF chunks are word-aligned (padded to even byte boundary)
        offset = payload_start + chunk_size + (chunk_size & 1)
    return None


def load_wav_pcm(source: Path | str) -> WavPcmData:
    """Read and validate uncompressed PCM frames from *source*, closing the file handle immediately."""
    path = Path(source)
    if not path.is_file():
        raise AudioPlaybackError(f"WAV file not found: '{path}'.", code=AUDIO_ERR_FILE_NOT_FOUND)

    try:
        raw_bytes = path.read_bytes()
        with wave.open(str(path), "rb") as wf:
            comptype = wf.getcomptype()
            channels = int(wf.getnchannels())
            sample_width = int(wf.getsampwidth())
            sample_rate = int(wf.getframerate())
            reported_frames = int(wf.getnframes())
            pcm_bytes = wf.readframes(reported_frames)
    except (wave.Error, EOFError) as exc:
        raise AudioPlaybackError(
            f"Malformed or non-WAV file '{path}': {exc}",
            code=AUDIO_ERR_INVALID_WAV,
        ) from exc
    except OSError as exc:
        raise AudioPlaybackError(
            f"Failed to read WAV file '{path}': {exc}",
            code=AUDIO_ERR_FILE_READ,
        ) from exc

    if comptype != "NONE":
        raise AudioPlaybackError(
            f"Unsupported compressed WAV codec {comptype!r}; only uncompressed PCM is supported.",
            code=AUDIO_ERR_UNSUPPORTED_WAV,
        )
    if channels < 1 or channels > 8:
        raise AudioPlaybackError(
            f"Unsupported WAV channel count {channels}; expected 1..8.",
            code=AUDIO_ERR_UNSUPPORTED_WAV,
        )
    if sample_rate <= 0:
        raise AudioPlaybackError(
            f"Invalid WAV sample rate {sample_rate} Hz.",
            code=AUDIO_ERR_INVALID_WAV,
        )
    if sample_width not in (1, 2, 3, 4):
        raise AudioPlaybackError(
            f"Unsupported WAV sample width {sample_width * 8}-bit; expected 8, 16, 24, or 32-bit PCM.",
            code=AUDIO_ERR_UNSUPPORTED_WAV,
        )

    frame_bytes = channels * sample_width
    data_chunk_size = _inspect_wav_data_chunk_size(raw_bytes)
    if data_chunk_size is not None and (data_chunk_size % frame_bytes != 0):
        raise AudioPlaybackError(
            f"Corrupt WAV PCM payload in '{path}': data chunk size {data_chunk_size} bytes "
            f"is not a multiple of {frame_bytes}-byte frame.",
            code=AUDIO_ERR_INVALID_WAV,
        )

    if not pcm_bytes:
        raise AudioPlaybackError(
            f"WAV file '{path}' contains zero audio frames.",
            code=AUDIO_ERR_EMPTY_WAV,
        )

    if len(pcm_bytes) % frame_bytes != 0 or len(pcm_bytes) != reported_frames * frame_bytes:
        raise AudioPlaybackError(
            f"Corrupt WAV PCM payload in '{path}': {len(pcm_bytes)} bytes does not match "
            f"{reported_frames} frames of {frame_bytes} bytes.",
            code=AUDIO_ERR_INVALID_WAV,
        )

    actual_frames = len(pcm_bytes) // frame_bytes
    duration_ms = int(round((actual_frames * 1000.0) / sample_rate))
    return WavPcmData(
        path=path,
        sample_rate=sample_rate,
        channels=channels,
        sample_width=sample_width,
        pcm_bytes=pcm_bytes,
        frame_bytes=frame_bytes,
        frame_count=actual_frames,
        duration_ms=max(1, duration_ms),
    )


def _decode_samples_normalized(
    pcm_bytes: bytes,
    channels: int,
    sample_width: int,
) -> List[List[float]]:
    """Decode little-endian PCM bytes into per-channel float streams in [-1.0, 1.0]."""
    frame_bytes = channels * sample_width
    frame_count = len(pcm_bytes) // frame_bytes
    per_ch: List[List[float]] = [[] for _ in range(channels)]

    if sample_width == 1:
        # 8-bit WAV PCM is unsigned [0..255], center at 128
        for idx in range(frame_count):
            base = idx * frame_bytes
            for c in range(channels):
                per_ch[c].append((pcm_bytes[base + c] - 128) / 128.0)
        return per_ch

    if sample_width == 2:
        arr = array.array("h")
        arr.frombytes(pcm_bytes)
        if sys.byteorder != "little":
            arr.byteswap()
        for idx in range(frame_count):
            base = idx * channels
            for c in range(channels):
                per_ch[c].append(arr[base + c] / 32768.0)
        return per_ch

    if sample_width == 3:
        for idx in range(frame_count):
            base = idx * frame_bytes
            for c in range(channels):
                off = base + c * 3
                val = int.from_bytes(pcm_bytes[off : off + 3], "little", signed=True)
                per_ch[c].append(val / 8388608.0)
        return per_ch

    arr32 = array.array("i")
    arr32.frombytes(pcm_bytes)
    if sys.byteorder != "little":
        arr32.byteswap()
    for idx in range(frame_count):
        base = idx * channels
        for c in range(channels):
            per_ch[c].append(arr32[base + c] / 2147483648.0)
    return per_ch


def _remap_channels(per_ch: List[List[float]], dst_channels: int) -> List[List[float]]:
    src_channels = len(per_ch)
    if src_channels == dst_channels:
        return per_ch
    frame_count = len(per_ch[0]) if per_ch else 0
    if dst_channels == 1:
        mono = [
            sum(per_ch[c][i] for c in range(src_channels)) / src_channels
            for i in range(frame_count)
        ]
        return [mono]
    if src_channels == 1:
        return [list(per_ch[0]) for _ in range(dst_channels)]
    if dst_channels <= src_channels:
        return [list(per_ch[c]) for c in range(dst_channels)]
    out = [list(per_ch[c]) for c in range(src_channels)]
    while len(out) < dst_channels:
        out.append(list(per_ch[len(out) % src_channels]))
    return out


def _resample_linear(per_ch: List[List[float]], src_rate: int, dst_rate: int) -> List[List[float]]:
    if src_rate == dst_rate or not per_ch or not per_ch[0]:
        return per_ch
    src_frames = len(per_ch[0])
    dst_frames = max(1, int(round(src_frames * (dst_rate / src_rate))))
    ratio = src_rate / dst_rate
    out: List[List[float]] = []
    for ch_samples in per_ch:
        resampled: List[float] = []
        last = src_frames - 1
        for i in range(dst_frames):
            pos = i * ratio
            lo = int(pos)
            if lo >= last:
                resampled.append(ch_samples[last])
            else:
                frac = pos - lo
                s0 = ch_samples[lo]
                s1 = ch_samples[lo + 1]
                resampled.append(s0 + (s1 - s0) * frac)
        out.append(resampled)
    return out


def _encode_samples_from_normalized(
    per_ch: List[List[float]],
    sample_format_name: str,
) -> bytes:
    channels = len(per_ch)
    frames = len(per_ch[0]) if per_ch else 0

    def _clamp(v: float) -> float:
        return -1.0 if v < -1.0 else (1.0 if v > 1.0 else v)

    if sample_format_name == "UInt8":
        out_b = bytearray(frames * channels)
        idx = 0
        for i in range(frames):
            for c in range(channels):
                val = int(round(_clamp(per_ch[c][i]) * 127.0)) + 128
                out_b[idx] = max(0, min(255, val))
                idx += 1
        return bytes(out_b)

    if sample_format_name == "Int16":
        arr = array.array("h", [0] * (frames * channels))
        idx = 0
        for i in range(frames):
            for c in range(channels):
                val = int(round(_clamp(per_ch[c][i]) * 32767.0))
                arr[idx] = max(-32768, min(32767, val))
                idx += 1
        if sys.byteorder != "little":
            arr.byteswap()
        return arr.tobytes()

    if sample_format_name == "Int32":
        arr32 = array.array("i", [0] * (frames * channels))
        idx = 0
        for i in range(frames):
            for c in range(channels):
                val = int(round(_clamp(per_ch[c][i]) * 2147483647.0))
                arr32[idx] = max(-2147483648, min(2147483647, val))
                idx += 1
        if sys.byteorder != "little":
            arr32.byteswap()
        return arr32.tobytes()

    if sample_format_name == "Float":
        arrf = array.array("f", [0.0] * (frames * channels))
        idx = 0
        for i in range(frames):
            for c in range(channels):
                arrf[idx] = float(_clamp(per_ch[c][i]))
                idx += 1
        if sys.byteorder != "little":
            arrf.byteswap()
        return arrf.tobytes()

    raise AudioPlaybackError(
        f"Unsupported output sample format {sample_format_name!r}.",
        code=AUDIO_ERR_UNSUPPORTED_DEVICE_FORMAT,
    )


def convert_pcm_data(
    wav: WavPcmData,
    target_format: PcmFormatSpec,
) -> bytes:
    """Convert *wav* PCM data into *target_format* using stdlib integer/float math only."""
    native_format_name = {1: "UInt8", 2: "Int16", 4: "Int32"}.get(wav.sample_width)
    if (
        native_format_name == target_format.sample_format_name
        and wav.sample_rate == target_format.sample_rate
        and wav.channels == target_format.channels
    ):
        # Zero-copy fast path: device supports original PCM verbatim.
        return wav.pcm_bytes

    per_ch = _decode_samples_normalized(wav.pcm_bytes, wav.channels, wav.sample_width)
    per_ch = _remap_channels(per_ch, target_format.channels)
    per_ch = _resample_linear(per_ch, wav.sample_rate, target_format.sample_rate)
    return _encode_samples_from_normalized(per_ch, target_format.sample_format_name)


def to_qaudio_format(spec: PcmFormatSpec) -> QAudioFormat:
    """Build a ``QAudioFormat`` matching *spec*."""
    fmt = QAudioFormat()
    fmt.setSampleRate(int(spec.sample_rate))
    fmt.setChannelCount(int(spec.channels))
    qt_fmt_map = {name: qfmt for name, qfmt in _SUPPORTED_SAMPLE_FORMATS}
    fmt.setSampleFormat(qt_fmt_map[spec.sample_format_name])
    return fmt


def spec_from_qaudio_format(fmt: QAudioFormat) -> Optional[PcmFormatSpec]:
    """Convert a ``QAudioFormat`` into ``PcmFormatSpec`` if supported by stdlib PCM codec."""
    name_map = {qfmt: name for name, qfmt in _SUPPORTED_SAMPLE_FORMATS}
    width_map = {"UInt8": 1, "Int16": 2, "Int32": 4, "Float": 4}
    fmt_name = name_map.get(fmt.sampleFormat())
    if fmt_name is None or fmt.sampleRate() <= 0 or fmt.channelCount() <= 0:
        return None
    return PcmFormatSpec(
        sample_rate=int(fmt.sampleRate()),
        channels=int(fmt.channelCount()),
        sample_width=width_map[fmt_name],
        sample_format_name=fmt_name,
    )


def negotiate_device_format(
    wav: WavPcmData,
    *,
    is_supported_fn: Callable[[PcmFormatSpec], bool],
    preferred_spec: Optional[PcmFormatSpec] = None,
) -> PcmFormatSpec:
    """Choose native PCM format if supported, otherwise fall back to safest compatible format."""
    native_name = {1: "UInt8", 2: "Int16", 4: "Int32"}.get(wav.sample_width)
    candidates: List[PcmFormatSpec] = []
    if native_name is not None:
        candidates.append(
            PcmFormatSpec(
                sample_rate=wav.sample_rate,
                channels=wav.channels,
                sample_width=wav.sample_width,
                sample_format_name=native_name,
            )
        )

    # Prefer same sample rate before resampling, trying common widths & stereo/mono
    for ch in (wav.channels, 2, 1):
        for fmt_name, width in (("Int16", 2), ("Int32", 4), ("Float", 4), ("UInt8", 1)):
            cand = PcmFormatSpec(
                sample_rate=wav.sample_rate,
                channels=ch,
                sample_width=width,
                sample_format_name=fmt_name,
            )
            if cand not in candidates:
                candidates.append(cand)

    if preferred_spec is not None and preferred_spec not in candidates:
        candidates.append(preferred_spec)

    for rate in (48000, 44100, 22050):
        for ch in (wav.channels, 2, 1):
            cand = PcmFormatSpec(
                sample_rate=rate,
                channels=ch,
                sample_width=2,
                sample_format_name="Int16",
            )
            if cand not in candidates:
                candidates.append(cand)

    for cand in candidates:
        if is_supported_fn(cand):
            return cand

    raise AudioPlaybackError(
        f"Audio output device does not support WAV format "
        f"({wav.sample_rate} Hz, {wav.channels} ch, {wav.sample_width * 8}-bit PCM) "
        f"or fallback PCM formats.",
        code=AUDIO_ERR_UNSUPPORTED_DEVICE_FORMAT,
    )


class DualPcmStreamDevice(QIODevice):
    """Random-access in-memory PCM ``QIODevice`` enforcing strict frame-aligned reads and seeks."""

    def __init__(self, parent: Optional[QObject] = None) -> None:
        super().__init__(parent)
        self._mutex = QMutex()
        self._data: bytes = b""
        self._frame_bytes: int = 2
        self._offset: int = 0

    def set_pcm_data(self, pcm_bytes: bytes, frame_bytes: int) -> None:
        """Replace active PCM buffer atomically, aligning data length and resetting offset to 0."""
        if frame_bytes <= 0:
            raise ValueError(f"frame_bytes must be >= 1, got {frame_bytes}")
        with QMutexLocker(self._mutex):
            aligned_len = (len(pcm_bytes) // frame_bytes) * frame_bytes
            self._data = pcm_bytes[:aligned_len]
            self._frame_bytes = int(frame_bytes)
            self._offset = 0
        super().seek(0)

    def clear_pcm(self) -> None:
        with QMutexLocker(self._mutex):
            self._data = b""
            self._offset = 0
        super().seek(0)

    def isSequential(self) -> bool:
        return False

    def size(self) -> int:
        with QMutexLocker(self._mutex):
            return len(self._data)

    def pos(self) -> int:
        with QMutexLocker(self._mutex):
            return self._offset

    def atEnd(self) -> bool:
        with QMutexLocker(self._mutex):
            return self._offset >= len(self._data)

    def is_exhausted(self) -> bool:
        """Return True iff the stream has bytes and all full PCM frames have been read."""
        with QMutexLocker(self._mutex):
            return len(self._data) > 0 and self._offset >= len(self._data)

    def frame_bytes(self) -> int:
        with QMutexLocker(self._mutex):
            return self._frame_bytes

    def align_byte_offset(self, byte_offset: int) -> int:
        with QMutexLocker(self._mutex):
            clamped = max(0, min(int(byte_offset), len(self._data)))
            return (clamped // self._frame_bytes) * self._frame_bytes

    def bytesAvailable(self) -> int:
        with QMutexLocker(self._mutex):
            rem = max(0, len(self._data) - self._offset)
        return rem + super().bytesAvailable()

    def seek(self, pos: int) -> bool:
        with QMutexLocker(self._mutex):
            clamped = max(0, min(int(pos), len(self._data)))
            aligned = (clamped // self._frame_bytes) * self._frame_bytes
            self._offset = aligned
        return super().seek(aligned)

    def readData(self, maxlen: int) -> bytes:
        with QMutexLocker(self._mutex):
            rem = len(self._data) - self._offset
            if rem <= 0 or maxlen <= 0:
                return b""
            n = min(rem, int(maxlen))
            # Never split a multi-byte PCM frame across read boundaries.
            n = (n // self._frame_bytes) * self._frame_bytes
            if n <= 0:
                return b""
            chunk = self._data[self._offset : self._offset + n]
            self._offset += n
            return chunk

    def writeData(self, _data: object, _len: int) -> int:
        return -1


class AudioSinkBackend(Protocol):
    """Minimal hardware-abstracting sink protocol separating Qt audio I/O from player state."""

    def has_output_device(self) -> bool: ...
    def negotiate_and_prepare(self, wav: WavPcmData, stream: DualPcmStreamDevice) -> PcmFormatSpec: ...
    def set_state_callback(self, callback: Callable[[QtAudio.State, QtAudio.Error], None]) -> None: ...
    def start(self, stream: DualPcmStreamDevice) -> None: ...
    def suspend(self) -> None: ...
    def resume(self) -> None: ...
    def stop(self) -> None: ...
    def reset(self) -> None: ...
    def processed_usecs(self) -> int: ...
    def buffer_size(self) -> int: ...
    def bytes_free(self) -> int: ...
    def state(self) -> QtAudio.State: ...
    def error(self) -> QtAudio.Error: ...
    def set_volume(self, volume: float) -> None: ...
    def release(self) -> None: ...


class QtAudioSinkBackend(QObject):
    """Production ``QAudioSink`` backend using ``QMediaDevices.defaultAudioOutput()``."""

    def __init__(self, parent: Optional[QObject] = None) -> None:
        super().__init__(parent)
        self._sink: Optional[QAudioSink] = None
        self._callback: Optional[Callable[[QtAudio.State, QtAudio.Error], None]] = None
        self._volume: float = 1.0

    def has_output_device(self) -> bool:
        return not QMediaDevices.defaultAudioOutput().isNull()

    def set_state_callback(self, callback: Callable[[QtAudio.State, QtAudio.Error], None]) -> None:
        self._callback = callback

    def negotiate_and_prepare(self, wav: WavPcmData, stream: DualPcmStreamDevice) -> PcmFormatSpec:
        device: QAudioDevice = QMediaDevices.defaultAudioOutput()
        if device.isNull():
            raise AudioPlaybackError(
                "No audio output device is available on this system.",
                code=AUDIO_ERR_NO_DEVICE,
            )

        preferred = spec_from_qaudio_format(device.preferredFormat())
        target_spec = negotiate_device_format(
            wav,
            is_supported_fn=lambda spec: device.isFormatSupported(to_qaudio_format(spec)),
            preferred_spec=preferred,
        )
        pcm_payload = convert_pcm_data(wav, target_spec)

        # Ensure any previous sink is stopped and detached before deleting or changing stream data.
        self._destroy_sink()

        if not stream.isOpen():
            stream.open(QIODevice.OpenModeFlag.ReadOnly | QIODevice.OpenModeFlag.Unbuffered)
        stream.set_pcm_data(pcm_payload, target_spec.frame_bytes)

        qt_fmt = to_qaudio_format(target_spec)
        try:
            sink = QAudioSink(device, qt_fmt, self)
        except Exception as exc:  # noqa: BLE001
            raise AudioPlaybackError(
                f"Failed to initialize QAudioSink: {exc}",
                code=AUDIO_ERR_SINK_INIT,
            ) from exc

        if sink.error() != QtAudio.Error.NoError:
            err = sink.error()
            sink.deleteLater()
            raise AudioPlaybackError(
                f"Audio device failed during sink initialization ({err}).",
                code=AUDIO_ERR_SINK_INIT,
            )

        sink.setVolume(self._volume)
        sink.stateChanged.connect(self._on_sink_state_changed)
        self._sink = sink
        return target_spec

    @Slot(QtAudio.State)
    def _on_sink_state_changed(self, new_state: QtAudio.State) -> None:
        if self._callback is not None:
            err = self._sink.error() if self._sink is not None else QtAudio.Error.NoError
            self._callback(new_state, err)

    def start(self, stream: DualPcmStreamDevice) -> None:
        if self._sink is None:
            raise AudioPlaybackError("Audio sink is not initialized.", code=AUDIO_ERR_SINK_INIT)
        if not stream.isOpen():
            stream.open(QIODevice.OpenModeFlag.ReadOnly | QIODevice.OpenModeFlag.Unbuffered)
        self._sink.start(stream)
        err = self._sink.error()
        if err not in (QtAudio.Error.NoError, QtAudio.Error.UnderrunError):
            raise AudioPlaybackError(f"Audio output failed to start ({err}).", code=AUDIO_ERR_SINK_INIT)

    def suspend(self) -> None:
        if self._sink is not None:
            self._sink.suspend()

    def resume(self) -> None:
        if self._sink is not None:
            self._sink.resume()

    def stop(self) -> None:
        if self._sink is not None:
            self._sink.stop()

    def reset(self) -> None:
        if self._sink is not None:
            self._sink.reset()

    def processed_usecs(self) -> int:
        return int(self._sink.processedUSecs()) if self._sink is not None else 0

    def buffer_size(self) -> int:
        return int(self._sink.bufferSize()) if self._sink is not None else 0

    def bytes_free(self) -> int:
        return int(self._sink.bytesFree()) if self._sink is not None else 0

    def state(self) -> QtAudio.State:
        return self._sink.state() if self._sink is not None else QtAudio.State.StoppedState

    def error(self) -> QtAudio.Error:
        return self._sink.error() if self._sink is not None else QtAudio.Error.NoError

    def set_volume(self, volume: float) -> None:
        self._volume = max(0.0, min(1.0, float(volume)))
        if self._sink is not None:
            self._sink.setVolume(self._volume)

    def _destroy_sink(self) -> None:
        if self._sink is not None:
            try:
                self._sink.stateChanged.disconnect(self._on_sink_state_changed)
            except (RuntimeError, TypeError):
                pass
            self._sink.stop()
            self._sink.reset()
            self._sink.deleteLater()
            self._sink = None

    def release(self) -> None:
        self._destroy_sink()


class StudioAudioPlayer(QObject):
    """PCM audio player managing ``QAudioSink``, seekable in-memory stream, pause/resume, and EOF."""

    playback_state_changed = Signal(str)  # "stopped" | "playing" | "paused"
    position_changed = Signal(int)  # milliseconds (estimated audible position)
    duration_changed = Signal(int)  # milliseconds
    end_of_media = Signal()
    error_occurred = Signal(str)

    def __init__(
        self,
        *,
        backend: Optional[AudioSinkBackend] = None,
        poll_interval_ms: int = 35,
        parent: Optional[QObject] = None,
    ) -> None:
        super().__init__(parent)
        self._owns_backend = backend is None
        self._backend: AudioSinkBackend = backend if backend is not None else QtAudioSinkBackend(self)
        self._backend.set_state_callback(self._on_backend_state_changed)

        self._stream = DualPcmStreamDevice(self)
        self._wav: Optional[WavPcmData] = None
        self._active_spec: Optional[PcmFormatSpec] = None

        self._status: str = "stopped"  # "stopped" | "playing" | "paused"
        self._duration_ms: int = 0
        self._anchor_ms: int = 0
        self._paused_position_ms: int = 0
        self._stopped_position_ms: int = 0
        self._pending_restart_from_pause: bool = False
        self._at_end: bool = False
        self._ignore_idle_transition: bool = False
        self._last_error: Optional[str] = None
        self._last_emitted_pos_ms: int = -1

        self._poll_timer = QTimer(self)
        self._poll_timer.setInterval(max(15, int(poll_interval_ms)))
        self._poll_timer.timeout.connect(self._on_poll_tick)

    def is_loaded(self) -> bool:
        return self._wav is not None and self._active_spec is not None and self._stream.size() > 0

    def is_playing(self) -> bool:
        return self._status == "playing"

    def is_paused(self) -> bool:
        return self._status == "paused"

    def at_end(self) -> bool:
        return self._at_end

    def playback_state(self) -> str:
        return self._status

    def duration(self) -> int:
        return self._duration_ms

    def active_format(self) -> Optional[PcmFormatSpec]:
        return self._active_spec

    def loaded_path(self) -> Optional[Path]:
        return self._wav.path if self._wav is not None else None

    def last_error(self) -> Optional[str]:
        return self._last_error

    def has_output_device(self) -> bool:
        return self._backend.has_output_device()

    def set_volume(self, volume: float) -> None:
        self._backend.set_volume(volume)

    def _bytes_to_ms(self, byte_count: int) -> int:
        spec = self._active_spec
        if spec is None or spec.bytes_per_second <= 0:
            return 0
        return int(round((max(0, int(byte_count)) * 1000.0) / spec.bytes_per_second))

    def _ms_to_aligned_bytes(self, pos_ms: int) -> int:
        spec = self._active_spec
        if spec is None or self._duration_ms <= 0:
            return 0
        clamped_ms = max(0, min(int(pos_ms), self._duration_ms))
        raw_bytes = int(round((clamped_ms * spec.bytes_per_second) / 1000.0))
        return self._stream.align_byte_offset(raw_bytes)

    def read_position(self) -> int:
        """Return raw PCM read cursor inside ``DualPcmStreamDevice`` in milliseconds."""
        if not self.is_loaded():
            return 0
        return min(self._duration_ms, self._bytes_to_ms(self._stream.pos()))

    def processed_position(self) -> int:
        """Return audio-sink processed position in milliseconds (``anchor + processedUSecs``)."""
        if not self.is_loaded():
            return 0
        if self._status == "stopped":
            return self._duration_ms if self._at_end else self._stopped_position_ms
        if self._status == "paused":
            if self._pending_restart_from_pause:
                return self._paused_position_ms
            proc_ms = max(0, self._backend.processed_usecs() // 1000)
            return min(self._duration_ms, max(self._paused_position_ms, self._anchor_ms + proc_ms))
        proc_ms = max(0, self._backend.processed_usecs() // 1000)
        return min(self._duration_ms, self._anchor_ms + proc_ms)

    def position(self) -> int:
        """Return conservative estimated audible position in milliseconds (never leads audio)."""
        if not self.is_loaded():
            return 0
        if self._status == "stopped":
            return self._duration_ms if self._at_end else self._stopped_position_ms
        if self._status == "paused":
            return self._paused_position_ms

        proc_delta_ms = max(0, self._backend.processed_usecs() // 1000)
        buf_size = max(0, self._backend.buffer_size())
        bytes_free = max(0, min(buf_size, self._backend.bytes_free())) if buf_size > 0 else 0
        queued_bytes = max(0, buf_size - bytes_free)
        queued_ms = self._bytes_to_ms(queued_bytes) if queued_bytes > 0 else 0

        if self._stream.is_exhausted():
            # Stream reached end; audible position advances monotonically up to duration_ms as queue drains.
            audible = self._anchor_ms + max(0, proc_delta_ms - queued_ms)
            return max(self._anchor_ms, min(self._duration_ms, audible))

        # Keep audible position slightly behind/equal to sink processed cursor by accounting for queued buffer.
        audible_delta_ms = max(0, proc_delta_ms - queued_ms)
        return max(self._anchor_ms, min(self._duration_ms, self._anchor_ms + audible_delta_ms))

    def _emit_position_if_changed(self, *, force: bool = False) -> None:
        pos = self.position()
        if force or pos != self._last_emitted_pos_ms:
            self._last_emitted_pos_ms = pos
            self.position_changed.emit(pos)

    def _set_status(self, new_status: str) -> None:
        if self._status != new_status:
            self._status = new_status
            self.playback_state_changed.emit(new_status)

    def _report_error(self, message: str) -> None:
        self._last_error = message
        self.error_occurred.emit(message)

    def load(self, path: Path | str) -> bool:
        """Load WAV file into memory, close file handle, and prepare audio device format."""
        self.release()
        self._last_error = None
        try:
            wav = load_wav_pcm(path)
            spec = self._backend.negotiate_and_prepare(wav, self._stream)
        except AudioPlaybackError as exc:
            self._wav = None
            self._active_spec = None
            self._duration_ms = 0
            self._report_error(str(exc))
            return False

        self._wav = wav
        self._active_spec = spec
        self._duration_ms = max(1, self._bytes_to_ms(self._stream.size()))
        self._anchor_ms = 0
        self._paused_position_ms = 0
        self._stopped_position_ms = 0
        self._pending_restart_from_pause = False
        self._at_end = False
        self._last_emitted_pos_ms = -1
        self._set_status("stopped")
        self.duration_changed.emit(self._duration_ms)
        self._emit_position_if_changed(force=True)
        return True

    def play(self) -> bool:
        """Start playback from beginning/seek cursor, or resume if currently paused."""
        if not self.is_loaded():
            self._report_error("Cannot start playback: no valid WAV loaded.")
            return False

        if self._status == "paused":
            return self.resume()

        if self._status == "playing":
            return True

        self._last_error = None
        if self._at_end or self._stream.is_exhausted():
            self._stream.seek(0)
            self._anchor_ms = 0
            self._stopped_position_ms = 0
            self._at_end = False
        else:
            byte_off = self._ms_to_aligned_bytes(self._stopped_position_ms)
            self._stream.seek(byte_off)
            self._anchor_ms = self._bytes_to_ms(byte_off)

        self._ignore_idle_transition = False
        try:
            self._backend.start(self._stream)
        except AudioPlaybackError as exc:
            self._report_error(str(exc))
            return False

        self._set_status("playing")
        self._poll_timer.start()
        self._emit_position_if_changed(force=True)
        return True

    def pause(self) -> None:
        """Suspend active playback while preserving exact audible cursor."""
        if self._status != "playing" or not self.is_loaded():
            return
        frozen_ms = self.position()
        self._poll_timer.stop()
        self._paused_position_ms = frozen_ms
        self._pending_restart_from_pause = False
        self._ignore_idle_transition = True
        try:
            self._backend.suspend()
        finally:
            self._ignore_idle_transition = False
        self._set_status("paused")
        self._emit_position_if_changed(force=True)

    def prepare_paused_at(self, position_ms: int) -> int:
        """Prepare loaded PCM stream in paused state at *position_ms* without starting audio sink."""
        if not self.is_loaded():
            return 0

        self._poll_timer.stop()
        self._ignore_idle_transition = True
        try:
            self._backend.stop()
            self._backend.reset()
        finally:
            self._ignore_idle_transition = False

        byte_off = self._ms_to_aligned_bytes(position_ms)
        aligned_ms = min(self._duration_ms, self._bytes_to_ms(byte_off))
        self._stream.seek(byte_off)
        self._anchor_ms = aligned_ms
        self._paused_position_ms = aligned_ms
        self._stopped_position_ms = 0
        self._pending_restart_from_pause = True
        self._at_end = False
        self._last_error = None
        self._set_status("paused")
        self._emit_position_if_changed(force=True)
        return aligned_ms

    def resume(self) -> bool:
        """Resume playback from paused state without replaying stale pre-seek buffers."""
        if self._status != "paused" or not self.is_loaded():
            return False

        self._ignore_idle_transition = False
        if self._pending_restart_from_pause:
            byte_off = self._ms_to_aligned_bytes(self._paused_position_ms)
            self._stream.seek(byte_off)
            self._anchor_ms = self._bytes_to_ms(byte_off)
            self._pending_restart_from_pause = False
            try:
                self._backend.start(self._stream)
            except AudioPlaybackError as exc:
                self._report_error(str(exc))
                self._set_status("stopped")
                return False
        else:
            self._backend.resume()

        self._set_status("playing")
        self._poll_timer.start()
        self._emit_position_if_changed(force=True)
        return True

    def stop(self) -> None:
        """Stop playback cleanly and reset playback cursor to ``0 ms``."""
        if not self.is_loaded() and self._status == "stopped":
            return

        self._poll_timer.stop()
        self._ignore_idle_transition = True
        try:
            self._backend.stop()
            self._backend.reset()
        finally:
            self._ignore_idle_transition = False

        if self._stream.isOpen():
            self._stream.seek(0)
        self._anchor_ms = 0
        self._paused_position_ms = 0
        self._stopped_position_ms = 0
        self._pending_restart_from_pause = False
        self._at_end = False
        self._set_status("stopped")
        self._emit_position_if_changed(force=True)

    def seek(self, position_ms: int) -> int:
        """Seek to *position_ms* safely across ``playing``, ``paused``, and ``stopped`` states."""
        if not self.is_loaded():
            return 0

        byte_off = self._ms_to_aligned_bytes(position_ms)
        aligned_ms = min(self._duration_ms, self._bytes_to_ms(byte_off))
        # Seeking to exact EOF when stream has frames clamps one step or allows EOF behavior consistently
        if self._status == "playing":
            self._poll_timer.stop()
            self._ignore_idle_transition = True
            try:
                self._backend.reset()
            finally:
                self._ignore_idle_transition = False

            self._stream.seek(byte_off)
            self._anchor_ms = aligned_ms
            self._at_end = False
            if self._stream.is_exhausted():
                # Seeking straight to the very end finishes cleanly instead of stalling
                self._at_end = True
                self._set_status("stopped")
                self._emit_position_if_changed(force=True)
                self.end_of_media.emit()
                return self._duration_ms

            try:
                self._backend.start(self._stream)
            except AudioPlaybackError as exc:
                self._set_status("stopped")
                self._report_error(str(exc))
                return self.position()
            self._poll_timer.start()
            self._emit_position_if_changed(force=True)
            return aligned_ms

        if self._status == "paused":
            self._ignore_idle_transition = True
            try:
                # Discard any buffered pre-seek audio so Resume never plays stale frames.
                self._backend.reset()
            finally:
                self._ignore_idle_transition = False
            self._stream.seek(byte_off)
            self._anchor_ms = aligned_ms
            self._paused_position_ms = aligned_ms
            self._pending_restart_from_pause = True
            self._at_end = False
            self._emit_position_if_changed(force=True)
            return aligned_ms

        # Stopped state (before Play or after EOF)
        self._stream.seek(byte_off)
        self._anchor_ms = aligned_ms
        self._stopped_position_ms = aligned_ms
        self._at_end = False
        self._emit_position_if_changed(force=True)
        return aligned_ms

    def _on_poll_tick(self) -> None:
        if self._status != "playing":
            return
        self._emit_position_if_changed()
        # Defensive check in case IdleState fired just before poll or sink already drained
        if (
            self._backend.state() == QtAudio.State.IdleState
            and self._stream.is_exhausted()
            and self._is_sink_drained()
        ):
            self._complete_eof()

    def _is_sink_drained(self) -> bool:
        buf_sz = self._backend.buffer_size()
        if buf_sz <= 0:
            return True
        return self._backend.bytes_free() >= buf_sz

    def _complete_eof(self) -> None:
        if self._status != "playing":
            return
        self._poll_timer.stop()
        self._ignore_idle_transition = True
        try:
            self._backend.stop()
        finally:
            self._ignore_idle_transition = False
        self._at_end = True
        self._pending_restart_from_pause = False
        self._set_status("stopped")
        self._emit_position_if_changed(force=True)
        self.end_of_media.emit()

    def _on_backend_state_changed(self, state: QtAudio.State, err: QtAudio.Error) -> None:
        if err not in (QtAudio.Error.NoError, QtAudio.Error.UnderrunError):
            self._poll_timer.stop()
            self._ignore_idle_transition = True
            try:
                self._backend.stop()
            finally:
                self._ignore_idle_transition = False
            self._set_status("stopped")
            self._report_error(f"Audio output device error: {err}")
            return

        if state == QtAudio.State.IdleState:
            if self._ignore_idle_transition or self._status != "playing":
                return
            # Genuine EOF ONLY when PCM stream has read all frames AND sink queue has drained.
            if self._stream.is_exhausted() and self._is_sink_drained():
                self._complete_eof()
            # Otherwise transient underrun / awaiting more frames: do NOT misclassify as EOF!

    def release(self) -> None:
        """Stop playback, release audio sink, close stream device, and drop PCM buffers."""
        self._poll_timer.stop()
        self._ignore_idle_transition = True
        try:
            self._backend.release()
        finally:
            self._ignore_idle_transition = False

        if self._stream.isOpen():
            self._stream.close()
        self._stream.clear_pcm()

        self._wav = None
        self._active_spec = None
        self._duration_ms = 0
        self._anchor_ms = 0
        self._paused_position_ms = 0
        self._stopped_position_ms = 0
        self._pending_restart_from_pause = False
        self._at_end = False
        self._last_emitted_pos_ms = -1
        self._set_status("stopped")

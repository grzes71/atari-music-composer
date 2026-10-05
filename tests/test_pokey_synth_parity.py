"""Bit-level and statistical parity tests between Rust core and Python reference implementations."""

import numpy as np
import pytest

from atari_music.pokey_synth import (
    render_pokey_samples,
    _render_pokey_samples_rs,
)
from atari_music.listening_test_v2 import (
    _read_wav_stats,
    _batch_inspect_wavs_rs,
)


def _render_pokey_samples_python_ref(
    frames: np.ndarray,
    sample_rate: int = 44100,
    frame_rate_hz: float = 50.0,
) -> np.ndarray:
    """Explicitly execute the pure-Python reference implementation."""
    from atari_music import pokey_synth

    # Temporarily hide Rust core to force pure Python execution
    saved_rs = pokey_synth._render_pokey_samples_rs
    try:
        pokey_synth._render_pokey_samples_rs = None
        return render_pokey_samples(frames, sample_rate, frame_rate_hz)
    finally:
        pokey_synth._render_pokey_samples_rs = saved_rs


def test_rust_core_availability():
    """Verify Rust core extension is compiled and available."""
    assert _render_pokey_samples_rs is not None, "Rust core extension _core must be available"


@pytest.mark.parametrize("audc", [0xA8, 0xC8, 0x88, 0x28, 0x48, 0x08])
def test_rust_python_single_channel_parity(audc: int):
    """Verify Rust and Python synthesizers match across all POKEY distortion modes."""
    num_frames = 50  # 1 second of audio
    frames = np.zeros((num_frames, 9), dtype=np.uint8)
    frames[:, 0] = 71     # AUDF1 = 71 (A4 ~440Hz)
    frames[:, 1] = audc   # Volume 8

    samples_rs = render_pokey_samples(frames)
    samples_py = _render_pokey_samples_python_ref(frames)

    assert len(samples_rs) == len(samples_py)
    # Correlation between Rust and Python synthesizers must be virtually identical
    corr = np.corrcoef(samples_rs, samples_py)[0, 1]
    assert corr >= 0.999, f"Correlation too low for AUDC ${audc:02X}: {corr}"


def test_rust_python_16bit_bass_parity():
    """Verify Rust and Python synthesizers match for joined 16-bit bass channel."""
    num_frames = 50
    frames = np.zeros((num_frames, 9), dtype=np.uint8)
    frames[:, 0] = 0x1F  # Low byte
    frames[:, 1] = 0x00  # Muted CH1
    frames[:, 2] = 0x01  # High byte
    frames[:, 3] = 0xAF  # Pure tone on CH2, Vol 15
    frames[:, 8] = 0x10  # AUDCTL_JOIN_1_2_16BIT

    samples_rs = render_pokey_samples(frames)
    samples_py = _render_pokey_samples_python_ref(frames)

    corr = np.corrcoef(samples_rs, samples_py)[0, 1]
    assert corr >= 0.9999


def test_rust_batch_inspect_wavs_parity(tmp_path):
    """Verify Rust batch WAV inspector results match Python _read_wav_stats."""
    import wave

    if _batch_inspect_wavs_rs is None:
        pytest.skip("Rust batch inspector not available")

    # Generate a dummy test WAV
    test_wav = tmp_path / "test_tone.wav"
    sample_rate = 44100
    n_samples = 44100 * 2
    t = np.linspace(0, 2, n_samples, endpoint=False)
    sine = (np.sin(2 * np.pi * 440 * t) * 16000).astype(np.int16)

    with wave.open(str(test_wav), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(sine.tobytes())

    # Python reader stats
    py_dur, py_peak, py_rms, py_fr, py_ch = _read_wav_stats(test_wav)

    # Rust batch reader stats
    rs_batch = _batch_inspect_wavs_rs([str(test_wav)])
    assert len(rs_batch) == 1
    rs_stat = rs_batch[0]

    assert rs_stat["error"] is None
    assert rs_stat["channels"] == py_ch == 1
    assert rs_stat["framerate"] == py_fr == 44100
    assert rs_stat["duration_sec"] == pytest.approx(py_dur, abs=0.01)
    assert rs_stat["peak"] == pytest.approx(py_peak, abs=1e-4)
    assert rs_stat["rms"] == pytest.approx(py_rms, abs=1e-4)

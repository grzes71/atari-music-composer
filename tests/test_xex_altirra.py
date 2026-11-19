"""Optional full-system Atari XL/XE (PAL 50 Hz) verification via AltirraSDL + AltirraBridge.

These integration tests boot actual production-generated ``.xex`` binaries (v1 and v2)
inside a real AltirraSDL emulator driven over the AltirraBridge JSON-over-socket protocol.

Markers & CI Independence
-------------------------
- Marked ``core``, ``live``, and ``emulator`` so ordinary offline CORE / CI runs
  (``pytest`` or ``pytest -m "core and not live"``) never launch an external emulator.
- Skips cleanly if ``AltirraSDL`` / ``AltirraBridgeServer`` or the ``altirra_bridge``
  Python SDK is not available.

How to Run Locally
------------------
    pytest -m emulator -o addopts="--strict-markers" -v

Optional Environment Overrides
------------------------------
- ``ALTIRRA_SDL_BIN``: Path to ``AltirraBridgeServer`` or ``AltirraSDL`` executable.
- ``ALTIRRA_BRIDGE_SDK``: Path to directory containing the ``altirra_bridge`` Python package.
- ``ALTIRRA_ARTIFACT_DIR``: Optional directory where PNG screenshots and logs are persisted.
"""

from __future__ import annotations

from contextlib import contextmanager
import os
from pathlib import Path
import shutil
import subprocess
import sys
import threading
from typing import Dict, Iterator, List, Optional, Tuple

import pytest

from atari_music.api import generate_music
from atari_music.constants import AUDCTL_CH1_179MHZ, AUDCTL_JOIN_1_2_16BIT
from tests.test_xex_e2e_py65 import (
    MADS_EXE,
    PLAYER_ASM,
    _build_v2_16bit_song,
    _build_v2_8bit_rich_song,
    _export_ir_via_studio,
)

pytestmark = [pytest.mark.core, pytest.mark.live, pytest.mark.emulator]

REPO_ROOT = Path(__file__).resolve().parents[1]


def _discover_altirra_executable() -> Optional[Path]:
    env_bin = os.environ.get("ALTIRRA_SDL_BIN")
    if env_bin:
        p = Path(env_bin)
        if p.is_file():
            return p

    for exe_name in ("AltirraBridgeServer", "AltirraBridgeServer.exe", "AltirraSDL", "AltirraSDL.exe"):
        found = shutil.which(exe_name)
        if found:
            return Path(found)

    sibling_root = REPO_ROOT.parent / "AltirraSDL"
    candidates = [
        sibling_root / "build" / "windows-bridge-release" / "src" / "AltirraBridgeServer" / "Release" / "AltirraBridgeServer.exe",
        sibling_root / "build" / "windows-sdl-release" / "src" / "AltirraSDL" / "Release" / "AltirraSDL.exe",
        sibling_root / "build" / "release" / "AltirraBridgeServer",
        sibling_root / "build" / "release" / "AltirraSDL",
    ]
    for cand in candidates:
        if cand.is_file():
            return cand
    return None


def _import_altirra_bridge():
    try:
        from altirra_bridge import AltirraBridge  # type: ignore[import-not-found]
        return AltirraBridge
    except ImportError:
        pass

    sdk_candidates: List[Path] = []
    env_sdk = os.environ.get("ALTIRRA_BRIDGE_SDK")
    if env_sdk:
        sdk_candidates.append(Path(env_sdk))
    sdk_candidates.append(REPO_ROOT.parent / "AltirraSDL" / "src" / "AltirraSDL" / "AltirraBridge" / "sdk" / "python")

    for sdk_dir in sdk_candidates:
        if (sdk_dir / "altirra_bridge").is_dir():
            sdk_str = str(sdk_dir)
            if sdk_str not in sys.path:
                sys.path.insert(0, sdk_str)
            from altirra_bridge import AltirraBridge  # type: ignore[import-not-found]
            return AltirraBridge
    return None


def _require_altirra_environment() -> Tuple[Path, object]:
    if not MADS_EXE.is_file():
        pytest.skip(f"MADS assembler not found at {MADS_EXE}")
    if not PLAYER_ASM.is_file():
        pytest.skip(f"player.asm not found at {PLAYER_ASM}")

    exe = _discover_altirra_executable()
    if exe is None:
        pytest.skip(
            "AltirraSDL / AltirraBridgeServer not found. Set ALTIRRA_SDL_BIN or place "
            "AltirraSDL build in sibling ../AltirraSDL directory."
        )

    bridge_cls = _import_altirra_bridge()
    if bridge_cls is None:
        pytest.skip(
            "altirra_bridge Python SDK not found. Install altirra_bridge or set ALTIRRA_BRIDGE_SDK."
        )
    return exe, bridge_cls


@contextmanager
def _altirra_boot_xex_session(
    exe: Path,
    bridge_cls,
    xex_path: Path,
    *,
    startup_timeout_s: float = 15.0,
    rpc_timeout_s: float = 15.0,
) -> Iterator[Tuple[object, List[str]]]:
    """Launch AltirraSDL directly booting *xex_path* with --bridge, bounded timeouts, and stderr drain."""
    proc = subprocess.Popen(
        [str(exe), "--bridge=tcp:127.0.0.1:0", str(xex_path)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
    )
    stderr_lines: List[str] = []
    token_file: Optional[str] = None
    token_ready = threading.Event()

    def _drain_stderr() -> None:
        nonlocal token_file
        assert proc.stderr is not None
        for raw_line in proc.stderr:
            line = raw_line.strip()
            stderr_lines.append(line)
            if "token-file:" in line:
                token_file = line.split("token-file:", 1)[1].strip()
                token_ready.set()

    drain_thread = threading.Thread(target=_drain_stderr, daemon=True)
    drain_thread.start()

    if not token_ready.wait(timeout=startup_timeout_s) or token_file is None:
        proc.kill()
        proc.wait(timeout=5)
        raise RuntimeError(
            f"AltirraSDL bridge failed to publish token-file within {startup_timeout_s}s "
            f"(rc={proc.poll()}): {stderr_lines[:15]}"
        )

    try:
        with bridge_cls.from_token_file(token_file) as bridge:
            if hasattr(bridge, "_sock") and bridge._sock is not None:
                bridge._sock.settimeout(rpc_timeout_s)
            assert bridge.ping().get("ok") is True
            # Verify PAL 800XL configuration (avoid re-triggering reset if already PAL 800XL without BASIC)
            cfg = bridge.config()
            if str(cfg.get("video", "")).lower() != "pal":
                bridge.config("video", "pal")
            if bool(cfg.get("basic", False)):
                bridge.config("basic", "false")
            bridge.warp(True)
            yield bridge, stderr_lines
            try:
                bridge.quit()
            except Exception:
                pass
    finally:
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=5)


def _save_screenshot_artifact(png_bytes: bytes, tmp_path: Path, filename: str) -> Path:
    assert png_bytes.startswith(b"\x89PNG\r\n\x1a\n"), "screenshot did not return valid PNG bytes"
    out_dir = Path(os.environ["ALTIRRA_ARTIFACT_DIR"]) if os.environ.get("ALTIRRA_ARTIFACT_DIR") else tmp_path
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / filename
    out_path.write_bytes(png_bytes)
    return out_path


def _extract_screen_lines(bridge) -> List[str]:
    raw = bridge.screen_text()
    if isinstance(raw, dict):
        lines = raw.get("lines") or raw.get("text") or []
    else:
        lines = raw
    return [str(line) for line in lines]


def _collect_pokey_trace_events(bridge, frames: int) -> List[Dict[str, object]]:
    bridge.pokey_trace_start(capacity=65536)
    bridge.frame(frames)
    bridge.pokey_trace_stop()
    trace = bridge.pokey_trace_read(max_events=8192)
    events = trace.get("events", []) if isinstance(trace, dict) else []
    return list(events)


def _send_key_and_step(bridge, key_name: str, settle_frames: int = 8) -> None:
    """Inject an Atari key press over AltirraBridge and step PAL frames for OS key scan."""
    bridge.key(key_name)
    bridge.frame(settle_frames)


def _verify_boot_ui_pokey_and_keys(
    exe: Path,
    bridge_cls,
    xex_path: Path,
    *,
    expected_title_substr: str,
    expected_audctl: int,
    expected_join_1_2: bool,
    screenshot_name: str,
    tmp_path: Path,
) -> None:
    """Boot a real XEX in PAL 800XL, verify UI text, POKEY trace/audio state, keyboard controls, and PNG."""
    with _altirra_boot_xex_session(exe, bridge_cls, xex_path) as (bridge, _logs):
        # Allow OS cold boot + XEX DOS loader + harness init + playback
        bridge.frame(100)

        # 1. Verify CPU is executing cleanly inside harness/player RAM ($6000-$7FFF)
        regs = bridge.regs()
        pc_raw = regs.get("PC") or regs.get("pc")
        pc_val = int(str(pc_raw).lstrip("$"), 16) if isinstance(pc_raw, str) else int(pc_raw)
        assert 0x0400 <= pc_val <= 0xFFFF, f"unexpected PC after boot: {regs}"

        # 2. Verify ANTIC Mode 2 screen text rendered by init_screen_layout + update_screen_ui
        lines = _extract_screen_lines(bridge)
        full_screen = "\n".join(lines)
        assert "ATARI POKEY MUSIC PLAYER" in full_screen, f"header missing:\n{full_screen}"
        assert expected_title_substr in full_screen, f"title {expected_title_substr!r} missing:\n{full_screen}"
        assert "[PLAYING]" in full_screen, f"expected [PLAYING] status:\n{full_screen}"
        assert "CH1:" in full_screen and "CH4:" in full_screen

        # 3. Verify PAL 50 Hz RTCLOK ($14) advances and POKEY hardware registers are actively driven
        rt_before = bridge.peek(0x0014, 1)[0]
        events = _collect_pokey_trace_events(bridge, frames=40)
        rt_after = bridge.peek(0x0014, 1)[0]
        assert rt_after != rt_before, "RTCLOK ($14) did not advance during PAL playback"
        assert len(events) > 0, "no POKEY register write events observed during 40 PAL frames"

        pokey_state = bridge.pokey(1)
        audctl_raw = pokey_state.get("AUDCTL") or pokey_state.get("audctl")
        assert audctl_raw is not None, f"AUDCTL missing from pokey(): {pokey_state}"
        parsed_audctl = int(str(audctl_raw).lstrip("$"), 16) if isinstance(audctl_raw, str) else int(audctl_raw)
        assert parsed_audctl == expected_audctl, (
            f"expected AUDCTL=${expected_audctl:02X}, got {audctl_raw!r}"
        )

        audio = bridge.audio_state()
        assert audio.get("ok") is True
        assert bool(audio.get("join_1_2")) is expected_join_1_2
        channels = audio.get("channels", [])
        assert len(channels) == 4
        assert any(int(ch.get("volume", 0)) > 0 for ch in channels), f"all POKEY channels silent: {audio}"

        # 4. Capture diagnostic PNG screenshot while playing
        png = bridge.screenshot()
        _save_screenshot_artifact(png, tmp_path, screenshot_name)

        # 5. Verify keyboard controls: '1'..'4' channel mute/unmute
        for ch_idx, key_name in ((1, "1"), (2, "2"), (3, "3"), (4, "4")):
            _send_key_and_step(bridge, key_name, settle_frames=8)
            ch_line_off = next((ln for ln in _extract_screen_lines(bridge) if f"CH{ch_idx}:" in ln), "")
            assert "OFF" in ch_line_off, f"key '{key_name}' did not mute CH{ch_idx}: {ch_line_off!r}"

            _send_key_and_step(bridge, key_name, settle_frames=8)
            ch_line_on = next((ln for ln in _extract_screen_lines(bridge) if f"CH{ch_idx}:" in ln), "")
            assert "ON" in ch_line_on and "OFF" not in ch_line_on, (
                f"second key '{key_name}' did not unmute CH{ch_idx}: {ch_line_on!r}"
            )

        # 6. Verify Space pause -> [PAUSED ] + silenced POKEY, then Space resume -> [PLAYING]
        _send_key_and_step(bridge, "space", settle_frames=8)
        paused_screen = "\n".join(_extract_screen_lines(bridge))
        assert "[PAUSED" in paused_screen, f"Space did not pause playback:\n{paused_screen}"
        paused_audio = bridge.audio_state()
        assert all(int(ch.get("volume", 0)) == 0 for ch in paused_audio.get("channels", [])), (
            f"POKEY channels not silenced while paused: {paused_audio}"
        )

        _send_key_and_step(bridge, "space", settle_frames=8)
        resumed_screen = "\n".join(_extract_screen_lines(bridge))
        assert "[PLAYING]" in resumed_screen, f"second Space did not resume playback:\n{resumed_screen}"


def test_altirra_boots_real_v1_xex_and_verifies_ui_pokey_and_keys(tmp_path: Path) -> None:
    """Boot a real production v1 XEX in AltirraSDL PAL 800XL and verify UI, POKEY, and keys."""
    exe, bridge_cls = _require_altirra_environment()
    song = generate_music(profile="action", seed=42).pokey_ir
    xex_path, _asm_path, fmt_ver = _export_ir_via_studio(song, tmp_path, "altirra_v1", player_version="v1")
    assert fmt_ver == 1

    _verify_boot_ui_pokey_and_keys(
        exe,
        bridge_cls,
        xex_path,
        expected_title_substr="TITLE:",
        expected_audctl=0x00,
        expected_join_1_2=False,
        screenshot_name="altirra_v1_playing.png",
        tmp_path=tmp_path,
    )


def test_altirra_boots_real_v2_8bit_and_16bit_xex_and_verifies_ui_pokey_and_keys(
    tmp_path: Path,
) -> None:
    """Boot real production v2 8-bit and 16-bit ($50) XEX files in AltirraSDL PAL 800XL."""
    exe, bridge_cls = _require_altirra_environment()

    song_8bit = _build_v2_8bit_rich_song()
    xex_8bit, _asm8, fmt8 = _export_ir_via_studio(song_8bit, tmp_path, "altirra_v2_8bit", player_version="v2")
    assert fmt8 == 2

    _verify_boot_xex_8 = _verify_boot_ui_pokey_and_keys(
        exe,
        bridge_cls,
        xex_8bit,
        expected_title_substr="Stage2 V2 8bit",
        expected_audctl=0x00,
        expected_join_1_2=False,
        screenshot_name="altirra_v2_8bit_playing.png",
        tmp_path=tmp_path,
    )

    song_16bit = _build_v2_16bit_song()
    xex_16bit, _asm16, fmt16 = _export_ir_via_studio(song_16bit, tmp_path, "altirra_v2_16bit", player_version="v2")
    assert fmt16 == 2

    _verify_boot_ui_pokey_and_keys(
        exe,
        bridge_cls,
        xex_16bit,
        expected_title_substr="Stage2 V2 16bit",
        expected_audctl=AUDCTL_JOIN_1_2_16BIT | AUDCTL_CH1_179MHZ,
        expected_join_1_2=True,
        screenshot_name="altirra_v2_16bit_playing.png",
        tmp_path=tmp_path,
    )

# Manual Verification Guide: Studio PCM Audio Playback Engine (Windows)

This checklist verifies Phase 3 Stage 2 (`StudioAudioPlayer` on `QAudioSink` + `DualPcmStreamDevice`) directly against a real Windows audio output device (`WASAPI` / speakers / headphones).

## Prerequisites

1. Activate the project virtual environment:
   ```powershell
   .\.venv\Scripts\Activate.ps1
   ```
2. Ensure an audio output device is connected and unmuted in Windows Sound settings.
3. Optional quick test WAV generator (creates two short 44.1 kHz / 16-bit mono test tones in `%TEMP%`):
   ```powershell
   python -c "
   import math, struct, wave, tempfile
   from pathlib import Path
   out = Path(tempfile.gettempdir()) / 'studio_manual_test'
   out.mkdir(exist_ok=True)
   for name, freq, secs in [('tone_a.wav', 440.0, 4.0), ('tone_b.wav', 660.0, 2.5)]:
       with wave.open(str(out / name), 'wb') as wf:
           wf.setnchannels(1); wf.setsampwidth(2); wf.setframerate(44100)
           frames = bytearray()
           for i in range(int(44100 * secs)):
               # Audible stepped sweep so seek positions sound clearly different!
               f = freq * (1.0 + 0.5 * int(i / 44100))
               s = int(0.25 * 32767 * math.sin(2 * math.pi * f * (i / 44100)))
               frames.extend(struct.pack('<h', s))
           wf.writeframes(bytes(frames))
   print('Created:', out / 'tone_a.wav', out / 'tone_b.wav')
   "
   ```

## Interactive Verification Script

Run the interactive Windows console harness below with `tone_a.wav` and `tone_b.wav` (type commands while the Qt event loop stays alive on a background stdin reader):

```powershell
python -c "
import threading, tempfile
from pathlib import Path
from PySide6.QtCore import QMetaObject, Qt, Q_ARG
from PySide6.QtWidgets import QApplication
from atari_music.studio.ui.audio_player import StudioAudioPlayer

app = QApplication([])
base = Path(tempfile.gettempdir()) / 'studio_manual_test'
wav_a, wav_b = base / 'tone_a.wav', base / 'tone_b.wav'
player = StudioAudioPlayer()
player.set_volume(0.5)
player.playback_state_changed.connect(lambda s: print('[STATE]', s))
player.position_changed.connect(
    lambda ms: print(f'[POS] {ms} ms / {player.duration()} ms (read={player.read_position()} ms, proc={player.processed_position()} ms)')
)
player.end_of_media.connect(lambda: print('[EOF] Playback finished!'))
player.error_occurred.connect(lambda msg: print('[ERROR]', msg))

def handle_cmd(cmd: str):
    parts = cmd.strip().split()
    if not parts:
        return
    op = parts[0].lower()
    if op == 'load_a': print('load_a ->', player.load(wav_a))
    elif op == 'load_b': print('load_b ->', player.load(wav_b))
    elif op == 'play': print('play ->', player.play())
    elif op == 'pause': player.pause()
    elif op == 'resume': print('resume ->', player.resume())
    elif op == 'stop': player.stop()
    elif op == 'seek' and len(parts) == 2: print('seek ->', player.seek(int(parts[1])))
    elif op == 'del_a': wav_a.unlink(); print('deleted tone_a.wav successfully')
    elif op == 'state': print(f'state={player.playback_state()} pos={player.position()} proc={player.processed_position()} read={player.read_position()} dur={player.duration()} err={player.last_error()}')
    elif op == 'quit': player.release(); app.quit()

def reader():
    print('Commands: load_a | load_b | play | pause | resume | stop | seek <ms> | del_a | state | quit')
    while True:
        try:
            line = input('> ')
        except EOFError:
            line = 'quit'
        QMetaObject.invokeMethod(app, lambda c=line: handle_cmd(c), Qt.ConnectionType.QueuedConnection)
        if line.strip().lower() == 'quit':
            break

threading.Thread(target=reader, daemon=True).start()
app.exec()
"
```

Alternatively, run the automated real-hardware pytest check first, then walk through steps 1–10 interactively:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_studio_playback.py -v -s
```

## 10-Step Manual Verification Checklist

| Step | Action | Expected Result |
|---|---|---|
| **1. Load short WAV** | Load `tone_a.wav` (`4.0 s`) via `player.load(wav_a)` | Returns `True`; `duration() == 4000`; `position() == 0`; `playback_state() == "stopped"`; no OS file handle kept open. |
| **2. Play** | Call `player.play()` | Audio plays cleanly through Windows speakers without clicks/stutter; `playback_state` becomes `"playing"`; `[POS]` advances monotonically every ~35 ms and **does not jump ahead of heard sound** (`position() <= processed_position() < read_position()`). |
| **3. Pause & Resume** | Call `player.pause()`, wait 2 s, call `player.resume()` | Audio stops immediately on `pause()`; `playback_state` is `"paused"`; `position()` freezes on the pause timestamp. On `resume()`, audio continues from the exact same spot without replaying old sound or resetting to `0`. |
| **4. Repeated Seek while playing** | While playing, call `player.seek(2500)`, wait ~0.5 s, call `player.seek(800)` | Pitch changes immediately to the new time offset (higher pitch at 2.5 s, lower pitch at 0.8 s); no stale pre-seek buffer audio bleeds through; `position()` jumps cleanly to `~2500` then `~800` and continues advancing. |
| **5. Seek while paused** | Call `player.pause()`, then `player.seek(3100)`, then `player.resume()` | While paused, `position()` updates immediately to `3100` and state remains `"paused"`. After `resume()`, playback begins cleanly at `3100 ms` (never plays audio from before the seek). |
| **6. Stop & Replay** | While playing, call `player.stop()`, verify `position()`, then call `player.play()` | Audio stops immediately; `playback_state == "stopped"`; `position()` returns strictly to `0` without triggering `[EOF]`. Subsequent `play()` starts from `0 ms`. |
| **7. Reach EOF** | Seek near end (`player.seek(3700)`) and wait ~0.5 s | Audio plays to natural end; `[EOF]` fires once after buffered frames drain; `playback_state == "stopped"`; `at_end() is True`; `position() == duration()`; calling `play()` again replays from `0 ms`. |
| **8. Repeated multi-file loads** | Alternate `player.load(wav_b)`, `play()`, `player.load(wav_a)`, `play()`, `player.release()` | No Qt warnings, no exceptions, no lingering audio from prior WAV, `duration()` updates accurately (`2500` vs `4000`). |
| **9. Delete WAV immediately after load** | Call `player.load(wav_a)` and `wav_a.unlink()` (even while `play()` is running!) | Succeeds immediately on Windows with **no `PermissionError` / `[WinError 32]`** because PCM was copied into memory and the file handle closed inside `load()`. |
| **10. Missing / changed audio device** | Disable/disconnect all Windows playback devices (or test hot-unplug during playback), then `load()` / `play()` | No application crash or hang; `error_occurred` emits a readable error (`NO_AUDIO_DEVICE` or device error); `last_error()` describes the failure and `is_playing()` returns cleanly to `"stopped"`. |

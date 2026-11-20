# Atari Music Composer Studio

**Atari Music Composer Studio — Instrument Explorer** is an optional PySide6 desktop application layered
cleanly over headless services
([`src/atari_music/studio/`](https://github.com/grzes71/atari-music-composer/blob/main/src/atari_music/studio/__init__.py))
that reuse the same arrangement, WAV synthesis, and XEX compilation pipeline as the CLI. Nothing in
Studio bypasses the core: it calls the same `arrange`, render, and export services, so a result produced
in the GUI is identical to the CLI equivalent.

## Install and launch

```bash
# Optional Qt UI dependency
pip install -e ".[studio]"

# Launch (optionally opening a .json or .dsl composition)
atari-music-studio examples/songs/Vaults-of-Nhyrmeth.dsl
# or:
python -m atari_music.studio.ui.app examples/songs/Vaults-of-Nhyrmeth.dsl
```

Without a file argument, Studio opens with an empty workspace.

## What you can do

* **Open compositions** — `.json` (`AICompositionDoc`) and `.dsl` (Music DSL) files, with per-channel
  instrument inspection and live catalog diagnostics (blocking conflicts disable rendering rather than
  silently degrading).
* **Assign SSOT catalog instruments** per channel with `POKEYRuntime`-powered compatibility warnings,
  and revert edits freely.
* **Render WAV previews** on demand (off-thread workers, cached).
* **A/B comparison** — two independent arrangement slots (`Save to A` / `Save to B`, `Render A/B`,
  position-preserving `Listen A/B` switching and `Switch A/B`); slots track whether they match the
  current editor state, and late worker results from previously-opened songs are discarded safely.
* **Arrangement presets** — persistent JSON presets (schema `atari-music/arrangement-preset/1`) stored
  atomically under `~/.atari_music_studio/presets/`, with a strict **Load** (read & validate only) vs.
  **Apply** (explicitly replace the working arrangement) separation, rename/delete management, and
  clean rejection of unknown instrument IDs or malformed files.
* **Validated XEX export** — `Export XEX...` compiles `.xex` binaries (optionally alongside companion
  MADS `.asm`) off the UI thread via `ExportService`, validating toolchain paths (`mads`,
  `player.asm`), addresses (`player_address`, `music_address`, `$80..$F2` Zero Page base), and
  `xex_layout.validate_xex_layout()`, with same-volume staging and rollback so failed exports never
  damage existing files.
* **Tabbed workspace** — the main window provides a tab-based workspace layout (playback, preset bar,
  panels) instead of stacking everything into one toolbar-driven surface.

## Manual QA checklists

Studio's audio-critical paths ship as manual verification guides (kept in the Development section):

* [A/B comparison & playback](../development/studio-ab-manual-test.md) — A/B flow, different-length
  tracks, configuration changes mid-playback.
* [PCM playback engine](../development/studio-playback-manual-test.md) — real `QAudioSink` /
  `DualPcmStreamDevice` behavior on a physical audio device, seek/pause/resume smoke tests.

## Where Studio fits in the workflow

Use Studio when you want human-in-the-loop sound design: open the master composition JSON, iterate
channel assignments, compare variants by ear, and export the winner — all validated against the same
constraints the CLI enforces. Use the CLI for scripted/batch work (see
[Arrangement](arrangement.md#batch-runners)).

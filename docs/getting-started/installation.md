# Installation

## System requirements

* **Python `>= 3.10`**
* **OS:** Windows, Linux, or macOS
* **MADS assembler:** required only when compiling `.xex` binaries or running 6502 size/parity checks.
  Download it from [mads.atari8.info](http://mads.atari8.info/). On Windows the expected location is
  `tools/mads/mads.exe` inside your working copy — note that `tools/` is *not* part of the public
  repository (it is gitignored), so place the executable there yourself or pass `--mads PATH` to the CLI.
  On Linux/macOS provide `mads` on `PATH` or pass `--mads PATH`.

## Python environment setup

```bash
git clone https://github.com/grzes71/atari-music-composer.git
cd atari-music-composer

# Create and activate a virtual environment
python -m venv .venv

# Windows (PowerShell):
.venv\Scripts\Activate.ps1
# Linux / macOS:
source .venv/bin/activate

# Install the package in editable mode
pip install -e .
```

Output directories for generated files (WAV, ASM, XEX, JSON) are created automatically by the CLI.

### Optional extras

```bash
# Desktop GUI (Atari Music Composer Studio, PySide6)
pip install -e ".[studio]"

# Packaging and semantic-release tooling used by the release workflow
pip install -e ".[dev]"

# Documentation site build (MkDocs Material)
pip install -e ".[docs]"
```

### Optional runtime tools

* `pip install openai` — required only for **live** AI generation (`openai`/`deepseek` providers);
  the offline `mock` provider needs nothing.
* `pip install py65` — required for 6502 CPU emulation parity tests (`tests/test_xex_e2e_py65.py`).

## Core dependencies

Core package dependencies declared in
[`pyproject.toml`](https://github.com/grzes71/atari-music-composer/blob/main/pyproject.toml):

| Package | Used for |
| --- | --- |
| `pydantic >= 2.0.0` | Schema models and validation (`AICompositionDoc`, `InstrumentCatalogDocument`, `IRSong`) |
| `numpy >= 1.24.0` | Hardware POKEY audio synthesis buffers |
| `click >= 8.0.0` | CLI commands |
| `matplotlib >= 3.7.0` | Visualization and analysis plots |
| `pytest >= 7.0.0` | Test suite |
| `python-dotenv >= 1.0.0` | `.env` configuration loading |

## AI provider and `.env` configuration

Configuration uses a 4-level priority chain in
[`src/atari_music/config.py`](https://github.com/grzes71/atari-music-composer/blob/main/src/atari_music/config.py)
(highest to lowest):

1. Explicit CLI flags (e.g. `--provider`, `--model`, `--env-file`)
2. System environment variables
3. `.env` file values (default `.env`, or a custom path via `--env-file PATH`)
4. Code defaults (`AI_PROVIDER=deepseek`, `AI_BASE_URL=https://api.deepseek.com`, `AI_MODEL=deepseek-flash`)

Copy [`.env.example`](https://github.com/grzes71/atari-music-composer/blob/main/.env.example) to `.env`
and fill in your credentials locally (`.env` is gitignored — never commit real keys):

```env
# Supported CLI providers: deepseek, openai, mock
AI_PROVIDER=deepseek
AI_API_KEY=your_api_key_here
AI_BASE_URL=https://api.deepseek.com
AI_MODEL=deepseek-flash
LOG_LEVEL=INFO
```

Supported providers:

| Provider | How it is selected | Notes |
| --- | --- | --- |
| `deepseek` | Default, or `--provider deepseek` / `AI_PROVIDER=deepseek` | OpenAI-compatible Chat Completions API at `https://api.deepseek.com` |
| `openai` | `--provider openai` / `AI_PROVIDER=openai` | Works with OpenAI or any OpenAI-compatible endpoint via `AI_BASE_URL` / `OPENAI_BASE_URL` |
| `mock` | `--provider mock` / `AI_PROVIDER=mock` | Offline deterministic mock; no API key or network needed — ideal for trying the pipeline |

Backward-compatible fallbacks (`DEEPSEEK_API_KEY`, `OPENAI_API_KEY`, …) are honored when the `AI_*`
variables are unset. API keys are masked in diagnostics and are never written into exported JSON,
`.asm`, `.xex`, or test manifests; placeholder values such as `your_api_key_here` are rejected for live
requests.

## Verify the installation

```bash
python -m atari_music --version
python -m atari_music list-instruments --target xex_v2
```

You should see the installed version and the 16 curated SSOT catalog instruments. If both work, continue
with [Your First Composition](first-composition.md).

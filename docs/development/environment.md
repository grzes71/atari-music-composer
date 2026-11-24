# Environment & Project Structure

## Development environment

```bash
git clone https://github.com/grzes71/atari-music-composer.git
cd atari-music-composer
python -m venv .venv
.venv\Scripts\Activate.ps1          # Windows (PowerShell)
# source .venv/bin/activate        # Linux / macOS

pip install -e .                    # core toolchain
pip install -e ".[studio]"          # optional: Studio GUI (PySide6)
pip install -e ".[docs]"            # optional: documentation site build
pip install openai py65             # optional: live AI tests / 6502 emulation tests
```

Local-only tooling (gitignored, not in the public checkout):

* **MADS** — place at `tools/mads/mads.exe` (Windows) or on `PATH`; needed to compile `.xex` binaries
  and run MADS/ASAP-dependent tests. Tests skip cleanly via `tests/conftest.py`'s
  `require_local_artifact()` helper when it is absent.
* **AltirraSDL / AltirraBridge SDK** — optional full-system emulator tests (`emulator` marker).

## Project structure

```text
atari-music-composer/
├── mkdocs.yml                  # Documentation site configuration (this site)
├── pyproject.toml              # Packaging, dependencies, pytest markers, semantic-release
├── main.py                     # Configuration-loading entry point demo (AI client init)
├── generate_arrangements.py    # Adaptive batch arrangement runner
├── player.asm, hardware.asm    # Root copies of the 6502 sources used by legacy builds
├── data/
│   └── instrument_libraries/   # Legacy Lead Library v0.1
├── examples/
│   ├── ai/                     # AI-generated example compositions (JSON)
│   └── songs/                  # Hand- and AI-written example songs (DSL/JSON + bindings)
├── docs/                       # Documentation site sources (this site)
├── scripts/                    # Research/release/verification scripts (see individual headers)
├── src/atari_music/            # The package (module map in [System Overview](../architecture/overview.md))
├── tests/                      # Pytest suite (see [Testing Strategy](testing.md))
├── tools/                      # Local binary toolchain (MADS, ASAP) — gitignored
└── output/                     # Generated artifacts (WAV/XEX/JSON) — gitignored
```

Directories such as `reports/`, `dataset/`, `experiments/`, `listening_test*/`, and the root
`stage*.md`/`report_*.md` research reports are local research artifacts: intentionally excluded from
the public repository via `.gitignore`, so they will be absent in fresh checkouts and CI.

## Conventions

### Versioning & releases

The project uses [Conventional Commits](https://www.conventionalcommits.org/) driving
[python-semantic-release](https://python-semantic-release.readthedocs.io/) (configured in
`pyproject.toml`): `fix -> patch`, `feat -> minor`, "`BREAKING CHANGE:`" footer or `!` suffix `-> major`;
`main` is the release branch. On each *merged pull request* to `main`,
[`.github/workflows/release.yml`](https://github.com/grzes71/atari-music-composer/blob/main/.github/workflows/release.yml)
runs the core test suite, bumps the version in `pyproject.toml` and `src/atari_music/__init__.py`,
appends to `CHANGELOG.md`, builds the sdist/wheel, tags (`v{version}`), and publishes a GitHub Release.
Work on feature branches and open pull requests against `main`.

### Continuous integration

| Workflow | Trigger | Purpose |
| --- | --- | --- |
| `release.yml` | merged PR to `main` | core tests + semantic-release + GitHub Release |
| `docs.yml` | push to `main` (docs paths) / manual | strict MkDocs build + GitHub Pages deployment (this site) |

### Changelog & history

* `CHANGELOG.md` — semantic-release changelog (embedded as this site's [Changelog](../about/changelog.md) page).
* `HISTORY.md` — detailed dated technical change narrative across stages.

### Code style

Standard Python conventions without a separate formatter/linter configuration: type hints
(`from __future__ import annotations`), pydantic models for all serialized data with
`extra="forbid"` on interface models, docstrings on public modules. Follow the patterns of the
module you are touching; keep new CLI flags and behaviors in `cli.py` consistent (strict validation,
no silent fallbacks).

## Documentation development

The site is built with MkDocs + Material:

```bash
pip install -e ".[docs]"   # mkdocs + mkdocs-material

python -m mkdocs serve                  # live preview at http://127.0.0.1:8000/
python -m mkdocs build --strict         # warnings are errors (what CI enforces)
```

Sources live in [`docs/`](https://github.com/grzes71/atari-music-composer/tree/main/docs) with
[`mkdocs.yml`](https://github.com/grzes71/atari-music-composer/blob/main/mkdocs.yml) at the repository
root. Every page under `docs/` must be listed in `nav` (the strict build enforces this) and links must
resolve. Deployment to GitHub Pages runs automatically through
[`.github/workflows/docs.yml`](https://github.com/grzes71/atari-music-composer/blob/main/.github/workflows/docs.yml)
— no manual publishing steps.

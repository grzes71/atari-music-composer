# Testing Strategy

The test suite is organized around one principle: **tests must state the contract they protect.** Every
test module carries exactly one category marker, and the classification itself is verified by a script.

## Test markers

Declared in `pyproject.toml` and audited by
[`scripts/verify_test_classification.py`](https://github.com/grzes71/atari-music-composer/blob/main/scripts/verify_test_classification.py):

| Marker | Scope |
| --- | --- |
| `core` | Tests verifying the active CORE production pipeline and contracts |
| `audio` | Fast CORE subset protecting POKEY semantics, IR, MADS export, `player.asm`, XEX layout, and sound profiles (must be `core` first) |
| `experimental` | Tests verifying research experiments (stages 9c–25, E26–E30, lead library spec) |
| `legacy` | Tests verifying historical stages 1–8 and deprecated v1–v3 generators |
| `live` | Tests requiring real LLM API access and credentials — **excluded by default** |
| `emulator` | Optional full-system Atari XL/XE emulator integration tests (AltirraSDL / AltirraBridge) |

Each test carries exactly one of `core` / `experimental` / `legacy` (plus optionally `audio`, `live`,
or `emulator`); the audit script fails when markers are missing, duplicated, or inconsistent.

## Running the suites

```bash
# Verify test marker classification integrity (CI runs this first)
python scripts/verify_test_classification.py

# Default: everything offline (pyproject addopts already excludes 'live')
pytest

# All offline CORE production tests (architecture boundaries, IR, exporters, py65, CLI)
pytest -m "core and not live" -q

# Fast POKEY / IR / MADS / player.asm / XEX regression subset
pytest -m "audio and not live" -q

# Stage C/D/E + Studio + presets + rhythmic-density regressions
pytest tests/test_stage_c_player_v2_parity.py tests/test_stage_d_integration.py \
  tests/test_stage_e_arrangement.py tests/test_studio_vertical_slice.py \
  tests/test_studio_presets.py tests/test_studio_xex_export.py tests/test_rhythmic_density.py -v

# Opt into live LLM tests (requires credentials in .env)
pytest -m live
```

## Local artifacts and clean skipping

`tests/conftest.py` provides `require_local_artifact(path)`, which *skips* a test when a local-only
asset is missing. Directories like `dataset/`, `music/`, `listening_test*/`, `experiments/`,
`stage11_xex/`, `reports/`, generated stage reports, and `tools/` binaries (MADS, ASAP) are
intentionally gitignored, so they will not exist in fresh checkouts. The result: the same test suite
runs everywhere, skipping only work that is physically impossible, while CI
([`release.yml`](https://github.com/grzes71/atari-music-composer/blob/main/.github/workflows/release.yml))
executes `python -m pytest -m "core and not live" -q` after the classifier check.

## The verification pyramid

1. **Architecture boundaries** (`test_architecture_boundaries.py`) — structural rules that keep the
   production code decoupled from research/experimental code.
2. **Unit/contract tests** — schema validation, DSL parser, catalog integrity, `POKEYRuntime`
   conflict rules, planner policies, CLI option contracts.
3. **Audio parity tests** (`test_pokey_*.py`, `test_stage_c_player_v2_parity.py`, …) — WAV preview,
   `frame_simulator`, and (via `py65`) compiled-player register parity for v1/v2/16-bit songs.
4. **End-to-end XEX** (`test_xex_e2e_py65.py`) — boots the exact produced `.xex` in `py65`, asserts
   `$D200–$D208` bit-exactness, the on-screen harness, keyboard mute/pause, and memory safety
   (see [XEX Verification](../reference/xex-verification.md)).
5. **Optional full-system emulator** (`test_xex_altirra.py`, `emulator`) and **live LLM validation**
   (`test_live_production.py`, `live`) — for local deep verification only.

## Manual QA

For Studio GUI paths that cannot be asserted headlessly (real audio devices, WASAPI playback):
[Studio A/B manual test](studio-ab-manual-test.md) and
[Studio playback manual test](studio-playback-manual-test.md). Headless Studio service tests
(`test_studio_*.py`) cover everything up to the audio device boundary.

## Adding tests

* Put the file in `tests/`, mirroring the module under test.
* Mark it with exactly one category marker (`core` / `experimental` / `legacy`) and, when relevant,
  `audio`.
* Use `require_local_artifact()` for anything depending on gitignored data — do not invent try/except
  skips.
* Keep runtime reasonable: `audio` is the fast CI-parallel subset; expensive end-to-end work belongs in
  `core` but should stay under a few minutes.
* Run `python scripts/verify_test_classification.py` before pushing.

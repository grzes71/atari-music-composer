# Project History

<!-- AGENT INSTRUCTIONS: Prepend new entries directly below this comment. Use format ## [YYYY-MM-DD] - [Brief Title] followed by a bulleted list of technical changes with relative paths. -->

## [2026-11-17] - Add Opt-In Rich Prompt Profile, Pre-Composition Brief, and Musical Critique Loop (`ai-compose`)

Added an opt-in `rich` prompt profile (`--prompt-profile rich`), pre-composition `MusicalBrief` planning (`--plan-first`), post-validation musical critique/revision loop (`--quality-passes`), DSL/JSON catalog parity, and new CLI flags while keeping the default `classic` profile byte-for-byte unchanged.

- Created [src/atari_music/ai/prompt_library.py](src/atari_music/ai/prompt_library.py) with ground-truth PAL 50 Hz timing grid (`build_timing_grid_section`, `--tempo-grid [describe|exact]`), POKEY chiptune craft techniques (`build_craft_section`), archetype idioms (`build_style_idioms_section`), `INSTRUMENT` directive syntax help, and validated `RICH_DSL_EXAMPLE` / `rich_json_example()`.
- Created [src/atari_music/ai/critique.py](src/atari_music/ai/critique.py) (`MusicalCritique.from_doc`, `format_revision_feedback`) evaluating melodic range, pitch class diversity, duration variety, dynamic contrast, consonance, active channels, and structural diversity.
- Added `MusicalBrief` models and `CompositionAttempt.critique_score` / `critique_findings` in [src/atari_music/ai/schema.py](src/atari_music/ai/schema.py), and extended `CompositionRequest` in [src/atari_music/ai/providers/base.py](src/atari_music/ai/providers/base.py).
- Added `get_system_prompt` and `get_user_prompt` dispatchers and opt-in DSL catalog parity in [src/atari_music/ai/prompts.py](src/atari_music/ai/prompts.py); updated [src/atari_music/ai/providers/openai.py](src/atari_music/ai/providers/openai.py), [src/atari_music/ai/providers/mock.py](src/atari_music/ai/providers/mock.py), and [src/atari_music/ai/client.py](src/atari_music/ai/client.py) (`_run_quality_passes`, `plan_first`).
- Extended `ai-compose` in [src/atari_music/cli.py](src/atari_music/cli.py) with `--key`, `--mode`, `--notes`, `--prompt-profile`, `--temperature`, `--tempo-grid`, `--plan-first`, and `--quality-passes`, and documented them in [README.md](README.md) and [SKILL.md](SKILL.md).
- Added [tests/test_prompt_library.py](tests/test_prompt_library.py), classic snapshot regression test in [tests/test_prompts.py](tests/test_prompts.py), and [scripts/benchmark_prompts.py](scripts/benchmark_prompts.py).


## [2026-11-17] - Add Valid YAML Frontmatter to `SKILL.md`

Added required `name` and `description` YAML frontmatter to [SKILL.md](SKILL.md) to fix skill loader parsing (`failed to parse frontmatter`).

- Prepended `---` YAML frontmatter block (`name: atari-music-composer`, `description: >- ...`) at the top of [SKILL.md](SKILL.md).

## [2026-11-17] - Update `SKILL.md` for Instrument Catalog, `arrange`, and `generate_arrangements.py`

Updated [SKILL.md](SKILL.md) to reflect the SSOT instrument catalog workflow, `v1`/`v2` output formats, `arrange`, and `generate_arrangements.py`.

- Updated Capabilities Matrix, Pipeline Architecture, and Section 8 (`music_data.asm` `v1`/`v2` format details) in [SKILL.md](SKILL.md).
- Added CLI reference subsections for `list-instruments` / `inspect-instrument` / `validate-instruments` (including the new JSON fields), `arrange`, and `generate_arrangements.py`, plus **Workflow H** and decoupled arrangement heuristics in Sections 11–12 of [SKILL.md](SKILL.md).

## [2026-11-17] - Unified Smart Batch Arrangement Script (`generate_arrangements.py`)

Replaced the separate 8-bit and 16-bit PowerShell batch scripts with a single stdlib-only Python orchestrator that queries `atari-music.exe`, analyzes each composition's hardware mode and per-channel note statistics, ranks matching instruments, compiles numbered WAV/XEX outputs plus a `vanilla` (`v1`) baseline, and writes `arrangements.log`.

- Enriched `atari-music list-instruments --json` in [src/atari_music/cli.py](src/atari_music/cli.py) with `midi_range`, `waveform_family`, `preferred_clock_hz`, `required_audctl_bits`, `poly4_safe_tuning`, and `envelope` fields (and added assertions in [tests/test_stage_d_integration.py](tests/test_stage_d_integration.py)).
- Added [generate_arrangements.py](generate_arrangements.py) supporting `.dsl` (auto-converted via `atari-music.exe import-dsl`) and `.json` (`AICompositionDoc` / `IRSong`), auto-detecting `uses_16bit_bass` and per-channel roles (`bass`, `melody`, `harmony`, `percussion`), scoring compatible instruments from `list-instruments --target xex_v2 --json` by MIDI range, clock mode, duration/short-note articulation, and pitch count, selecting diverse top-ranked `01_...`..`06_...` variants plus `vanilla` (`v1`), rendering WAV + XEX, and logging full match scores and CLI commands to `arrangements.log`.
- Removed legacy `generate-arrangements-8bit.ps1` and `generate-arrangements-16bit.ps1` and documented [generate_arrangements.py](generate_arrangements.py) in [README.md](README.md).
- Added `@pytest.mark.core` test coverage in [tests/test_generate_arrangements_script.py](tests/test_generate_arrangements_script.py).

## [2026-11-16] - Use `atari-music.exe` & Add `vanilla` (`v1`) Variant in Batch Scripts

Switched both PowerShell batch arrangement scripts from invoking `python -m atari_music` to calling `atari-music.exe` directly, and added a `vanilla` variant targeting the legacy `v1` player.

- Replaced `-PythonPath` / `Resolve-AtariMusicPython` with `-AtariMusicPath` / `Resolve-AtariMusicExe` in [generate-arrangements-8bit.ps1](generate-arrangements-8bit.ps1) and [generate-arrangements-16bit.ps1](generate-arrangements-16bit.ps1), checking `-AtariMusicPath`, `.venv\Scripts\atari-music.exe` (and `.venv/bin/atari-music`), then `PATH`, verified via `atari-music.exe --version`.
- Invoked `atari-music.exe` directly for `import-dsl` and `arrange` calls in both scripts.
- Added `$variants` entry `vanilla` (`PlayerVersion = "v1"`) to both [generate-arrangements-8bit.ps1](generate-arrangements-8bit.ps1) and [generate-arrangements-16bit.ps1](generate-arrangements-16bit.ps1), running `arrange` with `--player-version v1` and without `--channel-instrument` / `--program-change-policy` overrides so original composition instruments are compiled for `v1` alongside the six `v2` presets.

## [2026-11-16] - Fix Relative `-OutputDirectory` Resolution Against PowerShell `$PWD`

Fixed a Windows PowerShell working-directory mismatch when invoking the batch arrangement scripts from outside the user's home directory or repository root.

- Replaced `[System.IO.Path]::GetFullPath($OutputDirectory)` with `$ExecutionContext.SessionState.Path.GetUnresolvedProviderPathFromPSPath($OutputDirectory)` in [generate-arrangements-16bit.ps1](generate-arrangements-16bit.ps1) and [generate-arrangements-8bit.ps1](generate-arrangements-8bit.ps1) so relative output paths resolve against PowerShell's `(Get-Location)` instead of `.NET`'s `[System.Environment]::CurrentDirectory` (`$HOME`).

## [2026-11-16] - Fix Release Workflow & Clean-Checkout CORE CI Parity

Aligned the GitHub Release workflow and CORE test suite so clean checkouts pass without depending on excluded research datasets or Windows-only binaries.

- Guarded `test_the_library_entry_is_accepted_on_build_xex` in [tests/test_c1_modulation.py](tests/test_c1_modulation.py) with `require_local_artifact(MADS)` matching existing MADS-dependent tests.
- Updated [.github/workflows/release.yml](.github/workflows/release.yml) to execute `python scripts/verify_test_classification.py` followed by `python -m pytest -m "core and not live" -q`, matching the repository's CORE boundary contract.

## [2026-11-16] - Refine `.gitignore` to Expose Core Source Reporters & Trackable Example Fixtures

Adjusted [.gitignore](.gitignore) exclusions so missing source modules and small canonical composition examples are no longer hidden from clean repository checkouts and CI test runs.

- Removed `src/atari_music/stage3_reporter.py` and `src/atari_music/stage4_reporter.py` from [.gitignore](.gitignore) (imported by `src/atari_music/cli.py` and required by `tests/test_architecture_boundaries.py`).
- Replaced the blanket `/examples` rule in [.gitignore](.gitignore) with `/examples/*`, `!/examples/songs/`, `!/examples/ai/`, and explicit exclusions for `/examples/ai/live/`, `/examples/ai/live2/`, `/examples/ai/*.asm`, `/examples/ai/*.wav`, and `/examples/ai/*.xex`, exposing `39` small files (`540.3 KB`) while keeping `~158 MB` of generated WAV listening packages ignored.

## [2026-11-16] - Auto-Conversion of Music DSL (.dsl) Inputs in PowerShell Batch Scripts

Added automatic `.dsl` -> temporary JSON conversion to both PowerShell batch arrangement scripts so users can pass Music DSL files directly to `-InputFile`.

- Updated [generate-arrangements-16bit.ps1](generate-arrangements-16bit.ps1) and [generate-arrangements-8bit.ps1](generate-arrangements-8bit.ps1) to detect `.dsl` input files case-insensitively, convert them once via `python -m atari_music import-dsl ... --output-json` into a temporary file in `%TEMP%`, validate `hardware.use_16bit_bass` / `uses_16bit_bass` before creating `$OutputDirectory`, pass the temporary JSON to `arrange`, and remove the temporary file reliably inside a `try ... finally` block.

## [2026-11-16] - PowerShell Batch Arrangement Scripts Hardening

Hardened the 16-bit and 8-bit PowerShell batch arrangement wrappers for standalone execution outside an activated virtual environment and full POKEY IR / AI Composition JSON compatibility.

- Updated [generate-arrangements-16bit.ps1](generate-arrangements-16bit.ps1) and [generate-arrangements-8bit.ps1](generate-arrangements-8bit.ps1) with `Resolve-AtariMusicPython` (auto-detecting `.venv\Scripts\python.exe` / `.venv/bin/python`, optional `-PythonPath`, and pre-flight `import atari_music` check), safe `Invoke-AtariMusicCli` native `stderr` handling compatible with Windows PowerShell 5.1 `$ErrorActionPreference = "Stop"`, and non-empty `.wav`/`.xex` file size validation.
- Updated input JSON validation in both scripts to detect both AI Composition JSON (`hardware.use_16bit_bass`) and POKEY IR JSON (`uses_16bit_bass`), emit clear `.dsl` conversion guidance, and defer output directory creation until validation passes.
- Added `Harmony = "harmony_soft_square"` (`CH2`) assignment across all 6 variants in [generate-arrangements-8bit.ps1](generate-arrangements-8bit.ps1) while keeping `CH2` unassigned/reserved for `CH1+CH2` pairing in [generate-arrangements-16bit.ps1](generate-arrangements-16bit.ps1).

## [2026-11-16] - Automated Instrument System Test Suite Generator (`generate_instrument_test_suite.py`)

Added an automated end-to-end test-suite generator script and mocked-subprocess regression tests exercising the decoupled AI-once composition + multi-variant Stage E arrangement workflow without storing or logging secrets or mutating source compositions.

- Added [scripts/generate_instrument_test_suite.py](scripts/generate_instrument_test_suite.py) (`TEST_SUITE_SPECS`, `inspect_real_ai_provider()`, `build_ai_compose_command()`, `build_arrange_command()`, `run_test_suite()`, `main()`) supporting `--output-dir` (default `output/instrument_tests`), `--seed`, `--only` (`dark|action|mystery|experimental`), `--dry-run`, `--force`, and `--env-file`.
- Enforced pre-flight validation of a non-mock `.env`/environment provider (`openai` or `deepseek` with valid API key, never passing `--provider mock` or recording secrets), sequential execution (`shell=False`) of 4 `ai-compose` JSON runs (no WAV/ASM) followed by 12 `arrange` variants (`arrangement.json`, `<variant>.wav`, `<variant>.xex` via `--program-change-policy replace`, no ASM), overwrite protection without `--force`, per-variant file/size checks, `composition_musical_fingerprint` verification, and `manifest.json` reporting.
- Added [tests/test_generate_instrument_test_suite.py](tests/test_generate_instrument_test_suite.py) (`pytest.mark.core`, 11 tests) with mocked `subprocess.run` verifying 4+12 command counts, CLI flags, absence of secrets and `--provider mock` / `--output-asm`, `--dry-run`, `--only`, `--force` overwrite guard, missing/mock provider aborts, compose-failure variant skipping, variant/WAV failure isolation, and `composition_musical_fingerprint` mismatch detection.

## [2026-11-16] - Stage E: Decoupled Composition vs Arrangement Pipeline (`arrange` & `arrange_song`)

Separated musical composition from POKEY instrument realization so a saved composition JSON (AI Composition JSON or POKEY IR JSON) can be repeatedly re-arranged across 4 POKEY channels and exported to WAV/ASM/XEX without modifying the source composition, invoking AI again, or altering `player.asm` / binary format v2.

- Added `ProgramChangePolicy` (`preserve | replace | remove`), `normalize_program_change_policy()`, `composition_musical_fingerprint()` (SHA-256 hash over pitch, MIDI, duration, volume, rest, tempo, pattern structure, and sequence excluding instrument state), and immutable deep-copy `arrange_ir_song()` with channel-isolated policy handling and `POKEYRuntime` validation in [src/atari_music/instruments/planner.py](src/atari_music/instruments/planner.py), re-exported via [src/atari_music/instruments/__init__.py](src/atari_music/instruments/__init__.py).
- Extracted shared `build_xex_from_result()` in [src/atari_music/ai/client.py](src/atari_music/ai/client.py) (reused by both `build_xex_from_composition()` and `MusicGenerationResult.build_xex()`), supporting isolated temporary harness assembly when `--output-asm` and `--output-xex` target matching stems or `--output-asm` is omitted.
- Added public API `arrange_song()` and `MusicGenerationResult.export_mads()` / `MusicGenerationResult.build_xex()` helpers in [src/atari_music/api.py](src/atari_music/api.py) using the existing v1/v2 WAV synthesis, MADS export, and XEX build pipelines with zero AI invocation.
- Added CLI command `arrange` in [src/atari_music/cli.py](src/atari_music/cli.py) supporting `--channel-instrument CH=INSTRUMENT_ID`, `--program-change-policy preserve|replace|remove`, `--player-version auto|v1|v2`, and selective `--output-json` / `--output-wav` / `--output-asm` / `--output-xex` generation without altering input files.
- Added comprehensive integration and immutability audit tests in [tests/test_stage_e_arrangement.py](tests/test_stage_e_arrangement.py) verifying AI-once / multi-variant WAV+ASM+XEX workflow, identical note/rest/tempo/sequence hashes across variants, all three `PROGRAM_CHANGE` policies with channel isolation, v1/v2 format handling (including `py65` parity), validation errors, and blocked AI provider invocation during `arrange`.

## [2026-11-16] - Stage D: Opt-in SSOT Instrument Integration Across Composer v4, AI Pipeline & CLI

Integrated the SSOT instrument catalog (`data/instruments/catalog.json`), `POKEYRuntime` validation, and Stage C v2 `PROGRAM_CHANGE`/behavior support into Composer v4, the AI pipeline, and CLI without altering default v1 outputs, `player.asm`, or the `SONG_FORMAT_VERSION = 2` layout.

- Added CORE planning and format resolution module [src/atari_music/instruments/planner.py](src/atari_music/instruments/planner.py) (exported via [src/atari_music/instruments/__init__.py](src/atari_music/instruments/__init__.py) and registered in `CORE_MODULES` in [tests/test_architecture_boundaries.py](tests/test_architecture_boundaries.py)) providing `ProgramChangeSpec`, `InstrumentPlanError`, `parse_channel_instrument_specs()`, `parse_program_change_specs()`, `resolve_channel_instrument_plan()`, `resolve_export_format_version()` (`auto` -> `1` when v1-compatible, `2` only when required), and `select_ai_catalog_instrument_id()`.
- Integrated opt-in `channel_instruments`, `program_changes`, `instrument_catalog_path`, and `player_version` into [src/atari_music/composer_v4.py](src/atari_music/composer_v4.py) and [src/atari_music/api.py](src/atari_music/api.py), recording catalog provenance in `metadata.sound_profiles`, supporting v2 WAV rendering in `MusicGenerationResult.render_wav()`, and leaving default `compose_song_v4()` / `generate_music()` behavior bit-identical in v1.
- Integrated SSOT catalog awareness into the AI pipeline: added optional `catalog_id` in [src/atari_music/ai/schema.py](src/atari_music/ai/schema.py), catalog options on `CompositionRequest` in [src/atari_music/ai/providers/base.py](src/atari_music/ai/providers/base.py), prompt catalog listing and non-random `PROGRAM_CHANGE` guidance in [src/atari_music/ai/prompts.py](src/atari_music/ai/prompts.py), `POKEYRuntime` checks in [src/atari_music/ai/validation.py](src/atari_music/ai/validation.py), v2 multi-instrument compilation in [src/atari_music/ai/composition.py](src/atari_music/ai/composition.py), catalog-backed generation with coherent drum kits / contrasting section transitions in [src/atari_music/ai/providers/mock.py](src/atari_music/ai/providers/mock.py), and v1/v2 size/XEX handling in [src/atari_music/ai/client.py](src/atari_music/ai/client.py).
- Added CLI commands `list-instruments`, `inspect-instrument`, and `validate-instruments`, plus opt-in catalog/`--player-version` options on `compose`, `ai-compose`, `export-mads`, `import-json`, `import-dsl`, and `build-xex` in [src/atari_music/cli.py](src/atari_music/cli.py) without breaking legacy `--instrument` (`Lead Library v0.1`) semantics.
- Added [tests/test_stage_d_integration.py](tests/test_stage_d_integration.py) covering Composer v4 v1 regression, static `core_v1` auto-v1 preservation, 4-channel v2 + `PROGRAM_CHANGE` end-to-end `py65` parity, AI catalog vs legacy modes, validation error paths, and CLI commands; verified `python scripts/verify_test_classification.py` (`2444` cases, `PASS`), `python -m pytest -m "core and not live" -q` (`615 passed, 1829 deselected`), `python -m pytest -m "audio and not live" -q` (`402 passed, 2042 deselected`), and `python -m pytest tests/test_stage_d_integration.py -v` (`8 passed`).

## [2026-11-16] - Stage C Iteration 1: IR v2 Behavior Engine, MADS Exporter v2 & player.asm v2

Implemented Stage C Iteration 1 on branch `feature/instrument-system-stage-c` (branched from `920e406`) without modifying default `SONG_FORMAT_VERSION = 1` output, delayed vibrato/arpeggio/HPF XOR in `player.asm`, `composer_v4.py`, `ai/`, `cli.py`, or the 67-profile bank under `tests/data/sound_profiles/bank/`.

- Extended [src/atari_music/ir.py](src/atari_music/ir.py) with Stage C v2 constants (`MAX_V2_INSTRUMENTS = 32`, `MAX_V2_MACRO_STEPS = 8`, `MAX_V2_CONSECUTIVE_COMMANDS = 4`, `OPCODE_PROGRAM_CHANGE = 0x01`, `MACRO_FLAG_*`, `INST_FLAG_MOD_OCTAVE_PULSE`), active `IRMacroStep` v2 fields (`frames_per_step`, `audf_mode`, `fixed_audf`, `audc_dist`, `vol_override`, `is_v2_step()`, `from_transient_step()`), `IRPitchEnvelope`, `IRInstrument.from_catalog_profile()`, `IRNote.pending_program_changes`, `IRSong.initial_channel_instruments`, loop-invariant `plan_v2_pattern_streams()`, `song_requires_v2()`, and exact `calculate_ir_binary_size(song, format_version=1|2)`.
- Added opt-in `SONG_FORMAT_VERSION_2 = 2` Structure-of-Arrays export and shared deduplicated macro pool (`_validate_and_build_v2_tables`, `_export_mads_asm_v2`), `validate_v2_track_bytes()`, `FormatVersionError`, and `StreamValidationError` in [src/atari_music/mads_exporter.py](src/atari_music/mads_exporter.py), while keeping default `format_version=1` unchanged and explicitly refusing unsupported v2 features in v1 export.
- Extended [src/atari_music/asm/player.asm](src/atari_music/asm/player.asm) (synced identically to root [player.asm](player.asm)) with `SONG_FORMAT_VERSION = 1` vs `2` runtime dispatch, `load_v2_inst_ch` SoA loader, 0-tick `PROGRAM_CHANGE` parser (including pattern-start `@reload_track_ptr` fix, `MAX_V2_PARSE_COMMANDS = 8` guard, and out-of-range opcode/instrument muting), shared Transient Macro Engine, and per-frame signed Pitch Envelope + `add_signed_clamp` saturation; measured `1785 B` ROM (`263 B` below `2048 B` limit), `10 B` Zero Page (`$80..$89`, zero collision with `$8A..$8D`), `147 B` BSS RAM, `1117–2572` active 4-ch macro cycles, and `5577` cycles on simultaneous 4-ch `PROGRAM_CHANGE` + macro + pitch.
- Updated `PLAYER_ASSEMBLED_BYTES_RECORDED = 1785` in [src/atari_music/stage15.py](src/atari_music/stage15.py) and segment range expectation in [tests/test_xex_layout.py](tests/test_xex_layout.py), documented the binary specification in [docs/SONG_FORMAT_V2.md](docs/SONG_FORMAT_V2.md), added independent 6502 POKEY frame oracle [src/atari_music/frame_simulator.py](src/atari_music/frame_simulator.py) (registered in `CORE_MODULES` in [tests/test_architecture_boundaries.py](tests/test_architecture_boundaries.py)), and added v1/v2 `py65` 0-byte parity, corruption guard, and ASAP 8.0.0 integration tests in [tests/test_stage_c_ir_and_exporter_v2.py](tests/test_stage_c_ir_and_exporter_v2.py) and [tests/test_stage_c_player_v2_parity.py](tests/test_stage_c_player_v2_parity.py).
- Verified `python -m pytest tests/test_stage_c_ir_and_exporter_v2.py tests/test_stage_c_player_v2_parity.py -v` (`20 passed`), `python scripts/verify_test_classification.py` (`2436` cases / `609` core / `607` core offline / `401` audio, `PASS`), `python -m pytest -m "core and not live" -q` (`607 passed, 1829 deselected`), and `python -m pytest -m "audio and not live" -q` (`401 passed, 2035 deselected`).

## [2026-11-16] - Post-Audit Fix: Align POLY4 & POLY5 Hardware Order and STIMER Time-Domain Parity

- Added `_hw_lfsr_xnor_sequence()` in [src/atari_music/pokey_hw.py](src/atari_music/pokey_hw.py) modeling real POKEY right-shift XNOR polynomial counters from post-reset zero state (`a[0..3]=0`, `a[n]=~(a[n-4]^a[n-3])` for `POLY4`, sum=7; `a[0..4]=0`, `a[n]=~(a[n-5]^a[n-3])` for `POLY5`, sum=15 active gate), fixing time-reversal in `generate_lfsr4_sequence()` and `generate_lfsr5_sequence()` while keeping `legacy_polarity=True` / `legacy_order=True` options for legacy constant preservation and leaving `POLY9`/`POLY17` untouched.
- Separated hardware renderer tables `_POLY4_BITS` and `_POLY5_HW_GATE` from legacy `POLY4_SEQ` and `POLY5_SEQ` in [src/atari_music/pokey_synth.py](src/atari_music/pokey_synth.py), handled `Waveform.VOLUME_ONLY` explicitly in `_evaluate_channel_ticks()`, and skipped LFSR tick evaluation on muted HPF clock-only channels (`audible[ch] == False`) so `AUDC=$10` (`vol=0`) does not trigger unused poly calculations or alter `out_bits`.
- Expanded [tests/test_pokey_hardware_synthesis.py](tests/test_pokey_hardware_synthesis.py) with explicit independent POKEY XNOR reference bitstreams, post-`STIMER` bit-step verification against `ASAP 8.0.0`, time-domain cross-correlation parity tests for `$40` (`AUDF = 2, 4, 24, 76`), mod-5 vs mod-15 `POLY4` stall tests with/without `STIMER`, `CH3+CH4` 16-bit tests for `$08`, `$09`, and `$28` plus dynamic 8-bit ↔ 16-bit switching, and HPF control `AUDC=$10` (`vol=0`) parity.
- Verified `python -m pytest tests/test_pokey_hardware_synthesis.py tests/test_core_v1_profile_synth.py -v` (`30 passed`), `python -m pytest tests/test_pokey_timbre_experiment.py::TestDeliveredArtefacts -q` (`5 passed`), `python scripts/verify_test_classification.py` (`2416` cases / `589` core / `587` core offline / `386` audio, `PASS`), `python -m pytest -m "core and not live"` (`587 passed`), and `python -m pytest -m "audio and not live"` (`386 passed`).

## [2026-11-16] - Stage B: Hardware-Accurate POKEY Synthesis & CORE_V1 Profile Rendering

Implemented Stage B on branch `feature/instrument-system-stage-b` (branched from `4b7eaa6`) without modifying `SONG_FORMAT_VERSION`, `player.asm`, `mads_exporter.py`, `ir.py`, `composer_v4.py`, `ai/`, `cli.py`, `POKEYRuntime` capability rules, or the 67-profile bank under `tests/data/sound_profiles/bank/`.

- Extended [src/atari_music/pokey_hw.py](src/atari_music/pokey_hw.py) with exact POKEY clock/divider/polynomial constants (`POKEY_DIV_64KHZ = 28`, `POKEY_DIV_15KHZ = 114`, `AUDF_179MHZ_8BIT_OFFSET = 4`, `AUDF_179MHZ_16BIT_OFFSET = 7`, `POLY4_PERIOD = 15`, `POLY5_PERIOD = 31`, `POLY9_PERIOD = 511`, `POLY17_PERIOD = 131071`), `base_clock_divisor()`, `channel_period_cpu_cycles()`, `generate_lfsr4_sequence()`, `generate_lfsr5_sequence(active_gate_polarity=...)`, `generate_lfsr9_sequence()`, `generate_lfsr17_sequence()`, `audf_for_poly4_8bit()`, and `audf16_for_poly5()`.
- Rewrote the synthesis core in [src/atari_music/pokey_synth.py](src/atari_music/pokey_synth.py) around CPU-cycle-accurate LFSR event simulation (`_evaluate_channel_ticks`, `_gated_sample_and_hold`) modeling `POLY4` (mod 15), XNOR-gated `POLY5` (mod 31, 62-tick subharmonic doubling & divider stalls), `POLY9`/`POLY17` noise, digital HPF XOR D-latch (`_apply_hpf_xor` for `AUDCTL $02` CH2<-CH4 and `$04` CH1<-CH3 including muted control channels), 16-bit `CH1+CH2` & `CH3+CH4` (`$08`/`$28`), `VOLUME_ONLY` DC steps, and analytical box integration (`_box_integrate_events`), maintaining ~42x realtime speed (`0.2375s` for 500 frames / 10s @ 44.1 kHz vs `0.1737s` baseline).
- Added opt-in static `CORE_V1` SSOT profile rendering via `InstrumentRenderError`, `compile_core_v1_profiles_to_frames()`, `render_core_v1_profiles_samples()`, `render_core_v1_profiles_to_wav()`, and optional `profile_assignments`/`catalog`/`target` arguments on `render_pokey_samples()` and `render_pokey_to_wav()` (lazy-importing `atari_music.instruments` inside functions to avoid circular imports), rejecting incompatible/deferred profiles without silent downgrade.
- Added [tests/test_pokey_hardware_synthesis.py](tests/test_pokey_hardware_synthesis.py) (15 tests, including MADS + ASAP 8.0.0 parity tests reaching `0.0 Hz` f0 delta and `0.9493–0.9979` spectral correlation) and [tests/test_core_v1_profile_synth.py](tests/test_core_v1_profile_synth.py) (4 tests), all marked `@pytest.mark.core` + `@pytest.mark.audio`.
- Verified `python scripts/verify_test_classification.py` (`2405` cases / `578` core / `576` core offline / `375` audio, `PASS`), `python -m pytest -m "core and not live"` (`576 passed, 1829 deselected`), `python -m pytest -m "audio and not live"` (`375 passed, 2030 deselected`), and targeted POKEY/audio suites (`198 passed`).

## [2026-11-16] - Enforce HardwareConstraints Divider Mode and AUDCTL Join Consistency

- Added cross-validation in `HardwareConstraints._validate_constraints` inside [src/atari_music/instruments/models.py](src/atari_music/instruments/models.py) enforcing exact `AUDCTL` join bit parity (`_DIVIDER_JOIN_MASK`: `"8bit" -> 0x00`, `"16bit_ch12" -> AUDCTL_JOIN_1_2_16BIT (0x10)`, `"16bit_ch34" -> AUDCTL_JOIN_3_4_16BIT (0x08)`) without altering non-join `AUDCTL` bits.
- Added regression cases in [tests/test_instrument_catalog.py](tests/test_instrument_catalog.py) covering valid `16bit_ch12` (`0x50`), valid `16bit_ch34` (`0x28`), valid `8bit` clocked modes (`0x41`), contradictory `divider_mode`/`required_audctl_bits` combinations, and missing join masks.
- Verified with `python -m pytest tests/test_instrument_catalog.py tests/test_pokey_runtime.py tests/test_architecture_boundaries.py` (`24 passed`), `python scripts/verify_test_classification.py` (`2386` cases, `PASS`), and `python -m pytest -m "core and not live"` (`557 passed, 1829 deselected`).

## [2026-11-16] - Stage A: SSOT Instrument Catalog & Stateless POKEYRuntime Foundation

Implemented Stage A on branch `feature/instrument-system-stage-a` without touching existing audio synthesis, IR compilation, MADS exporter, `player.asm`, Composer v4, AI modules, CLI, or the 67-profile bank under `tests/data/sound_profiles/bank/`.

- Added Pydantic v2 models (`EnvelopeSpec`, `HardwareConstraints`, `TransientMacroStep`, `TransientMacroSpec`, `PitchEnvelopeSpec`, `VibratoSpec`, `InstrumentProvenance`, `InstrumentBehavior` / `PerformanceSpec`, `InstrumentProfile`, `InstrumentCatalogDocument`) with `extra="forbid"`, `frozen=True`, separated profile vs behavior validation, advisory `preferred_clock_hz` vs hard `AUDCTL` masks, and deterministic JSON serialization in [src/atari_music/instruments/models.py](src/atari_music/instruments/models.py).
- Added versioned JSON loader and integrity/provenance validator (`InstrumentCatalog`, `CatalogError`, `load_instrument_catalog`, `validate_instrument_catalog` against `atari-music/instrument-catalog/1`) in [src/atari_music/instruments/catalog.py](src/atari_music/instruments/catalog.py), plus the public zero-side-effect facade in [src/atari_music/instruments/__init__.py](src/atari_music/instruments/__init__.py).
- Added curated SSOT catalog [data/instruments/catalog.json](data/instruments/catalog.json) with 16 profiles (`lead`, `bass`, `pad`/`harmony`, `percussion`), 10 behavior definitions, and verified bank provenance IDs/SHA-256 fingerprints (`pokey_ref_25f94201`, `pokey_ref_9daa0429`, `pokey_ref_2b83db43`).
- Added stateless hardware/backend resolver `POKEYRuntime` (`TargetCapability`, `InvalidTargetCapabilityError`, `ChannelAssignmentRequest`, `RuntimeDiagnostic`, `RuntimeResolutionReport`, `check_profile`, `resolve`) with strict backend validation (`wav`, `xex_v1`, planned `xex_v2` / `asap`), `AUDCTL` conflict rules (`$01` 15 kHz, `$40`/`$20` 1.79 MHz, `$10`/`$50` 16-bit CH1+2, deferred `$08` / HPF `$02`/`$04`), no hidden channel rerouting, and strict `effective_audctl = 0` on blocking errors in [src/atari_music/instruments/runtime.py](src/atari_music/instruments/runtime.py).
- Added CORE test suites [tests/test_instrument_catalog.py](tests/test_instrument_catalog.py) and [tests/test_pokey_runtime.py](tests/test_pokey_runtime.py), registered `instruments/*` in `CORE_MODULES`, and added regression guards for CLI `hidden=True` enforcement and `instruments` subpackage relative imports in [tests/test_architecture_boundaries.py](tests/test_architecture_boundaries.py).
- Verified `pytest tests/test_instrument_catalog.py tests/test_pokey_runtime.py tests/test_architecture_boundaries.py` (`24 passed`), `scripts/verify_test_classification.py` (`2386` cases, `559` core / `557` offline, `PASS`), and `python -m pytest -m "core and not live"` (`557 passed, 1829 deselected`).

## [2026-11-16] - Harden Architecture Boundary Checks (Relative Imports & CLI Exemptions)

Closed the two AST boundary check gaps identified in post-implementation review on branch `refactor/core-boundaries-test-markers` without modifying production code, test markers, or audio modules.

- Updated `_imported_atari_music_targets()` in [tests/test_architecture_boundaries.py](tests/test_architecture_boundaries.py) to resolve relative imports (`level >= 1`, including `from .stage15 import ...`, `from ..composer_v2 import ...`, `from . import module`, and `from .. import module`) relative to each module's `atari_music` package hierarchy.
- Replaced the inverted `public_core_cli_fns` allowlist in [tests/test_architecture_boundaries.py](tests/test_architecture_boundaries.py) with `_is_exempt_cli_command()` requiring an explicit `@cli.command(...)` decorator and membership in `HIDDEN_LEGACY_CLI_COMMANDS` (with AST `hidden=True`) or `EXPERIMENTAL_STAGE_CLI_COMMANDS`, so any new unlisted helper or CLI command in [src/atari_music/cli.py](src/atari_music/cli.py) is strictly audited as `CORE`.
- Extracted `find_core_import_violations()` and added 5 regression tests in [tests/test_architecture_boundaries.py](tests/test_architecture_boundaries.py) (`test_relative_import_legacy_is_detected`, `test_relative_import_experimental_is_detected`, `test_relative_from_dot_import_module_is_detected`, `test_relative_import_core_produces_no_false_positive`, `test_cli_unlisted_new_function_is_not_exempted`), growing `CORE` offline from `537` to `542` cases (`2371` total collected pytest cases).

## [2026-11-16] - Core Dependency Boundary Stabilization & Pytest Profile Organization

Cleaned up `CORE -> LEGACY/EXPERIMENTAL` import leaks, removed shadowed Stage 12A CLI duplicates, and partitioned the entire test suite with mutually exclusive `pytest` category markers (`core`, `experimental`, `legacy`) plus the `audio` release-gate subset on branch `refactor/core-boundaries-test-markers`.

- Extracted `deduplicate_pokey_patterns` from [src/atari_music/composer_v2.py](src/atari_music/composer_v2.py) into [src/atari_music/ir_optimizer.py](src/atari_music/ir_optimizer.py), keeping a compatibility re-export in `composer_v2.py` and updating [src/atari_music/composer_v4.py](src/atari_music/composer_v4.py).
- Moved `SCALES` and `KEY_BASE_MIDI` from [src/atari_music/generator.py](src/atari_music/generator.py) into [src/atari_music/constants.py](src/atari_music/constants.py), retaining compatibility re-exports in `generator.py` and switching [src/atari_music/composer_v4.py](src/atari_music/composer_v4.py).
- Extracted production player binary budget enforcement and MADS measurement (`PLAYER_SIZE_LIMIT_BYTES`, `PLAYER_SIZE_LIMIT_SCOPE`, `PLAYER_SIZE_BUDGETS`, `PLAYER_ZERO_PAGE_BYTES`, `DEFAULT_PLAYER_ASM`, `DEFAULT_MADS`, `PlayerSizeError`, `player_size_limit_ok`, `check_player_size`, `measure_player_size`) from [src/atari_music/stage15.py](src/atari_music/stage15.py) into [src/atari_music/player_budget.py](src/atari_music/player_budget.py), retaining compatibility re-exports in `stage15.py` and switching [src/atari_music/ai/client.py](src/atari_music/ai/client.py), [src/atari_music/xex_layout.py](src/atari_music/xex_layout.py) docstring, and `TestPlayerSizeLimit` monkeypatching in [tests/test_xex_layout.py](tests/test_xex_layout.py).
- Cleaned [src/atari_music/cli.py](src/atari_music/cli.py): removed unused top-level `extract_raw_dump` import, moved `build_full_dataset` import lazily inside `extract_cmd`, and removed shadowed first definitions of `run_stage12a_cmd` and `prepare_stage12a_listening_cmd` while preserving the active definitions (including `--seed`).
- Configured `--strict-markers` and `core` / `experimental` / `legacy` / `audio` / `live` markers in [pyproject.toml](pyproject.toml), annotated all 48 existing test files (splitting mixed [tests/test_pokey_music.py](tests/test_pokey_music.py), [tests/test_sound_profiles.py](tests/test_sound_profiles.py), and [tests/test_stage15.py](tests/test_stage15.py) cleanly per test without `core`/`experimental`/`legacy` overlaps), and added [scripts/verify_test_classification.py](scripts/verify_test_classification.py), [tests/test_player_budget.py](tests/test_player_budget.py), [tests/test_ir_optimizer.py](tests/test_ir_optimizer.py), and [tests/test_architecture_boundaries.py](tests/test_architecture_boundaries.py).
- Verified full suite (`2364 passed, 2 deselected`), `core and not live` (`537 passed`), `audio` (`356 passed`), `legacy` (`25 passed`), `experimental` (`1802 passed`), classification completeness (`2366/2366` cases across `2273` definitions via `pytest --collect-only`), MADS/`py65` (`scripts/verify_stage11_runtime.py`), and ASAP (`asapscan.exe` + `asapconv.EXE` present).

## [2026-11-15] - Phase 1: Critical Audio Engine Fixes (ADSR & Channel Muting)

Fixed the two critical production correctness bugs identified in `AUDIT_AUDIO_ENGINE.md` without modifying IR/SAP formats, generator APIs, or adding post-Phase-1 synthesis features.

- Fixed ADSR envelope state machine in [player.asm](player.asm) and mirrored byte-identically into [src/atari_music/asm/player.asm](src/atari_music/asm/player.asm): added `scale_env_step` (zero-RAM loop division using existing `zp_tmp_ptr` at `$88..$89`), replaced two-step Attack `(peak >> 1) | 1` with multi-step linear Attack `max(1, floor(env_frame * peak / att))`, added multi-step linear Decay (`peak - floor(env_frame * (peak - sus_lvl) / dec)` with immediate `dec=0` fall-through), clamped Sustain via `ch_sus_lvl = min(ch_sus, ch_peak_vol)` in `@setup_envelope`, and fixed Release units mismatch by checking remaining VBI frames `(ch_dur - 1) * tempo_divider + tick_counter <= ch_rel` with overflow guard. Strictly MOS 6502 opcodes only; Zero Page stays `10` bytes (`$80..$89`); assembled player footprint is `1144` bytes (`1067` code + `77` state, leaving `904` bytes headroom below the `2048`-byte limit).
- Fixed POKEY channel muting in `write_pokey_registers` across [player.asm](player.asm) and [src/atari_music/asm/player.asm](src/atari_music/asm/player.asm): loaded `#0` before testing `ch_mute_mask` in all 8-bit (`AUDC1..4`) and 16-bit joined bass (`AUDCTL & $10`, `ch_mute_mask+0` or `+1` -> `AUDC2`) mute branches so muted channels always write exact `$00` instead of leaking `$01` distortion noise, while preserving internal channel timing/state for clean unmute recovery.
- Updated Python reference envelope parity in `player_envelope_volumes` inside [src/atari_music/pokey_hw.py](src/atari_music/pokey_hw.py) and updated `PLAYER_ASSEMBLED_BYTES_RECORDED = 1144` in [src/atari_music/stage15.py](src/atari_music/stage15.py). Isolated Stage 20's historical 4-parameter reduced contour model inside `_stage20_reduced_contour` in [src/atari_music/stage20.py](src/atari_music/stage20.py).
- Added 26 MADS + `py65` CPU emulation regression tests in [tests/test_phase1_audio_fixes.py](tests/test_phase1_audio_fixes.py) (all ADSR transitions, edge cases, `peak < sustain` clamp, 8-bit/16-bit muting with arbitrary mask bytes, mid-note & cross-note unmute recovery) and updated Phase-1 baselines across [tests/test_pokey_semantics.py](tests/test_pokey_semantics.py), [tests/test_stage22.py](tests/test_stage22.py), [tests/test_xex_layout.py](tests/test_xex_layout.py), [tests/test_sound_profile_library.py](tests/test_sound_profile_library.py), and [tests/test_stage11.py](tests/test_stage11.py).
- Refreshed gitignored downstream experimental packages (`reports/stage15/`, `reports/stage9d/`, `reports/stage10a/`, `reports/stage10b/`, `reports/stage11/`, `experiments/experiment26..28/`, `examples/sound_profile_listening/`, `examples/sound_profile_rebinding_10a/`, `examples/sound_profile_volume_contour_10b/`) via [scratch/phase1_verification/refresh_packages.py](scratch/phase1_verification/refresh_packages.py) while preserving all human listening CSV ratings intact.
- Verified real MADS `SAP TYPE B` + ASAP 8.0.0 (`asapscan` + `asapconv`) before/after binaries and single shared-gain comparison WAVs in `scratch/phase1_verification/` (`adsr_before/after`, `mute_solo_ch1_before/after` dropping muted Ch1 from `-37.53 dBFS` to `0.0` / `-120.0 dBFS`, `mute_before_buggy_01` vs `mute_after_fixed_00`, `mute_16bit_bass`, `mute_unmute_recovery`, documented in [PHASE_1_REPORT.md](PHASE_1_REPORT.md) and `scratch/phase1_verification/phase1_metrics.json`).

## [2026-10-09] - XEX Memory Layout Validation (segment ranges, not file size)

Removing the whole-file 2048-byte rule (the entry below) left the build with **no check on where a binary loads**. It still assembled, and it still reported success, but nothing noticed that `--music-address 0x6000` with `--player-address 0x6000` emits two segments over the same bytes, or that `--player-address 0xC000` puts the player inside the OS ROM. This entry closes that gap by validating the **address ranges** the loader will act on, and re-states that the file's size is not a criterion. Nothing was added to `player.asm`, and no XEX size limit was restored.

- Added [src/atari_music/xex_layout.py](src/atari_music/xex_layout.py): a deterministic XEX container parser (`parse_xex`) and the layout validator (`validate_xex_layout` / `validate_xex_file`). The walk follows each segment's declared inclusive range rather than scanning for `$FF $FF`, so a payload containing the marker cannot be mistaken for a header; it refuses an empty file, a missing leading marker, a truncated header or payload, a range whose end precedes its start (a 16-bit wrap), and a SpartaDOS X block header where a DOS segment was expected. A repeated `$FF $FF` before later segments is accepted as well as the bare-header spelling MADS emits.
- Encoded the memory policy as constants with their evidence in the same module: `USER_RAM_START = $0400`, `USER_RAM_END = $BFFF`, `LOADER_VECTOR_RANGES = ($02E0-$02E1, $02E2-$02E3)`, `SDX_BLOCK_STARTS`, and `USER_RAM_POLICY`. The lower bound is the platform's own layout (`atari8bit/system/memory-map/base-map.md`: zero page, hardware stack, DOS control block) plus the vectors and shadows this project's binary itself uses; the upper bound is `AGENTS.md` §3.1 ("All user code, graphics, data, and tables MUST end at or below `$BFFF`"). `$A000-$BFFF` is the BASIC ROM window and is **deliberately permitted**, because the project relocates there (`scripts/verify_stage11_runtime.py`) and no rule forbids it.
- Validated overlap between **all** segments, not just player-vs-song-data: the loader writes segments in file order, so the later one silently destroys the earlier one. This is the failure `AGENTS.md` §3.3 describes ("`org` directives … must be kept in strictly ascending memory order … to prevent XEX segment overwrites during boot loading"); an overwrite *is* an overlap, so overlap is what is checked, and a descending but disjoint layout is accepted rather than rejected for looking unusual.
- Wired it into the build in [src/atari_music/ai/client.py](src/atari_music/ai/client.py) as `_validate_built_xex`, called after MADS succeeds and before the path is returned. It parses the emitted container, then runs the unchanged player-size rule through `stage15.measure_player_size` + `stage15.check_player_size`. A failure deletes the binary that was just written, so a build that cannot be loaded leaves no artefact that looks runnable; the generated `.asm` is kept for debugging.
- Reported it cleanly in [src/atari_music/cli.py](src/atari_music/cli.py): `atari-music build-xex` catches `XexLayoutError` and re-raises it as a `click.ClickException`, matching the existing `InstrumentSelectionError` convention, so the user sees the range and the reason instead of a traceback.
- Added [tests/test_xex_layout.py](tests/test_xex_layout.py) (57 tests): the container walk (marker once / repeated, inclusive end, payload containing `$FF $FF`, exact consumption of a real build), the region policy (permitted, forbidden, straddling, the BASIC window, the exempt RUN vector, an unusual-but-legal `$0500`), overlap (identical, partial, swallowed, third-segment, adjacent-is-fine, descending-is-fine), the file-size non-criterion (a valid 4 KB and a valid 32 KB container are accepted), the real build path (accepted and refused layouts, with the binary's absence asserted), the player-size boundary through the build's own check (2048 refused, 2047 accepted), and the CLI reporting. Documented in [docs/xex_memory_layout.md](docs/xex_memory_layout.md).
- Fixed three test doubles that were passing a **truncated** container to the build — `tests/test_cli.py` (twice), `tests/test_instrument_selection_cli.py` and `tests/test_sound_profiles.py` wrote `b"\xff\xff\x00\x40\x10\x40"`, a header declaring 17 payload bytes with none following. They now emit a well-formed container from the new `conftest.fake_xex_bytes` helper and accept the real `subprocess.run` signature, because the build also measures the player with it. This is a fidelity fix to the stubs, not a weakening of the tests they support.
- **Deliberately unchanged:** the strict player-size rule (`< 2048`), the absence of any ceiling on the complete XEX file, C1 modulation, instrument selection, the song format, POKEY register behaviour, and the separate POKEY IR / song-data budgets. `player.asm` and `src/atari_music/asm/player.asm` are untouched.

## [2026-10-09] - The 2048-Byte Limit Now Bounds the Player, Not the XEX File

The 2048-byte limit was introduced on 2026-09-28 as a **whole-file** rule ("reducing XEX code size to stay strictly within the 2048-byte limit across all AI composition artifacts"). It was always a proxy for the player: the file was only ever close to 2048 because the player is roughly half of it, and the song data of the tightest example left 16 bytes of headroom. The C1 per-channel modulation (`docs/c1_player_extension_design.md`, Appendix B) grew the assembled player 886 → 1016 bytes, which pushed `dungeon_dark` to 2065, `funny_prl` to 2124 and `action_fast` to 2167 bytes and broke `tests/test_ai_composition.py::test_end_to_end_example_artifacts_compilation` — a **valid** executable rejected for a reason that had nothing to do with the hardware. The proxy was removed and replaced by the rule it was standing in for. No ceiling was put on the file in its place, because no byte budget on the file was ever justified by the Atari memory map.

- Made the player-size limit explicit, exclusive and single-sourced in [src/atari_music/stage15.py](src/atari_music/stage15.py): `PLAYER_SIZE_LIMIT_BYTES = 2048`, `PLAYER_SIZE_LIMIT_SCOPE` (what the limit does and does not bound), `PlayerSizeError`, `player_size_limit_ok()` (the one `<`, not `<=`) and `check_player_size()`. `PLAYER_SIZE_BUDGETS["current_envelope_2KB"]` is now defined *from* `PLAYER_SIZE_LIMIT_BYTES` so the number cannot drift between the policy and the Stage 15 report; the measurement convention is unchanged (`measure_player_size`, MADS on an `org $6000` wrapper, `-b:$6000 -o:...bin`, file size = code + state).
- Added the policy verdict to the Stage 15 analysis in [src/atari_music/stage15.py](src/atari_music/stage15.py): `player_size_analysis` now publishes `limit_bytes`, `limit_is_exclusive`, `limit_scope`, `within_limit` and a `limit_note`, `summary.json`'s `player` block carries `size_limit_bytes` / `size_limit_is_exclusive` / `size_limit_scope` / `within_size_limit`, and section 11 of the generated report states the limit in prose before its table. Regenerated [reports/stage15/](reports/stage15/) and [docs/stage15_performance_style.md](docs/stage15_performance_style.md) from unchanged inputs; the regenerated bundle is byte-identical to the committed one apart from the added policy fields.
- Removed the whole-file ceiling from the tests that carried it, keeping every other assertion: `assert len(data) <= 2048` in [tests/test_ai_composition.py](tests/test_ai_composition.py) (replaced by the DOS header check, a first-segment `start <= end` check, and a guard that at least one example still exceeds 2048 bytes and is accepted); `assert xex_p.stat().st_size <= 2048` in [tests/test_pokey_music.py](tests/test_pokey_music.py) (replaced by a header check plus one real `stage15.check_player_size` on the assembled player); `assert 1000 <= size <= 2048` in [tests/test_pokey_music.py](tests/test_pokey_music.py) and `assert 500 <= len(xex_bytes) <= 2048` in [tests/test_stage13_llm_integration.py](tests/test_stage13_llm_integration.py) (lower sanity bounds kept, upper bounds dropped).
- Added the enforcement tests in [tests/test_stage15.py](tests/test_stage15.py): the limit is exclusive (`player_size_limit_ok(2047) is True`, `(2048) is False`, `(2049) is False`), `check_player_size(2047)` returns and `check_player_size(2048)` raises `PlayerSizeError` naming both numbers, the scope statement names the player and the XEX, the analysis publishes a matching `within_limit`, and the live measurement passes `check_player_size`.
- Recorded the policy in [docs/c1_player_extension_design.md](docs/c1_player_extension_design.md) §B.5 (the blocker is resolved by the policy correction, not by shrinking the feature) and in [SKILL.md](SKILL.md).
- **Deliberately unchanged:** the independent POKEY-IR / song-data budget (`composer_v2/v3/v4.max_size = 2048`, `generator.py`, `control_generator.py`, `batch_experiment.py`, `ai/client.py`'s `under_budget`, and the tests that assert `memory_size_bytes <= 2048`). That is a *different* 2048: it bounds the exported song data, its purpose was never to bound the file, and it is far from binding (max 505 B). It was left alone.
- **Not changed:** the C1 algorithm, timing and register sequence; the Lead Library schema and instrument definitions; `pure_sustain`, `pure_pluck`, `buzz_steady`; the player source (no bytes were saved anywhere).

## [2026-10-06] - Volume Contour Transfer Experiment Prepared (Stage 10B)

Stage 9E named the first capability the composer lacks: the archaeology **measures** how loudness moved inside a sound (`gesture.volume.runs` — absolute AUDC levels, one sample per VBL frame; 58 of 67 profiles carry one, every one published with `playable.gesture.volume.enabled: false`) and the player discards it. Stage 10A then showed that reassigning profiles changes nothing on its own. This stage asks the narrow question that leaves: **can the measured contour be transferred into the existing IR and frame generation, and does the transfer change the sound in the direction the measurement describes?** It implements that transfer — minimally — and prepares the listening test that judges it.

**One code path, and a per-frame volume that already existed.** `AUDC = (distortion & 0xE0) | volume` was already written for every frame by `_render_note_to_frames`, so the contour needs one multiplicative step there and nothing else: no second renderer, no separate audio path, and the WAV and the XEX keep coming from the same representation. `IRInstrument.volume_contour` defaults to `None`, which is what keeps every artefact that predates the feature identical.

**The mapping, defined before anything was rendered.** `effective[i] = floor(volumes[i] * contour[i % span] / max(contour) + 0.5)`, clamped to 0..15. Three properties follow and all three are load-bearing: **velocity stays sovereign** (the factor is ≤ 1, so the contour attenuates and can never boost or clip); **a static contour is an exact no-op** (checked through the real path, not in the abstract); **the source's absolute loudness cannot leak**, because the reference level is the contour's own peak. The span restarts at every note onset, tiles over longer notes and truncates over shorter ones; `floor(x + 0.5)` rather than `round()`, so no mapping depends on the parity of a half-integer.

**The contour's zeros are the whole argument.** Level 0 in a measurement means *nothing sounded* — timing, not loudness. Transferring it would import another song's gating into a composition that owns its own notes, so a contour that reaches 0 is **not transferable**, and every channel where one was withheld is named in the report (3 channels in 2 of the 6 songs) rather than approximated. Measured consequence, reported as scope rather than hidden: the bank's most mobile contours — up to 119 level changes in 147 frames — are exactly the ones containing silence, and all of them change faster than the 50 Hz frame grid can carry, so this stage tests the swell and step class and leaves the tremolo class untouched.

**Proof by perturbation, not by summary.** For each of the 8 tested profiles (7 VOICE + 1 PAIR, chosen by a stated rule: transferable, at least 2 distinct levels, rate ≤ 12.5 Hz, span 8..300 frames, renderable) three renders of one composition and one binding are compared: no contour, the measured contour, and the same contour **reversed**. The proof is that exactly one frame column differs and it is the AUDC column of the channel that sounds (AUDC2 for the 16-bit pair — the coupled-channel case needs no special case, and the test says so), that the distortion nibble never moved, that the low nibble equals the mapping's own arithmetic frame for frame with zero mismatching frames, and that the rendered audio's frame-wise RMS follows the volume the frames carry (median r ≈ 0.97).

**The negative proof is byte-exact.** With the feature switched off, all **18 renders** the Stage 10A package published (6 songs × default/old/new) are reproduced **byte for byte**, so no golden file was regenerated to accommodate a change. The pairing rule (`volume_contour=False` ≡ no argument) and the gating refusal (a withheld channel's frames are identical between B and C) are both pinned by tests.

**The limit of this stage, stated up front: the XEX cannot carry it.** The MADS exporter publishes a note table and `player.asm` builds the per-frame envelope at run time, so `export_mads_asm` **refuses** a song that carries a contour (`VOLUME_CONTOUR_NOT_EXPRESSIBLE_IN_XEX`) instead of exporting something that would play a different sound from the one that was listened to. Nothing existing breaks, because no IR carries a contour unless a caller asks for one.

**Verdict: INCONCLUSIVE.** The mechanical question is answered — the transfer reaches the register stream and the audio, it is the sole cause of the difference between variant B and variant C, and it is inert when not asked for. Whether a listener hears it, and whether it sounds better, is not answered here; the package is prepared for exactly that, and this stage declares no winner.

- [src/atari_music/ir.py](src/atari_music/ir.py): `apply_volume_contour` (the mapping and its three properties), `FRAME_COLUMN_NAMES` / `audc_column` / `audf_column` (the interleaved row layout, made explicit), `FRAME_RATE_HZ`, `IRInstrument.volume_contour`, and the call in `_render_note_to_frames`.
- [src/atari_music/sound_profiles/bank.py](src/atari_music/sound_profiles/bank.py): `SoundProfile.volume_gesture`, `.volume_contour_declared` and `.volume_contour` (RLE expanded verbatim; a malformed series yields `None` rather than a guess).
- [src/atari_music/sound_profiles/binding.py](src/atari_music/sound_profiles/binding.py): `apply_profile_binding(..., volume_contour=...)` — `False` (default), `True`, or a set of binding keys, which is what lets one channel's gating contour be withheld while its neighbours take theirs; `describe_binding` mirrors it and the plan records the source.
- [src/atari_music/mads_exporter.py](src/atari_music/mads_exporter.py): `VolumeContourNotExpressibleError` and the refusal, plus `find_volume_contour_instruments`.
- [src/atari_music/stage10b.py](src/atari_music/stage10b.py): the experiment — `transferability`/`contour_record`/`silence_shape` (why a contour may or may not be transferred), the eligibility rule and the tested-set ranking, the held-note stimulus, the three variants, level/volume/attenuation/spectral metrics, `perturbation_proof`, `static_contour_is_a_no_op`, `regression_proof`, the blinded programme, the interface, the report and the answer reader. Config: `volume_contour=True`, `mads_exporter` refuses a contoured song for XEX export.
- `prepare-volume-contour-10b` and `analyze-volume-contour-10b` CLI commands (deterministic; read-only with respect to the bank, the songs, the Stage 10A package and the Stage 9C package — all digested before and after).
- [docs/stage10b_volume_contour_experiment.md](docs/stage10b_volume_contour_experiment.md): fourteen sections with Observed / Inference / Experimental choice kept apart, [reports/stage10b/](reports/stage10b/) with `profiles.json`, `subjects.json`, `transfer.json`, `perturbation.json`, `regression.json` and `verification.json`, and the blinded package (96 files, 47.5 MB, reproducible from the CLI) in `examples/sound_profile_volume_contour_10b/`.
- [tests/test_stage10b.py](tests/test_stage10b.py) (72 tests): the mapping's arithmetic (attenuation only, static no-op, tiling/truncation, the `max(contour) == 0` guard, `floor(x+0.5)` not banker's rounding, the reference level), eligibility and refusal reasons, the tested set's bounds and reproducibility, every perturbation proof, the coupled-pair AUDC2 case, the 18-render byte-exact regression, the withheld channel, the exporter refusal, reproducibility, the package (mono/16-bit, B≠C, 14 B-vs-C + 4 controls, one B-vs-C per subject, sides equal the variants they claim, blindness, withheld channels named in the README), the report's fourteen sections and its verdict wording, the answer reader, and the immutability of everything read.
- Fixed a real defect found while implementing: `stage10a.frame_differences` named the frame columns as if the row were `AUDF1..4, AUDC1..4, AUDCTL`. The row is **interleaved** (`AUDF1, AUDC1, AUDF2, AUDC2, …`), so every name after the first was wrong and the published Stage 10A tables mislabelled which register had changed (e.g. `funky.json` default-vs-old reported `AUDF2` where the truth is `AUDC1`). The names now come from one definition (`ir.FRAME_COLUMN_NAMES`), `docs/stage10a_rebinding_experiment.md` and `reports/stage10a/machine_comparison.json` were regenerated from unchanged inputs (audio proven byte-identical, manifest identical apart from its timestamp and three path spellings), and `tests/test_stage10a.py` gained a test that derives the layout from a real render.

**STOP.** The package is prepared and nothing else is done: no profile edited, renamed or removed, no schema, DSL, composition, binding, generator, player or historical result changed, no authoring integration, no pitch trajectory, no bank or binding selection, and no winner declared. The verdict stays `INCONCLUSIVE` until the listening evidence exists.

Composer suite: **646 passed, 2 deselected** (568 before), 3–7 min; `tests/test_stage10b.py` builds the whole experiment once and finishes in ~3 min.

## [2026-10-06] - Evidence-Based Profile Rebinding Experiment Prepared (Stage 10A)

Stage 9C's whole-song comparison put the profile-bound render at **0 wins to the composer's own instruments' 5** (one tie) — and Stage 9E then established that those bindings were drawn from **generator-family pools**, not from anything the listener said. So the 5–0 does not yet separate "the mechanism is worse for whole songs" from "the wrong profile was put on each role". This stage prepares the experiment that tells them apart, and implements nothing: no profile, fingerprint, schema, composition, binding, player, renderer, DSL or Composer source was modified.

**The only variable is the assignment.** Three renders per song — the composer's own instruments, the old binding, and a new binding chosen from the listening evidence — over the six Part C songs recovered from the Stage 9C manifest rather than from filenames. The manifest is authoritative: the per-song binding file is re-read and must agree with it profile-by-profile, and a binding edited since the experiment is refused, because it would silently change what "old" means.

**Compatibility is measured, not assumed.** Every candidate profile is put through `apply_profile_binding`; a refusal removes it from the pool. That is why the new assignment obeys the channel/pair/AUDCTL rules without a separate model of them — the layer that enforces them is the layer that was asked, and the refusals are recorded as data.

**The decision rule, and why it is not a preference.** Stage 9D measured the listener against themselves on byte-identical sounds (usefulness ICC(1,1) 0.76, distinctiveness 0.73, Atari character 0.92), so a replacement is adopted only when the listener rated it **no lower on usefulness, distinctiveness and Atari character** and higher on at least one: by 2 points on a single scale, or by 1 point on two scales together. A single one-point gain is not evidence — including when it is a *distinctiveness* gain, because across the whole library the listener's distinctiveness and Atari-character ratings **oppose each other** (Spearman **−0.57**, n=60) while usefulness tracks character (+0.57). Buying distinctiveness with character would move against the dimension the questionnaire asks about, so several channels whose old profile is the listener's *least* distinctive ("typical atari lead tone", distinctiveness 1) are deliberately **kept**: those profiles are simultaneously the most Atari-like in the library (character 5). The first draft of the rule did trade the two, and the dry run showed it choosing the library's only Atari-character-2 sound for five songs' percussion; the rule was replaced before anything was built. Adjustments like that are why the report's Observed / Inference / Experimental-choice sections are kept apart.

**Result of the preparation.** 10 of 21 channels changed (11 roles) across 5 songs; `dziki2.json` is left entirely unchanged — its channel 4 carries a bell, a counter *and* a drum, so one profile must serve pitched and percussive roles at once, and no assignment can be right for all three. The six songs drew on only **11 distinct sounds for 24 bound roles**, which is the measured shape of the problem.

**The comparison is anchored to the audio the listener already judged.** The default and old sides are compared **byte for byte** with the Stage 9C package's own stimuli — identical for all six songs — and the shared gain matches the gain Stage 9C recorded to four decimals. The build stops rather than ships if either diverges. Level and time are untouched: one gain per song derived from the default side and applied to all three versions, the same 15 s window, no compression, no EQ, no per-side level matching; clipped-sample counts are recorded per version rather than hidden.

**What the package asks, and what it hides.** 18 blinded pairs (per song: default-vs-new, old-vs-new, and a default-vs-old *control*), orientations randomized from a recorded seed, three choice questions plus a 1–5 difference scale and a comment. The control is there because Stage 9D measured a session effect (Atari character and confidence correlating −0.37 and −0.47 with presentation position): without it a change in the default-vs-new result could not be separated from the session. The interface names no version, profile, generator, scope or song, and captions all three kinds identically; the mapping lives only in the package's manifest, which the README tells the listener not to open.

- [src/atari_music/stage10a.py](src/atari_music/stage10a.py): the experiment — song recovery and manifest agreement, the evidence table, role classes and channel groups, the measured candidate pools, the decision rule, three renders per song with a shared gain, the machine comparison (SHA-256, peak/RMS, centroid/bandwidth/flatness, spectral distance, register-frame and per-column differences, AUDCTL), the blinded programme, the interface, and the report.
- `prepare-rebinding-10a` CLI (deterministic; read-only with respect to the bank, the songs, the old bindings, the Stage 9C package and the Stage 9D analysis — all digested before and after, and compared).
- [docs/stage10a_rebinding_experiment.md](docs/stage10a_rebinding_experiment.md): ten sections with Observed / Inference / Experimental choice kept apart, [reports/stage10a/](reports/stage10a/) with `songs.json`, `rebinding.json`, `machine_comparison.json` and `verification.json`, and the blinded package in `examples/sound_profile_rebinding_10a/`.
- [tests/test_stage10a.py](tests/test_stage10a.py) (52 tests): exact song identification (and refusal of an edited binding), one profile per channel, every new binding applies, no rating regressed, no scope changed, kept channels have no eligible replacement, the rule's unit behaviour including the character floor and the blocked trade, deterministic selection and orientation, no clipping, byte-identical default/old sides, the same shared gain as Stage 9C, reproducible renders, no note changed, the pairs are the versions they claim, the interface gives nothing away, and nothing the stage reads was modified.
- [docs/profile_integration.md](docs/profile_integration.md): §13.3 added — the experiment, and why its comparison is anchored to Stage 9C's own audio.
- [README.md](README.md): Stage 10A section, test count.

**STOP.** The package is prepared and nothing else is done: no gesture rendering, no player or IR change, no library selection, no profile renamed or removed, and the Stage 9C package, its answers and its results are untouched. The next decision belongs to the listening: a win for the new assignment means the 5–0 was at least partly a selection problem; a loss means selection alone is not enough and the minimal renderer capability experiment Stage 9E scoped comes next.

Composer suite: **568 passed, 2 deselected** (516 before), 2–5 min; `tests/test_stage10a.py` builds the whole experiment once and finishes in ~90 s.

## [2026-10-05] - Perceptual / Renderer Gap Diagnosed (Stage 9E)

Stage 9D said the 61 profiles sound like 37, and that binding them to six real songs lost 5-0. This stage diagnoses **why** and where, and implements nothing: no profile, fingerprint, schema, WAV, answer, player, composition or Composer source was modified.

**Method: measured, not read.** Reading the pipeline would only produce a list of what it *looks* like it uses. Instead four boundaries are measured. (1) A profile document is wrapped in a `TrackingMapping` that records every path the **real** binding touches, and the binding is then run. (2) Each `IRInstrument` field is perturbed in each profile's own bound stimulus and the register frames are compared, which measures the IR→frames boundary. (3) Each frame column is zeroed and re-rendered, which measures frames→audio. (4) Every duplicate group is walked through document → bound IR → frames → WAV, and the walk stops at the first stage whose members agree. Finally the diagnosis renders each profile itself and compares its audio **byte for byte** with the WAV the listener heard: **61 of 61 identical**, and it raises rather than continues if any file disagrees — so its claims are about exactly the pipeline that produced the experiment.

**Three findings.**

1. **The binding reads 13 of the 232 documented leaf paths a profile defines.** `_rebuild_song` writes six values onto the instrument — the generator nibble, three envelope frame counts, the sustain level and AUDCTL (plus the pair flag and two validation-only reads) — and stages 5–6 never see the document at all. Statuses across all 232 paths: 28 `USED`, 109 `UNREPRESENTABLE` (a series over time the player has no macro for), 74 `IGNORED`, 21 `PLAYER_ONLY`. The measured pitch trajectory (525 differing leaf paths), volume contour (981), modulation, generator changes inside a sound and all provenance are present and read by nothing.
2. **All 6 duplicate groups are lost at that one boundary.** Every group's documents differ (125–691 leaf paths) while the bound IR is already identical, so the frames and the WAV must be too: `representation_duplicate` for 6 of 6 groups, **30 profiles**, and 0 groups needed a renderer or quantization explanation. The `true_duplicate` and `renderer_duplicate` classes are both empty. A byte-identical WAV therefore does **not** mean a redundant profile — it is redundant *today*, for this renderer.
3. **The Part C loss is not a level artefact, and the renderer is nearly blameless.** Both sides of each pair were rendered at one shared gain (as in Stage 9C) and the profile-bound side was not louder (median RMS delta −2.39 dB); the binding replaced each instrument's generator and/or envelope, so the two sides differ in timbre and articulation and the Composer's own instruments won. The frame compiler uses every field the binding writes, except a few measured inert — `envelope.decay_frames` changes no frame for 8 of 61 profiles, and `is_16bit`, `role`, `vibrato_depth`, `vibrato_speed`, `macro`, `name` reach no frame for any.

**Order of causes.** Representation gap first (dominant), musical-interpretation gap second (the bindings were chosen by generator family, not by listening evidence), renderer gap only marginally. Six capabilities are ranked by evidence rather than opinion — volume contour (6 groups, 981 paths), pitch trajectory (6, 525), generator changes (6, 188), measured pitch base/range (6, 48), modulation (6, 18), and the envelope shape/timing, which is a **quantization** limit and cannot explain a duplicate by construction because the envelope already survives the binding. None is implemented: carrying the first two changes what the listener hears, which invalidates the current perceptual ranking and requires a new listening test.

- [src/atari_music/stage9e.py](src/atari_music/stage9e.py): the diagnosis — `TrackingMapping`/`TrackingList` field-access recording, the path-status classifier, IR perturbation, frame-column zeroing, per-group differential rendering, gesture and Part C diagnostics, the evidence-ordered capability ranking, and the verdict derived from the number of unexplained groups.
- `analyze-listening-test-9e` CLI (deterministic, read-only, refuses a package whose audio it does not reproduce byte for byte).
- [docs/stage9e_perceptual_renderer_gap.md](docs/stage9e_perceptual_renderer_gap.md): the report, sections 1–16 with Observed / Inference / Recommendation kept apart, and [reports/stage9e/](reports/stage9e/) with `pipeline_fields.json`, `duplicate_groups.json`, `profile_diffs.json`, `information_loss.json`, `part_c_diagnostics.json`, `missing_capabilities.json` and `verdict.json`.
- [tests/test_stage9e.py](tests/test_stage9e.py) (38 tests): the read-set and status classification, the perturbation boundaries (asserted separately per stimulus variant, because AUDCTL is $00 on a VOICE stimulus and genuinely changes the audio on a PAIR one), group classification and partitions, capability ordering, determinism, that a modified package WAV is *refused*, and that the analysis cannot modify the bank, the package or the answers.
- [docs/profile_integration.md](docs/profile_integration.md): §3.5 added — the measured explanation behind §3.4's two negative findings.
- [README.md](README.md): Stage 9E section, test count.

**Closing answer: DIAGNOSTICALLY_COMPLETE** — 6 duplicate groups, 6 explained, 0 unexplained. Nothing was fixed, because the fix is a research act: re-bind the six songs from the listening evidence (cheap, reversible), then carry the volume contour before the pitch trajectory, then re-run the listening test.

Composer suite: **516 passed, 2 deselected** (478 before), 1–3 min; `tests/test_stage9e.py` runs the diagnosis once and completes in ~72 s.

## [2026-10-05] - Human Listening Results Analysed (Stage 9D)

The listening was performed by a human; this stage analysed it. The result is a negative one, and it is reported rather than smoothed over. Nothing was changed: no profile, no fingerprint, no schema, no WAV, no manifest, no answer, no Composer code.

**What the data is.** Three completed spreadsheets — 61 profile ratings, 30 A/B trials, 6 song pairs — plus the Stage 9C private manifest, all hashed before use so the run is reproducible from the same bytes. The first thing the analysis had to do was verify them: 61/30/6 rows, ids set-for-set with the manifest, every rating inside 1–5, every choice inside a/b/none, no duplicates. Two gaps were found and **reported instead of filled**: `sample_026` carries a comment but no ratings, and `trial_20` has no stated preference. Each statistic states its own n.

**The four findings that matter.**

1. **The library is audibly much smaller than its profile count.** The 61 renderable profiles produce only **37 distinct audio signals**; 24 render *byte-identical* audio to another profile, in groups of 10, 6, 4, 4, 3 and 3. The profiles differ in measured pitch/volume gesture behaviour that the player cannot render, so they differ on paper and not in sound. Stage 9C recorded this faithfully (equal feature vectors are visible in its manifest) but did not report it as a property of the *library*. The defect is described in the report and used, not corrected retroactively.
2. **Profile-bound rendering lost the whole-song test.** Across the six songs the Composer's own default instruments won **5**, the profile-bound render **0**, with one tie — unanimously on all three questions ("better sound", "more character", "more convincing Atari"). Six songs is not a population, but the direction is consistent, and it is the reason the closing answer is **NO**.
3. **The similarity metric is blind to level.** The band-energy cosine distance that Stage 9C used to stratify the A/B programme predicts perceived similarity well (Spearman **−0.68**, n=30; **−0.55** without the duplicate pairs), but it is computed on a *normalized* spectrum: a pair sustaining 12 dB apart and a byte-identical pair both score ≈ 0.00. The listener disagreed in exactly those cases — the six pairs it called nearly identical but the listener called "quite different" differ by 7–12 dB in level (the sixth differs in generator at matched level). The pitch/centroid gap predicts similarity better than the distance does (−0.71).
4. **The listener keys on the generator; the metric keys on the spectrum.** Every profile called "noisy/crackling/rustling" is a noise or poly generator (`$0`, `$8`) and every one called "clean/clear" is `$A` or `$C`: the family sets are **disjoint**, and spectral flatness does not separate them (median flatness 0.496 for "noisy" versus 0.510 for "clean" — the wrong way round).

**Measurement quality.** The byte-identical groups gave a free repeatability measurement: the same sound, presented under two labels, drew distinctiveness ratings up to 2 points apart (ICC(1,1) 0.73; usefulness 0.76; Atari character 0.92). The listener was reliable, but a one-point difference between profiles is inside the noise. A session effect is present and reported: Atari character and confidence correlate negatively with presentation position (Pearson −0.37 and −0.47), so the later part of the session discriminated less. Loudness is *not* the explanation (largest |rho| against RMS = 0.26), though 10 of 11 decided A/B trials preferred the louder side.

**Seven hypotheses, judged.** H1 partially supported (the distance ranks similarity but barely predicts distinctiveness), H2 supported with two named blind spots, H3 **not** supported (more distinctive is weakly *less* useful, rho −0.24), H4 confirmed, H5 confirmed on the audio rather than on the metric, H6 **falsified for these six songs**, H7 supported.

**Candidate groups and a shortlist.** Five categories with their rules printed: 5 strong candidates, 21 character specialists, 22 technically interesting but perceptually weak, 13 perceptually interesting *despite* weak machine metrics, 30 redundant. The recommended shortlist holds **25** profiles — one representative per byte-identical group (its best-rated member), then the most useful of what remains — with a reason per member, plus a purely diversity-driven greedy alternative. Nothing is removed from the library.

- [src/atari_music/stage9d.py](src/atari_music/stage9d.py): the analysis — answer loading and verification, the identical-audio noise floor with ICC(1,1), Part A/B/C analysis, human-machine correlations (Spearman, Kendall tau-b, Cliff's delta), a blind-spot comparison of every measurable difference against the similarity rating, loudness-bias checks, hypothesis verdicts, five candidate categories, average-linkage clustering with a PCA projection and a greedy coverage set, a 25-profile shortlist with a reason per member, and a machine-readable verdict derived from pre-stated criteria.
- `analyze-listening-test-9d` CLI (deterministic, read-only, refuses a package without answers).
- [docs/stage9d_human_listening_results.md](docs/stage9d_human_listening_results.md): the report, sections 1–14 with Observed / Inference / Recommendation kept apart, and [reports/stage9d/](reports/stage9d/) with `profile_scores.json` plus six more machine-readable extracts.
- [tests/test_stage9d.py](tests/test_stage9d.py) (45 tests): the statistics against hand-computed values, answer verification, mapping and aggregation, the noise floor, category and shortlist rules, determinism, report completeness, and that the analysis cannot modify the answers.
- [tests/test_stage9c.py](tests/test_stage9c.py): one test updated — its premise that the published templates are empty changed when the listening was performed; it now allows empty *or* valid answers and validates the vocabulary.

**Closing answer: NO** — there is not yet enough evidence to select a production library. Two named defects come first: add the level term the distance is blind to, and re-bind the six songs from the listening evidence instead of by generator family, then repeat **only** the whole-song comparison. Selection would then work on audio groups rather than profile ids, and publish a curation document over the existing bank — no profile renamed, none deleted.

Composer suite: **478 passed, 2 deselected** (433 before).

## [2026-10-05] - Profile Listening Experiment (Stage 9C)

The library says what **renders**; it cannot say what is **worth keeping**. Stage 9C builds the blinded listening experiment that asks a human, and decides nothing on their behalf. No composition code, DSL rule, prompt, musical structure, profile document or profile name changed.

**The package** — [examples/sound_profile_listening/](examples/sound_profile_listening/) (gitignored working material, like the songs): `index.html` (a self-contained interface — no server, no Python, no internet; answers kept in `localStorage` and exported as the three CSVs), `audio/` (61 profile stimuli + 12 song excerpts), `manifest.json` (the **private** answer key) and the empty `evaluation_profiles.csv` / `evaluation_ab.csv` / `evaluation_songs.csv` templates.

**One musical input for every profile.** Each of the 61 renderable profiles realizes the same 32-step phrase at the same BPM, velocity, duration and pitch on POKEY channel 1; a `PAIR` profile gets the same phrase with the composition declaring the 1+2 join, since a pair cannot be realized otherwise. A profile is the only variable. Each stimulus is set to the same peak (−0.92 dBFS) by a single gain — no compression, EQ or clipping — with original/final peak **and** RMS recorded, so loudness stays measurable. The A/B trials reuse those very stimuli (the strongest guarantee that everything else is identical); the 6 song pairs apply one *shared* gain and an identical excerpt to both sides.

- [src/atari_music/stage9c.py](src/atari_music/stage9c.py): `build_package` / `analyze_experiment` plus the stimulus, level, spectral-feature, stratification, template, interface and report renderers. The A/B programme is 30 deterministic, stratified trials over the six categories of the brief (similar, distant, same generator family, different families, same source song, cross-song), never reusing a pair, with the A/B sides randomised; the presentation order is a seeded shuffle, so `sample_001` leaks nothing.
- Two CLI commands mirroring the existing listening-test conventions: `prepare-listening-test-9c` (with `--song`/`--seed`, bank read-only) and `analyze-listening-test-9c`.
- **The one honest deviation, recorded not hidden.** Two profiles measure an attack wider than the composer's envelope fields can express (`ENVELOPE_FRAME_ABOVE_CONSUMER_MAX`), which the binding refuses rather than clamping. The stimulus declares that single field from the composer's own character default, and the manifest marks the affected samples (`envelope_source`, `envelope_refusal`); the listener is not told which.
- **Analysis** → `reports/stage9c/{report.md,profile_scores.csv,ab_results.csv,song_results.csv,vocabulary.json}`: medians, distributions, Spearman correlations (technical spectral distance, centroid, bandwidth, flatness, loudness vs the ratings — reported only where the data supports them), the A/B outcome per stratum, counterexamples where the measurements and the listener **disagree**, the song results translated back from blinded sides, the listener's own vocabulary (raw comments kept verbatim), and evidence-based candidate groups with their thresholds stated. It refuses to run on empty templates, is deterministic, and does not declare a library.
- New tests: [tests/test_stage9c.py](tests/test_stage9c.py) (54 tests) — identical musical input, level math, features, stratified A/B construction, manifest completeness, blinded ids, level metadata, template emptiness, song-pair symmetry, determinism (byte-identical audio), "the build cannot modify the bank" (SHA-256 over the bank before/after), the analysis contract, and read-only checks of the published package.

Composer suite: **433 passed, 2 deselected** (379 before). Status: **READY FOR HUMAN LISTENING** — the human evaluation has not been performed and the final 10–20 profile palette has not been chosen.

## [2026-10-05] - Full POKEY Sound Profile Library Published (Stage 9B)

Stage 9 proved the integration with a hand-picked four-profile demo bank. Stage 9B replaces it with the **complete published library — 67 `PlayableSoundProfile` artefacts** — so the Composer has technical access to everything the POKEY Sound Archaeology project produced, behind the interface that already existed.

**No profile was modified.** The bank was published by the archaeology project's own `playable` command (`--all`), and every one of the 67 profile files is byte-identical to what that command wrote; the four profiles of the Stage 9 demo bank kept their exact bytes and fingerprints. Nothing was renamed, regrouped, ranked or removed.

- [tests/data/sound_profiles/bank/](tests/data/sound_profiles/bank/): now `registry.json` (67 entries) + `profiles/` (67 files). Inventory: **49 `VOICE`, 18 `PAIR`**; **22 `PLAYABLE`, 39 `PLAYABLE_WITH_LIMITATION`, 6 `MEASUREMENT_ONLY`**; 61 renderable.
- [src/atari_music/sound_profiles/bank.py](src/atari_music/sound_profiles/bank.py): `SoundProfile` now carries the published verdict (`status`, `blocking_codes`, `limitation_codes`, `consumer_gap_codes`) with `renderable`/`status_known`; the bank exposes `of_status()`, `renderable()` and `status_totals()`. The status is optional, so a bank that predates the audit still loads.
- [src/atari_music/sound_profiles/binding.py](src/atari_music/sound_profiles/binding.py): a profile whose status is not renderable is **refused** with `PROFILE_STATUS_NOT_RENDERABLE` (naming the profile, the status and the blocking codes) instead of being rendered as silence; an unrecognised status is refused with `PROFILE_STATUS_UNKNOWN` so a future verdict cannot pass silently. `describe_binding` reports the status and the codes.
- `--audit-report <playability_audit.json>` on the archaeology `playable` command attaches the audited verdict to each registry entry (additive keys only). Without it the registry is unchanged, which is locked by a test.
- New tests: [tests/test_sound_profile_library.py](tests/test_sound_profile_library.py) (27 tests) — every profile loadable/parseable/fingerprint-valid/registry-addressable; VOICE and PAIR groups checked for their hardware contracts; `$50` verified as staying `$50` (never read as the Composer's `$10`); the six silent profiles refused; the registry/published-status census; determinism; and the Stage 9 regression. Archaeology side: `tests/test_stage9b_publication.py` (11 tests).

**The Stage 9 regression is exact**, proved by SHA-256 against the Stage 9 baseline: `vaults_profile.wav` `91a0a22f…`, `vaults_profile.asm` `56e99472…`, `vaults_default.wav` `b841379c…`, `vaults_default.asm` `92471930…`, `vaults_profile.xex` `428fa499…` — all unchanged with 67 profiles loaded instead of 4.

**Per-song bindings.** [examples/songs/](examples/songs/) holds seventeen songs (twelve DSL, five JSON); each now has a `<song file>.binding.json` naming profiles from the full bank, chosen by **generator family** (mirroring the composer's own character defaults) rather than by preference, one profile per POKEY channel, every one proved by applying it.

Two findings recorded rather than silently fixed: `build-xex -o X.xex` writes its harness assembly to `X.asm` and so overwrites an `--output-asm X.asm` export of the same name (pre-existing; documented, worked around in the example); and the Stage 9 `examples/sound_profiles/vaults_profile.asm` had been overwritten by that collision, so its recorded hash was corrected.

Composer suite: **379 passed, 2 deselected** (352 before). Silent profiles stay published and inspectable — they are simply never rendered as an instrument.lowed by a bulleted list of technical changes with relative paths. -->
## [2026-10-05] - POKEY Sound Profile Integration (Stage 9)

First product integration with the **POKEY Sound Archaeology** project: an existing composition can now be rendered with a real measured POKEY sound profile, without any change to the composition language.

**Architecture.** A profile is a *rendering-time dependency*: the composition describes musical intent, the profile describes POKEY realization. The whole feature lives in a new package [src/atari_music/sound_profiles/](src/atari_music/sound_profiles/) and nothing in `atari_music.ai` imports it.

- [src/atari_music/sound_profiles/bank.py](src/atari_music/sound_profiles/bank.py): loads a portable bank (`registry.json` + `profiles/`), performs exact `profile_id` lookup, and recomputes every `playable_fingerprint` (SHA-256 over the canonical document) so a tampered profile is refused. The bank is self-sufficient — no emulator, SAP file, archaeology code or reference audio is needed. Every refusal carries a stable code (`PROFILE_BANK_MISSING`, `PROFILE_FINGERPRINT_MISMATCH`, `PROFILE_NOT_FOUND`, `PROFILE_SCOPE_UNSUPPORTED`, …).
- [src/atari_music/sound_profiles/binding.py](src/atari_music/sound_profiles/binding.py): the external binding document (`atari-music/sound-profile-binding/1`) and `apply_profile_binding(result, binding, bank, composition)`, which rewrites only the hardware realization of the bound instruments — generator (distortion), envelope, AUDCTL, divider mode — and records provenance. No note, duration, velocity, role, pattern or arrangement is touched.
- Rendering layer: `IRInstrument` gained optional `audctl`, `profile_id` and `profile_fingerprint`; `ir.resolve_audctl_mode(song)` resolves the AUDCTL byte (profile requirements OR-ed with the existing `uses_16bit_bass` flag); `frequency_to_audf_8bit` / `frequency_to_audf_16bit` accept `audctl`/`channel` so a divider is derived under the profile's clock. `pokey_hw.describe_audctl` describes a byte for reporting.
- [src/atari_music/mads_exporter.py](src/atari_music/mads_exporter.py) now uses the same resolved AUDCTL and the same divider arithmetic as the frame compiler, so WAV and XEX cannot disagree. Two coupled bugs were fixed: the export header claimed `AUDCTL=$50` while writing `.byte $10`, and the 16-bit bass instrument table hard-coded `$A0` for channel 2 while the frame compiler writes channel 1's instrument distortion.
- CLI: `--sound-bank` and `--profile-bindings` on `import-json`, `import-dsl` and `build-xex` (all optional). `build_xex_from_composition` gained a profile-agnostic `result_transform(result, composition)` hook so the XEX path shares the profile-aware IR without the AI layer learning about profiles.

**Verified.** 351 tests pass (299 before, 52 new in [tests/test_sound_profiles.py](tests/test_sound_profiles.py)), including an A/B end-to-end proof that the profile changes the audio (identical length and peak, **100 % of samples differ**), a WAV↔XEX agreement test, and a regression test for the nibble→AUDC conversion (`"$A"` → `0xA0`, never `0x0A`).

**Backward compatible**, measured by rebuilding the same compositions before and after with the tracked sources stashed: WAV and XEX byte-identical, all 588 assembly data lines identical (only the false `; Mode:` comment changed), and the exported IR JSON differing only by three new optional `null` fields per instrument.

**Deliberately not converted:** the archaeology `$50` / 1.79 MHz PAIR configuration is never reinterpreted as the Composer's `$10` / 64 kHz 16-bit bass — the profile's AUDCTL is written as given and the divider offset follows the clock (`+7` vs `+1`). Conflicts (AUDCTL, pair channels, explicit distortion, envelope range) are refused with codes rather than approximated.

Documentation: [docs/profile_integration.md](docs/profile_integration.md) (14 sections) plus a runnable example under [tests/data/sound_profiles/](tests/data/sound_profiles/) using the documented *Vaults of Nhyrmeth* DSL composition with an external binding.lowed by a bulleted list of technical changes with relative paths. -->
## [2026-10-05] - Rust Core Engine Acceleration & Test Suite Optimization

** This functionality has been added to separate feat/refactoring branch! **

- Created native PyO3 Rust extension crate `atari_music_core` in [crates/atari_music_core/](crates/atari_music_core/):
  - [crates/atari_music_core/Cargo.toml](crates/atari_music_core/Cargo.toml): configured PyO3 0.29, NumPy 0.29, Rayon 1.10, and Hound 3.5.
  - [crates/atari_music_core/src/pokey.rs](crates/atari_music_core/src/pokey.rs): ported POKEY audio synthesis (`render_pokey_samples_rust`) with 4-channel oscillators, polynomial LFSR sequence generators (4-bit, 5-bit, 9-bit, 17-bit), 16-bit channel pairing, DAC ladder emulation, and high-pass DC blocking IIR filter.
  - [crates/atari_music_core/src/wav.rs](crates/atari_music_core/src/wav.rs): implemented multithreaded WAV file inspection and metrics extraction (`inspect_wav_batch_parallel`) via Hound and Rayon.
  - [crates/atari_music_core/src/lib.rs](crates/atari_music_core/src/lib.rs): exposed `render_pokey_samples`, `read_wav_stats`, and `batch_inspect_wavs` to Python.
- Integrated Rust fast paths with transparent Python fallbacks:
  - [src/atari_music/pokey_synth.py](src/atari_music/pokey_synth.py): delegated `render_pokey_samples` to Rust when available (~14ms vs ~440ms per 24s track, a ~32x speedup), retaining pure-Python NumPy implementation as fallback.
  - [src/atari_music/listening_test_v2.py](src/atari_music/listening_test_v2.py): integrated `batch_inspect_wavs` and optimized audio metrics in `validate_listening_test_v2` and `_read_wav_stats`, dropping 80-file scan from 2.55s to ~0.20s (~13x speedup).
  - [src/atari_music/ai/client.py](src/atari_music/ai/client.py): implemented in-memory assembly content-hash caching for MADS compilation in `build_xex_from_composition` to avoid redundant assembler subprocess invocations.
- Test runner and dependencies updates:
  - [pyproject.toml](pyproject.toml): added `pytest-xdist>=3.5.0` and `maturin>=1.15.0` to `[project.optional-dependencies] dev`.
  - [tests/test_pokey_synth_parity.py](tests/test_pokey_synth_parity.py): added 9 automated parity tests verifying 1.000000 correlation and bit-level accuracy between Rust and Python synthesizers across all distortion modes and 16-bit bass mode.
- Verification & Benchmarks:
  - Full test suite runtime reduced from **~15.0s** to **~2.8s** sequentially, and **~3.7s** across workers with `pytest -n auto`.
  - All 308 tests pass cleanly.

## [2026-09-29] - Added Debug Logging for Music DSL Prompts and Payloads

** This functionality has been added to separate feat/refactoring branch! **

- Added comprehensive `logger.debug` diagnostic logging for Music DSL in [src/atari_music/ai/providers/openai.py](src/atari_music/ai/providers/openai.py) (`_generate_dsl`):
  - Logs `Music DSL System Prompt (version=...)` and `Music DSL User Prompt`.
  - Logs repair feedback and previous DSL when entering a retry loop (`Music DSL Repair Prompt:`).
  - Logs sanitized API request endpoint, model, messages count, and full request payload.
  - Logs received raw DSL response text and completion ID.
- Added DEBUG logging for mock provider DSL prompts in [src/atari_music/ai/providers/mock.py](src/atari_music/ai/providers/mock.py) (`generate_composition_dsl`).
- Added unit tests in [tests/test_logging.py](tests/test_logging.py):
  - `test_openai_provider_dsl_prompt_debug_logging`: asserts that system prompt, user prompt, and payload are logged under `DEBUG` while protecting secret keys.
  - `test_openai_provider_dsl_repair_prompt_debug_logging`: verifies feedback and repair content logging during retry attempts.
  - `test_mock_provider_dsl_prompt_debug_logging`: verifies mock DSL prompt logging under `DEBUG`.
- Verified test suite: all 299 tests pass.


## [2026-09-29] - Music DSL v1.1 Implementation & 30-Trial Controlled Regression Benchmark

- Implemented **Music DSL v1.1** with automatic pattern length inference in [src/atari_music/ai/dsl.py](src/atari_music/ai/dsl.py):
  - Made pattern `length=` parameter optional; when omitted, pattern length is deterministically derived as `length_steps = max(channel_end_steps)`.
  - Maintained backward compatibility: explicit `length=` declarations are fully parsed and validated; if events exceed explicit length, `DSLSyntaxError` is raised with line context.
  - Updated `export_music_dsl(doc, include_lengths=False)` to default to omitting `length=` from pattern headers (`[PATTERN <id>]`), preserving trailing rest padding for shorter channels.
- Updated LLM prompting in [src/atari_music/ai/prompts.py](src/atari_music/ai/prompts.py):
  - Updated `build_dsl_system_prompt(version="v1.1")` and `build_dsl_user_prompt` with the explicit rule: *"Do not specify pattern length. Pattern length is calculated automatically from the events."*
  - Preserved backward compatibility for `version="v1"`. JSON prompts remain completely untouched.
- Updated provider request handling in [src/atari_music/ai/providers/base.py](src/atari_music/ai/providers/base.py) and [src/atari_music/ai/providers/openai.py](src/atari_music/ai/providers/openai.py):
  - Added `dsl_version: str = "v1.1"` to `CompositionRequest` and propagated it to `build_dsl_system_prompt()`.
- Added regression and edge case unit tests in [tests/test_dsl.py](tests/test_dsl.py):
  - `test_dsl_v1_1_inferred_length_single_channel`: verifies single-channel inferred length without `length=`.
  - `test_dsl_v1_1_inferred_length_multichannel_max`: verifies multi-channel max end step derivation (32 vs 64 steps -> 64).
  - `test_dsl_v1_1_inferred_length_trailing_rest`: verifies trailing rests advance step timing and determine pattern length.
  - `test_dsl_v1_1_empty_pattern_default_length`: verifies empty pattern receives default length 16.
  - `test_dsl_v1_1_16bit_bass_pairing`: verifies BASS 16BIT coupling with master/slave channels without `length=`.
  - `test_dsl_v1_1_explicit_length_backward_compatibility`: verifies explicit `length=64` is retained.
  - `test_dsl_v1_1_explicit_length_mismatch_too_small_raises`: verifies explicit length smaller than events raises `DSLSyntaxError`.
  - `test_dsl_v1_1_explicit_length_larger_than_events_retained`: verifies explicit length larger than events is preserved.
  - `test_dsl_v1_1_export_omits_lengths_by_default`: verifies export round-trip without `length=`.
  - `test_dsl_v1_1_full_equivalence_ir_asm_wav`: verified 100% bit-level equivalence (identical POKEY IR, byte-identical MADS ASM, bit-identical WAV audio) across reference songs.
  - Test suite status: all 295 pytest tests passing.
- Executed 30-trial controlled regression benchmark comparing DSL v1 vs DSL v1.1 via [scripts/benchmark_dsl_v1_vs_v1_1.py](scripts/benchmark_dsl_v1_vs_v1_1.py) on `deepseek-flash`:
  - 5 categories × 2 conditions (DSL v1 vs DSL v1.1) × 3 repetitions = 30 trials.
  - Results:
    - **Length-related errors (`PATTERN_LENGTH_EXCEEDED`):** eliminated from **2 in v1** (Category E) to **0 in v1.1**.
    - **Initial success rate:** increased from **86.7%** (13/15) in v1 to **100.0%** (15/15) in v1.1.
    - **Final success rate:** **100.0%** for both versions.
    - **Repair attempts:** reduced from 2 in v1 (mean 0.133) to **0 in v1.1** (mean 0.0).
    - **Hardware pass (POKEY IR -> ASM -> WAV):** **100%** (30/30 trials).
    - **Total tokens:** reduced by **19.9%** (217,753 in v1 vs 174,398 in v1.1; 14,516.9 vs 11,626.5 tokens per successful composition).
    - **Mean latency:** reduced from 44.98 s to **37.71 s** (16% faster).
    - **Musical complexity:** distributions of note counts, sequence length, and unique pitches remained comparable.
  - Artifacts recorded in `benchmark_results/dsl_v1_1_20260929_180136/`: `raw_trials.json`, `summary.json`, `report.md`.


## [2026-09-29] - Separation of CLI Import Commands (import-json & import-dsl) and Elimination of Extension-Based Ingestion

- Separated composition import into two explicit, dedicated CLI commands in [src/atari_music/cli.py](src/atari_music/cli.py):
  - `atari-music import-json`: strictly validates and imports canonical JSON files via `load_composition_json`, failing fast with clear errors if non-JSON is provided.
  - `atari-music import-dsl`: strictly parses and validates Music DSL (`.dsl`) files via `load_composition_dsl`, with options for `--output-wav`, `--output-asm`, `--output-ir`, and `--output-json` (exporting canonical JSON).
- Removed extension-based format guessing in [src/atari_music/ai/client.py](src/atari_music/ai/client.py) (`load_composition`):
  - Replaced `.suffix` extension inspection (`.dsl` / `.mdsl`) with explicit format enforcement (`format="dsl"` or `format="json"`) or content-based detection (`{` inspection) when format is unspecified.
  - Enhanced error handling in `import_json_cmd` and `import_dsl_cmd` using `click.ClickException` for syntax and validation diagnostics.
- Updated `build-xex` CLI command in [src/atari_music/cli.py](src/atari_music/cli.py) to accept optional explicit `--format [json|dsl]`.
- Added unit and regression tests in [tests/test_cli.py](tests/test_cli.py):
  - `test_cli_import_json_success`: verifies successful JSON import and output generation.
  - `test_cli_import_json_rejects_dsl_or_invalid`: verifies that `import-json` rejects non-JSON / DSL files.
  - `test_cli_import_dsl_success`: verifies DSL import, canonical JSON export, and ASM/IR compilation.
  - `test_cli_import_dsl_rejects_json_or_invalid`: verifies that `import-dsl` rejects JSON / malformed input.
  - `test_cli_build_xex_with_explicit_format`: verifies that `build-xex` works with `--format dsl` and `--format json` regardless of file extension.
- Updated documentation in [README.md](README.md), [SKILL.md](SKILL.md), and [docs/music_dsl.md](docs/music_dsl.md).
- Verified full test suite: all 283 tests passing cleanly.


- Executed full 100-trial empirical benchmark suite (5 categories × 2 formats × 10 runs) against `deepseek-flash` via [scripts/benchmark_llm_formats.py](scripts/benchmark_llm_formats.py):
  - Completed 50 JSON and 50 DSL trials with zero modifications to DSL grammar, parser, or prompts mid-experiment (git commit SHA: `2828724bb3fa452b724a96d47d417ecb38febb4c`).
  - Recorded exact API token usage (`response.usage`), character metrics (`input_chars`, `output_chars`), generation/repair wall-clock latency, and 100% hardware validation (POKEY IR -> MADS ASM -> WAV audio synthesis).
  - Measured token efficiency: Music DSL reduced total tokens by **49.4%** (1,375,618 vs 695,673 tok) and tokens per successful composition by **49.4%** (27,512.4 vs 13,913.5 tok), maintaining 100% final success rate and comparable musical complexity.
  - Generated audit artifacts in [benchmark_results/run_1790692314/](benchmark_results/run_1790692314/): `raw_trials.json`, `summary.json`, and `report.md` with bootstrap 95% confidence intervals.
  - Enabled direct compilation of `.dsl` files to Atari XEX binary in [src/atari_music/ai/client.py](src/atari_music/ai/client.py) (`build_xex_from_composition`) and CLI (`atari-music build-xex`), verified via [tests/test_dsl.py](tests/test_dsl.py).
  - Verified test suite: all 278 pytest unit & integration tests passing cleanly.

## [2026-09-29] - Implementation & Validation of LLM Benchmark Runner (JSON vs Music DSL)

- Implemented comprehensive empirical benchmark harness in [scripts/benchmark_llm_formats.py](scripts/benchmark_llm_formats.py):
  - Strict experiment tracking: records `provider`, `model`, `temperature`, `prompt_id`, `condition` (`json` / `dsl`), `seed`, and UTC `timestamp`.
  - Captures exact API token usage (`prompt_tokens`, `completion_tokens`, `total_tokens`) directly from provider completions (`response.usage`), flagging estimated tokens separately if missing.
  - Implemented 5 standardized prompt specifications across key structural archetypes (duet, typical 4-ch, multi-section, 16-bit bass, macro-form architecture) with semantically identical musical requests across conditions.
  - Integrated 9 objective musical complexity metrics via `analyze_composition`: `duration`, `pattern_count`, `sequence_length`, `active_channels`, `note_count`, `rest_count`, `unique_instruments`, `unique_pitches`, and `lead_note_count`.
  - Granular failure classification: `JSON_SYNTAX`, `JSON_SCHEMA`, `JSON_MUSICAL`, `JSON_HARDWARE`, `DSL_SYNTAX`, `DSL_STRUCTURE`, `DSL_MUSICAL`, `DSL_HARDWARE`, `PROVIDER_ERROR`, `TIMEOUT`.
  - Auditable persistence: records full raw attempt traces, validation issues, and generated contents in `benchmark_results/<run_id>/raw_trials.json` and statistical summaries in `summary.json`.
- Extended repair loop tracking in [src/atari_music/ai/client.py](src/atari_music/ai/client.py):
  - Updated `generate_composition_with_retry` to support `return_history=True` returning complete attempt diagnostic records with token usage per attempt.
- Fixed hardware channel padding in [src/atari_music/ai/dsl.py](src/atari_music/ai/dsl.py):
  - In `_flush_current_pattern`, limited empty channel initialization to `range(1, channels_count + 1)` rather than hardcoded 4 channels, preventing false `CHANNEL_OUT_OF_RANGE` validation errors when 2 channels are requested.
- Fixed client instantiation in [src/atari_music/ai/providers/openai.py](src/atari_music/ai/providers/openai.py):
  - Added reusable `_get_client()` method in `OpenAICompositionProvider` used by both JSON and DSL generation pipelines.
- Successfully executed 30-trial smoke test (5 prompts × 2 formats × 3 runs) against `deepseek-flash`: verified 100% token usage capture, repair loop operation, parser, validator, and metrics aggregation.

- Designed and implemented an optional, human- and LLM-friendly **Music DSL** in [src/atari_music/ai/dsl.py](src/atari_music/ai/dsl.py):
  - `parse_music_dsl(text, validate=True)`: deterministic lexer/parser with line and column diagnostics, step accumulation, automatic pattern length derivation, and canonical validation integration.
  - `export_music_dsl(doc)`: lossless serializer converting `AICompositionDoc` into compact, readable Music DSL text.
  - `DSLSyntaxError`: structured exception with line numbers, column positions, and source code snippet diagnostics.
- Preserved `AICompositionDoc` and JSON schema as the canonical Single Source of Truth (SSOT); Music DSL is strictly an opt-in frontend without an alternative IR.
- Integrated Music DSL prompts into [src/atari_music/ai/prompts.py](src/atari_music/ai/prompts.py): added `build_dsl_system_prompt()` and `build_dsl_user_prompt()`.
- Updated provider abstraction in [src/atari_music/ai/providers/base.py](src/atari_music/ai/providers/base.py): added `format="json"|"dsl"` to `CompositionRequest` and `generate_composition_dsl()` protocol method.
- Implemented DSL generation in [src/atari_music/ai/providers/mock.py](src/atari_music/ai/providers/mock.py) and [src/atari_music/ai/providers/openai.py](src/atari_music/ai/providers/openai.py) (with markdown code-fence sanitization and transient HTTP retry backoff).
- Extended client and AI repair loop in [src/atari_music/ai/client.py](src/atari_music/ai/client.py):
  - `generate_composition_with_retry`: branches on `request.format`, handling both `DSLSyntaxError` diagnostics and 3-tier validation reports.
  - Added polymorphic `load_composition(source, format=None)` supporting `.dsl`, `.json`, dicts, or doc instances.
  - Added `generate_music_from_dsl(dsl_source)`.
- Updated CLI in [src/atari_music/cli.py](src/atari_music/cli.py):
  - `ai-compose`: added `--format [json|dsl]` option (defaults to `json` for 100% backwards compatibility).
  - `import-json` & `build-xex`: support loading `.dsl` and `.json` files seamlessly via `load_composition`.
- Created benchmark script [scripts/benchmark_dsl_vs_json.py](scripts/benchmark_dsl_vs_json.py): verified an average **83.2% token reduction** and **89.5% character reduction** across real production compositions (`examples/ai/`) with parsing latency under 1ms.
- Verified 100% byte-for-byte POKEY IR, MADS ASM, and synthesized WAV identity across JSON and DSL compilation pipelines in [tests/test_dsl.py](tests/test_dsl.py) (19 unit/equivalence tests added, all 276 suite tests passing).
- Documented complete formal grammar, semantics, timing rules, and CLI/API usage in [docs/music_dsl.md](docs/music_dsl.md).

## [2026-09-29] - Fix XEX Keyboard Scancodes for Channel Muting (Keys 1-4)

- Fixed keyboard scancodes in [src/atari_music/ai/client.py](src/atari_music/ai/client.py): updated `key_table` in the generated XEX assembly harness from `$1E, $1D, $19, $18` to `$1F, $1E, $1A, $18`. Atari POKEY keyboard matrix scancodes in `CH` ($02FC) for number keys '1'..'4' are `$1F` (31), `$1E` (30), `$1A` (26), and `$18` (24). Resolves channel toggle mismatches where '2' toggled CH1, '5' (`$1D`) toggled CH2, and '1' / '3' were unresponsive.
- Updated unit test assertion in [tests/test_duration.py](tests/test_duration.py): `test_xex_harness_channel_mute_and_colors` now expects `.byte $1F, $1E, $1A, $18`.
- Corrected scancode reference table in [.agents/skills/atari8bit/system/input.md](.agents/skills/atari8bit/system/input.md) for keys '1'..'6' and ESC.

## [2026-09-28] - Post-Implementation Fixes (F-1, F-2, F-3, F-5, F-6, F-7)

Fixes for the findings of the independent post-implementation audit, keeping
[src/atari_music/pokey_hw.py](src/atari_music/pokey_hw.py) as the single source of truth.

- **F-2 (release off-by-one)** in [src/atari_music/pokey_hw.py](src/atari_music/pokey_hw.py):
  `player_envelope_volumes` sustained with `ticks_remaining <= release`; `player.asm` uses the
  strict `ch_dur < ch_rel`, so the preview released one row tick (4–6 frames) early. Changed to
  `ticks_remaining < release` and corrected the docstring. Derived empirically, not from the
  report: `player.asm` was executed under a 6502 emulator (py65) for 7 ADSR/tempo combinations and
  compared frame-by-frame against both variants — strict `<` gives 0 mismatches, `<=` gives 6/7.
- **F-1 (unpitched percussion)** in [src/atari_music/ir.py](src/atari_music/ir.py) and
  [src/atari_music/mads_exporter.py](src/atari_music/mads_exporter.py): a percussion note with no
  resolvable pitch was rendered as the implicit MIDI 60 (AUDF `$47`) in the WAV register stream but
  as silence (AUDF `$00`, volume 0) in the exported tracker bytes, so the preview and the Atari
  disagreed. Both paths now use an explicit shared fallback
  (`pokey_hw.PERCUSSION_DEFAULT_AUDF = $50` + `pokey_hw.is_unpitched_percussion`), producing a real
  audible hit with the instrument's own distortion and envelope. Pitched percussion and rests are
  unaffected. A differential over `generator.generate_song` seeds 0–7 now reports 4400 compared
  events and 0 WAV↔ASM mismatches.
- **F-3 (8-bit AUDF floor)** — added to [src/atari_music/pokey_hw.py](src/atari_music/pokey_hw.py):
  `raw_audf_8bit` (unclamped divider), `eight_bit_floor_hz()` (~124.19 Hz for `AUDF $FE`) and
  `describe_8bit_range_error()` (requested Hz, unclamped divider, best representable Hz, cents).
  Added `find_pitch_range_issues(song)` to [src/atari_music/ir.py](src/atari_music/ir.py), and
  `export_mads_asm` now logs one aggregated warning instead of silently detuning. The AI path gained
  a non-fatal warning channel: `ValidationReport.warnings` / `add_warning()` in
  [src/atari_music/ai/schema.py](src/atari_music/ai/schema.py) (deliberately does **not** clear
  `valid`, so it cannot fail validation or trigger composition repair) and a
  `PITCH_OUT_OF_8BIT_RANGE` warning emitted from
  [src/atari_music/ai/validation.py](src/atari_music/ai/validation.py). Detected in the real
  composition `dziki-zgon-title-x.json`: 151 notes below the floor, worst C1 at 32.7 Hz clamped to
  124.19 Hz (+2310 cents). No automatic switch to 16-bit bass.
- **F-5** in [src/atari_music/mads_exporter.py](src/atari_music/mads_exporter.py): the empty 16-bit
  slave track (channel 2) hardcoded a 32-row rest; it now rests for `pat.rows`.
- **F-6** dead imports removed from [src/atari_music/ir.py](src/atari_music/ir.py) (`math`,
  `DISTORTION_4BIT_POLY`, `DISTORTION_WHITE_NOISE`, `PAL_CLOCK_HZ`) and
  [src/atari_music/features.py](src/atari_music/features.py) (`DISTORTION_WHITE_NOISE`,
  `PAL_15KHZ_CLOCK`, `PAL_64KHZ_CLOCK`, `PAL_CLOCK_HZ`).
- **F-7** [src/atari_music/reporting.py](src/atari_music/reporting.py): the AUDC table still labelled
  `$E0` as "White Noise" and grouped `$00` with `$40`. Labels and equivalence groups now follow
  `pokey_hw.decode_audc` (`$A0`/`$E0` and `$20`/`$60` are identical; `$00`, `$40`, `$80`, `$C0` are
  distinct; `$80` is the only true noise). Removed the stale `$E0` comment in
  [src/atari_music/classifier.py](src/atari_music/classifier.py).
- `IRMacroStep` / `IRInstrument.macro` are now explicitly documented as reserved (not rendered, not
  exported). The audit's F-4 (procedural kick/snare/hi-hat macro sweep) remains unimplemented: the
  macro semantics are ambiguous (`audf_offset` holds absolute-looking values) and rendering it would
  change the exported data layout. The F-1 fix removes the worst symptom — drums are now real
  percussive hits instead of a sustained wrong-pitch MIDI 60.
- Tests: corrected `test_envelope_release_is_linear_decrement` in
  [tests/test_pokey_semantics.py](tests/test_pokey_semantics.py), which had encoded the off-by-one,
  and added hand-derived release expectations. New regression coverage in the same file: the
  py65-backed `test_emulated_player_envelope_matches_model` (7 parametrised cases, comparing the
  emulated player's `AUDC1` writes against the model), unpitched/pitched percussion and rest
  handling, the procedural-generator end-to-end percussion check, 8-bit range detection (boundary,
  boundary±, cents), the warning-is-not-an-error contract, and the 16-bit slave rest length.
  258 tests pass; `python -m build --no-isolation` succeeds.

## [2026-09-28] - Unified POKEY Semantics (single source of truth)

- Added [src/atari_music/pokey_hw.py](src/atari_music/pokey_hw.py): the single source of truth for
  POKEY hardware semantics — AUDC distortion decoding (`decode_audc`), clock/divider arithmetic
  (`hz_from_audf_8bit` / `hz_from_audf_16bit` and inverses), the tracker AUDF clamp, and the
  player's ADSR envelope model (`player_envelope_volumes`). Derived from two independent reference
  emulators (atari800 `pokeysnd.c`, `mzpokeysnd.c`).
- Fixed distortion semantics in [src/atari_music/constants.py](src/atari_music/constants.py):
  `DISTORTION_WHITE_NOISE` is now `$80` — the real poly9/poly17 noise mode. `$E0` is documented as
  audibly identical to `$A0` (PURETONE outranks POLY4) and is no longer treated as noise anywhere.
  Added AUDC bit-mask constants.
- [src/atari_music/pokey_synth.py](src/atari_music/pokey_synth.py): waveform selection now uses
  `pokey_hw.decode_audc`, so `$E0` renders as a pure tone and `$40` (poly5-gated poly4) is
  implemented instead of falling back to a square wave. Frequency math delegates to `pokey_hw`.
- [src/atari_music/ir.py](src/atari_music/ir.py): AUDF is clamped with
  `pokey_hw.clamp_audf_for_tracker` — `$FF` is the tracker end-of-track marker, so the WAV register
  stream and the ASM export now agree on `$FE` instead of silently diverging. The 16-bit joined
  divider offset was corrected to `+1` (was `+2`). Frequency helpers delegate to `pokey_hw`, and the
  per-frame envelope mirrors `player.asm`. `IRNote.vibrato/slide/arpeggio` and `IRInstrument.macro`
  are no longer applied during frame rendering (the 6502 player cannot reproduce them), so the WAV
  preview matches what real hardware plays.
- [src/atari_music/mads_exporter.py](src/atari_music/mads_exporter.py): AUDF clamping and 16-bit
  math via `pokey_hw`; notes without a resolvable pitch render as silence (previously a hardcoded
  AUDF); empty channels rest for `pat.rows` (previously hardcoded 32 rows); durations clamped to a
  byte.
- [src/atari_music/features.py](src/atari_music/features.py): the analysis/decoder path delegates to
  `pokey_hw` (fixing the same 16-bit `+2` offset in the decode direction) and decodes noise via
  `decode_audc`, so `$E0` is treated as a pitched pure tone rather than noise.
- AI contract: [src/atari_music/ai/composition.py](src/atari_music/ai/composition.py) maps
  `kick`/`tom` to poly4 and `percussion`/`noise`/`drum`/`snare`/`hihat` to real noise (`$80`);
  channel instrument resolution is now deterministic (one instrument per channel, matching the
  player). [src/atari_music/ai/validation.py](src/atari_music/ai/validation.py) accepts only real
  AUDC distortion bytes. [src/atari_music/ai/prompts.py](src/atari_music/ai/prompts.py) documents the
  one-instrument-per-channel rule and the real percussion/instrument vocabulary.
- Tests: added [tests/test_pokey_semantics.py](tests/test_pokey_semantics.py) — independent golden
  tests with hand-computed expected values (AUDC truth table, `$E0`/`$40`, 8-bit and 16-bit
  dividers, `$FF` clamp, percussion mapping, envelope shape, LFSR maximal-length, WAV↔ASM AUDF
  consistency, end-to-end pipeline) — and de-circularised
  `test_mads_export_percussion_consistency` in [tests/test_pokey_music.py](tests/test_pokey_music.py).

## [2026-09-28] - Semantic Alignment of MADS Exporter with POKEY IR & WAV Renderer

- Fixed dynamic instrument assignment per channel in [src/atari_music/mads_exporter.py](src/atari_music/mads_exporter.py):
  - Removed hardcoded instrument channel assumptions (`def_inst_id = 1 if ch == 1 else ...`).
  - Added `_find_channel_instrument` to derive the active channel instrument directly from `IRNote.instrument_id` and pattern tracks, preserving each instrument's actual distortion (e.g. `$E0` for `perc`) and ADSR envelope.
  - Linked joined 16-bit bass hardware slave (Channel 2) directly to Channel 1's resolved bass instrument envelope while retaining pure tone distortion `$A0`.
- Eliminated hardcoded percussion frequency override in [src/atari_music/mads_exporter.py](src/atari_music/mads_exporter.py):
  - Removed `if note.channel_role == "percussion": audf = 12 if vol >= 14 else (24 if vol >= 11 else 8)`.
  - Added `_note_to_midi` helper to resolve MIDI pitch from either `midi_pitch` or note name strings (e.g. `A2` -> MIDI 45 -> 110 Hz).
  - Ensured percussion notes with specified pitch undergo the standard `frequency_to_audf_8bit` conversion (yielding `AUDF = $FE` for `A2` instead of hardcoded `AUDF = $08`), preventing high-pitched 3.5 kHz pure tone artifacts ("dzwoneczek") on Atari hardware.
  - Preserved fallback percussion divider defaults strictly for unpitched hits (`pitch=None`).
- Updated [src/atari_music/ai/composition.py](src/atari_music/ai/composition.py) in `compile_composition_to_pokey_ir` to retain matched event instruments rather than arbitrarily overwriting `instrument_id = 3` for percussion tracks.
- Added regression unit test `test_mads_export_percussion_consistency` to [tests/test_pokey_music.py](tests/test_pokey_music.py) validating:
  - CH3 in `song_data_instruments` uses the `perc` instrument with distortion `$E0`.
  - CH3 in `song_data_pat_0_ch3` does not hardcode `AUDF = $08` and accurately matches POKEY IR (`AUDF = $FE` for `A2`).
  - Channels 1 and 2 remain unaffected with correct instruments and AUDF dividers.


- Replaced flat 44.1 kHz `noise_pool` in [src/atari_music/pokey_synth.py](src/atari_music/pokey_synth.py) with accurate POKEY hardware LFSR emulation:
  - Precomputed `POLY17_SEQ` (131,071 states, polynomial $1 + x^{12} + x^{17}$) and `POLY9_SEQ` (511 states, polynomial $1 + x^4 + x^9$, activated via `AUDCTL_9BIT_POLY = 0x80`).
  - Toggled noise bit transitions at the channel divider clock rate ($f_{\text{divider}} = 2.0 \cdot \text{freq} = \text{base} / (\text{AUDF} + 1)$), correctly applying Sample & Hold between divider ticks.
  - Implemented continuous per-channel LFSR step tracking (`ch_lfsr_steps`) across 50 Hz frames to preserve smooth phase continuity and eliminate frame boundary clicks.
  - Updated composite distortion mode `$00` (5-bit + 17-bit poly) to XOR-modulate the 5-bit poly sequence against the AUDF-clocked 17-bit noise stream.
  - Eliminated large per-call `noise_pool` memory allocations in `render_pokey_samples`.
- Fixed dynamic address resolution for `music_update` in [tests/test_duration.py](tests/test_duration.py) to prevent py65 emulation hangs caused by hardcoded harness offsets.
- Added comprehensive unit tests to [tests/test_pokey_music.py](tests/test_pokey_music.py):
  - `test_pokey_noise_audf_frequency_response`: Verifies zero-crossing rate scales drastically with AUDF (low pitch/A2 drum vs high pitch/hi-hat).
  - `test_pokey_noise_determinism`: Verifies bit-for-bit reproducible WAV output for identical frame inputs.
  - `test_pokey_noise_9bit_vs_17bit`: Verifies `AUDCTL_9BIT_POLY` produces distinct raspy 9-bit timbres.
  - `test_game_over_percussion_rendering`: Verifies end-to-end rendering of the *Game Over* comic thud percussion event (`A2`).


## [2026-09-28] - Package Version Synchronization & Semantic Release Tracking

- Updated `__version__` in [src/atari_music/__init__.py](src/atari_music/__init__.py) to dynamically retrieve package metadata via `importlib.metadata.version("atari-music")` with fallback to the current release version (`0.5.0`).
- Configured `version_variables = ["src/atari_music/__init__.py:__version__"]` under `[tool.semantic_release]` in [pyproject.toml](pyproject.toml) so `python-semantic-release` automatically updates `__init__.py` in sync with `pyproject.toml` on every release.
- Added `test_cli_version_flag` to [tests/test_cli.py](tests/test_cli.py) validating that both `atari-music -v` and `atari-music --version` correctly report `atari_music.__version__`.

## [2026-09-28] - Interactive Channel Muting (Keys 1-4) & Dark Green Theme for XEX Visualizer

- Added per-channel mute toggling (`ch_mute_mask: .byte 0, 0, 0, 0`) to [player.asm](player.asm) and [src/atari_music/asm/player.asm](src/atari_music/asm/player.asm) inside `write_pokey_registers` for both standard 8-bit and joined 16-bit bass modes.
- Updated XEX visualizer harness in [src/atari_music/ai/client.py](src/atari_music/ai/client.py):
  - Added keyboard scancode decoding for keys 1..4 (scancodes `$1E`, `$1D`, `$19`, `$18`) to toggle individual channels 1 to 4 on/off at runtime.
  - Set dark green color scheme for background and border via `$C4` (hue `$C` green, luminance 4) in OS shadow registers (`$02C6` / `COLOR2`, `$02C8` / `COLOR4`) and GTIA registers (`$D018` / `COLPF2`, `$D01A` / `COLBK`).
  - Added visual `ON ` / `OFF` indicator labels next to each channel VU meter box (cols 26..28) dynamically reflecting mute status.
  - Muted channels automatically silence audio output and zero out real-time VU meter bars.
  - Updated screen footer to display `[1-4] MUTE CH   [SPACE] PLAY/PAUSE`.
  - Optimized harness footprint via compact string printing subroutine (`print_string` / `get_cell_ptr`), reducing XEX code size to stay strictly within the 2048-byte limit across all AI composition artifacts.
    - **Superseded 2026-10-09:** the 2048-byte limit now bounds the *assembled player*, not the complete XEX file. The harness optimisation above stands on its own (a smaller harness is a smaller executable), but the whole-file rule it was serving was removed; see the 2026-10-09 entry. `reports/stage15/player_size_analysis.json` is the authoritative statement of the limit in force.
- Added unit tests in [tests/test_duration.py](tests/test_duration.py) validating assembly generation for channel muting keys, mask, and GTIA color registers.

## [2026-09-28] - Untrack Structure Metrics Files from Git

- Removed `stage16_structure_metrics.json` and `stage17_structure_metrics.json` from git tracking (`git rm --cached`) while preserving local copies on disk.
- Confirmed files remain ignored via the `/stage*.json` rule in [.gitignore](.gitignore).

## [2026-09-28] - Server Retry-Delay Parsing for HTTP 429 Rate Limits

- Implemented `extract_retry_delay()` in [src/atari_music/ai/providers/openai.py](src/atari_music/ai/providers/openai.py) to dynamically extract and respect server-requested rate limit backoff durations rather than relying solely on fixed exponential intervals.
- Added multi-source delay detection:
  - HTTP `Retry-After` (seconds) and `Retry-After-Ms` response headers.
  - Google Cloud RPC `RetryInfo` details in structured response bodies (`retryDelay`).
  - Regex pattern matching against natural language server error messages (e.g. `Please retry in 57.489879459s`, `retry in Xs`, `retry after Xs`, `try again in Xs`).
  - Automatic `+ 1.0s` safety margin to ensure retries occur strictly after the provider's rate-limit window resets.
- Updated `OpenAICompositionProvider.generate_composition` in [src/atari_music/ai/providers/openai.py](src/atari_music/ai/providers/openai.py) and `generate_composition_with_retry` in [src/atari_music/ai/client.py](src/atari_music/ai/client.py) to prioritize server-dictated retry delays over static backoffs, preventing premature exhaustion of retry quotas.
- Added unit tests in [tests/test_transient_retry.py](tests/test_transient_retry.py) verifying regex extraction across Google 429 messages, HTTP headers, RPC bodies, and end-to-end provider recovery using server-directed sleep times.

## [2026-09-28] - Add -v / --version CLI Flag

- Added `@click.version_option` (`-v`, `--version`) to the root `@click.group()` in [src/atari_music/cli.py](src/atari_music/cli.py) sourcing `__version__` from [src/atari_music/__init__.py](src/atari_music/__init__.py).
- Allows running `atari-music -v` or `atari-music --version` to immediately print application version and exit cleanly (code 0) without executing any subcommands or requiring parameters.
- Preserved existing subcommand option functionality (e.g. `-v` / `--variation` in `atari-music compose`).
- Added automated unit test `test_cli_version_flag` in [tests/test_cli.py](tests/test_cli.py) covering `-v` and `--version` invocations.

## [2026-09-28] - Exponential Backoff for Transient HTTP 503 & 429 API Errors

- Implemented `_is_transient_http_error()` in [src/atari_music/ai/providers/openai.py](src/atari_music/ai/providers/openai.py) to detect transient server congestion (HTTP 503, 502, 504) and rate limiting (HTTP 429, `RateLimitError`).
- Added configurable exponential backoff retry loop in `OpenAICompositionProvider.generate_composition` ([src/atari_music/ai/providers/openai.py](src/atari_music/ai/providers/openai.py)) with initial 5.0 s wait scaling to 10.0 s, 20.0 s up to 30.0 s, preventing sudden crashes during momentary server load spikes.
- Prevented immediate failure in fallback completion paths when encountering transient errors, prioritizing exponential backoff retries over premature schema fallbacks.
- Added transient API error recovery in `generate_composition_with_retry` ([src/atari_music/ai/client.py](src/atari_music/ai/client.py)), ensuring the high-level musical repair loop waits and retries if transport-level errors bubble up.
- Added unit tests in [tests/test_transient_retry.py](tests/test_transient_retry.py) verifying 503/429 detection, exponential backoff timing, successful recovery, and non-transient immediate failure behavior.

## [2026-09-28] - Generic AI Configuration Refactoring & Custom Env-File Support

- Refactored [config.py](config.py): removed `DEEPSEEK_*` names from the primary configuration interface and replaced them with generic keys `AI_PROVIDER`, `AI_API_KEY`, `AI_BASE_URL`, and `AI_MODEL`.
- Added backward compatibility layer in [config.py](config.py): implemented properties and kwargs aliases for `deepseek_api_key`, `deepseek_base_url`, and `deepseek_model`, and maintained automatic fallback reading for legacy `DEEPSEEK_*` and `OPENAI_*` variables in `.env` and system environment.
- Enforced strict priority resolution chain: `CLI argument > System environment > env-file > Code defaults`.
- Guaranteed system environment immutability: loading `.env` values (via `dotenv_values`) never mutates or overwrites existing variables in `os.environ`.
- Added global `--env-file PATH` CLI option to [config.py](config.py) and [src/atari_music/cli.py](src/atari_music/cli.py) (`@click.group()` and `ai-compose`), allowing custom `.env` file locations to be specified.
- Preserved CLI `--provider` option on `ai-compose` and [config.py](config.py) as an explicit override for `AI_PROVIDER`.
- Updated [src/atari_music/ai/providers/__init__.py](src/atari_music/ai/providers/__init__.py) and [src/atari_music/ai/providers/openai.py](src/atari_music/ai/providers/openai.py) to read `AI_*` settings from `Config` and environment first with legacy fallbacks.
- Updated [src/atari_music/ai/client.py](src/atari_music/ai/client.py) to pass custom `env_path` to `get_ai_provider`.
- Updated [check_config.py](check_config.py) and [main.py](main.py) to inspect and report `AI_PROVIDER`, `AI_API_KEY`, `AI_BASE_URL`, `AI_MODEL`, and `ENV_FILE`.
- Updated [.env.example](.env.example) with canonical `AI_PROVIDER=deepseek`, `AI_API_KEY`, `AI_BASE_URL`, and `AI_MODEL`.
- Updated [README.md](README.md) and [SKILL.md](SKILL.md) documentation with new environment variables, `--env-file` option, and provider priority details.
- Updated and expanded [tests/test_config.py](tests/test_config.py) and [tests/test_live_production.py](tests/test_live_production.py) verifying priority chain, system environment immutability, `--provider` override, custom `--env-file`, and legacy `.env` backward compatibility.
- Updated [.gitignore](.gitignore) to ensure `poc_output/` is ignored across the repository, untracked from git index, and preserved locally.
- Placed canonical configuration inside the package at [src/atari_music/config.py](src/atari_music/config.py) and retained [config.py](config.py) as a root backward-compatibility shim, resolving `ModuleNotFoundError: No module named 'config'` when invoking the installed console script executable `atari-music`.

## [2026-09-27] - System & User Prompt Revision for AI Composer

- Redesigned `build_system_prompt()` in [src/atari_music/ai/prompts.py](src/atari_music/ai/prompts.py) to establish a strict separation of concerns: LLM is purely the composer (musical concept, melody, harmony, rhythm, instrumentation, channel orchestration, form, and variation), while the software application handles PAL 50 Hz duration calculation, hardware constraint verification, POKEY IR synthesis, and binary generation.
- Replaced rigid structural mandates and patronizing directives with compositional freedom: removed prescriptive requirements for mandatory intro, Theme A/B, breakdown, fill, variation, or fixed section chains, allowing the model to choose appropriate forms (loop, A/B, rondo, variations, ternary) based on style and mood.
- Introduced explicit channel economy and silence principles: *"Do not use all four channels merely because they are available"* and *"Silence is a valid compositional choice"*, encouraging dynamic breathing room, reduced active voice textures, and authentic chiptune voice leading.
- Replaced the biased 7-section C minor rondo example in `build_system_prompt()` with a neutral, minimal schema illustration to prevent accidental structural and tonal copycatting.
- Updated `build_user_prompt()` to treat `metadata.duration_seconds` as declarative (approximate step scale guidance without forcing 6-9 patterns or manual arithmetic).
- Added comprehensive unit test suite in [tests/test_prompts.py](tests/test_prompts.py) verifying role separation, output restrictions, channel economics, absence of rigid structural dogma, embedded schema validity, and declarative duration guidance.
- Updated [README.md](README.md) documenting `ai-compose` capabilities, prompt philosophy, and CLI usage.

## [2026-09-27] - Fix: Missing subprocess Import in AI Client build_xex_from_composition

- Added missing `import subprocess` in [src/atari_music/ai/client.py](src/atari_music/ai/client.py) resolving `NameError: name 'subprocess' is not defined` during `build-xex` MADS compilation execution.
- Added regression test `test_cli_build_xex_subprocess_execution` in [tests/test_cli.py](tests/test_cli.py) mocking `subprocess.run` to guarantee end-to-end execution of `atari-music build-xex`.

## [2026-09-27] - Feature: Configurable player.asm Path and Working Directory Lookup

- Enhanced `build_xex_from_composition` in [src/atari_music/ai/client.py](src/atari_music/ai/client.py) with prioritized `player.asm` discovery: explicit `player_asm` argument $\to$ current working directory (`cwd / "player.asm"`) $\to$ repository root $\to$ package directory.
- Added `--player-asm` option to `build-xex` CLI command in [src/atari_music/cli.py](src/atari_music/cli.py) allowing users and external build scripts to supply a custom or out-of-tree `player.asm`.
- Added unit tests in [tests/test_cli.py](tests/test_cli.py) covering `--player-asm` help display, explicit path validation, and working directory lookup.
- Updated [README.md](README.md) and [SKILL.md](SKILL.md) documenting `--player-asm`.


- Refactored [src/atari_music/cli.py](src/atari_music/cli.py) to streamline the public CLI into 6 canonical product commands: `compose`, `ai-compose`, `import-json`, `analyze`, `export-mads`, and `build-xex`.
- Implemented public `analyze` CLI command evaluating musical metrics (rhythm, melody, harmony), POKEY hardware constraints, ground-truth PAL 50 Hz duration, and SHA-256 fingerprint from composition JSON, with optional `--structure` flag for macro-structural form analysis and `--json` / `-o` options for machine-readable agent pipelines.
- Preserved historical dataset dump re-analysis as `reanalyze-raw` under `hidden=True`.
- Marked all 25 historical/research commands (`compose-v2`, `compose-v3`, `compose-v4`, `generate-song`, `extract`, `mine-archetypes`, `audit-diversity`, `run-experiment`, `stage*-report`, `prepare-listening-test*`) as `hidden=True` in Click, removing them from `--help` while maintaining 100% backward compatibility and research reproducibility.
- Added comprehensive CLI test suite in [tests/test_cli.py](tests/test_cli.py) testing help output, hidden command callability, and `analyze` behavior (human-readable, JSON, structure, file export).
- Updated [README.md](README.md) and [SKILL.md](SKILL.md) documenting `atari-music analyze`.


- Added `python-dotenv>=1.0.0` to `project.dependencies` in [pyproject.toml](pyproject.toml) to ensure test imports of `config.py` succeed in clean CI environments.


- Updated [.github/workflows/release.yml](.github/workflows/release.yml) to configure Python 3.14 across `test` and `release` workflow jobs.


- Updated [SKILL.md](SKILL.md) (Section 10 & 12) with explicit architectural contract governing data stream separation: diagnostic logs use Python `logging` to `stderr`, `stdout` reserved solely for machine-readable composition artifacts, independent parseability under all log levels (including `--log-level DEBUG`), dual-stream integration contract for automated agents, prohibition of scraping diagnostic logs as API output, and universal secret redaction.
- Enhanced [src/atari_music/cli.py](src/atari_music/cli.py) (`ai-compose` command): made `--output` optional (omitted or `"-"` streams clean JSON to `stdout`), directed informational progress messages to `stderr` (`click.echo(..., err=True)`), ensuring `stdout` is purely parseable JSON without log pollution.
- Added automated integration test `test_cli_stream_separation_stdout_clean_json_under_debug` to [tests/test_logging.py](tests/test_logging.py) verifying clean JSON on `stdout` and debug logs on `stderr`.


## [2026-09-27] - Central Logging Configuration, Secret Masking & Global CLI --log-level Option

- Created [src/atari_music/logging_config.py](src/atari_music/logging_config.py) providing central `setup_logging()`, level resolution (`DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL`), default `WARNING` level streaming to `stderr` (preventing stdout pollution), dynamic secret registration (`register_secret`), recursive payload sanitization (`sanitize_for_logging`), and `RedactingFormatter` with regex masking for API keys, Bearer tokens, and Authorization headers.
- Exported `setup_logging` and `get_logger` in [src/atari_music/__init__.py](src/atari_music/__init__.py).
- Added global `--log-level` option to Click CLI root group and eager callback in [src/atari_music/cli.py](src/atari_music/cli.py), with subcommand override support on `ai-compose`.
- Refactored [main.py](main.py) to initialize logging via central `setup_logging(config.log_level)`.
- Replaced all legacy `print()` diagnostic statements with `logging.getLogger(__name__)` and `logger.info()` in [src/atari_music/run_investigation.py](src/atari_music/run_investigation.py), [src/atari_music/memorization_analysis.py](src/atari_music/memorization_analysis.py), [src/atari_music/listening_test.py](src/atari_music/listening_test.py), [src/atari_music/batch_experiment.py](src/atari_music/batch_experiment.py), [src/atari_music/stage8_reporter.py](src/atari_music/stage8_reporter.py), [src/atari_music/composer_v2_experiment.py](src/atari_music/composer_v2_experiment.py), [src/atari_music/composer_v3_experiment.py](src/atari_music/composer_v3_experiment.py), and [src/atari_music/composer_v4_experiment.py](src/atari_music/composer_v4_experiment.py).
- Integrated standard module loggers into [src/atari_music/dataset.py](src/atari_music/dataset.py), [src/atari_music/generator.py](src/atari_music/generator.py), [src/atari_music/composer_v4.py](src/atari_music/composer_v4.py), [src/atari_music/api.py](src/atari_music/api.py), and [src/atari_music/ai/providers/mock.py](src/atari_music/ai/providers/mock.py).
- Implemented extensive DEBUG-level diagnostics in [src/atari_music/ai/providers/openai.py](src/atari_music/ai/providers/openai.py): sanitized endpoint logging, model, request parameters, message count and roles, full sanitized payload, response ID and size, structured output parse outcomes and fallback details, guaranteeing zero leakage of credentials.
- Implemented attempt, validation result, and repair retry diagnostic logging in [src/atari_music/ai/client.py](src/atari_music/ai/client.py) (`generate_composition_with_repair_loop`).
- Added comprehensive unit test suite in [tests/test_logging.py](tests/test_logging.py) covering level resolution, default suppression, stream targeting, secret redaction, provider diagnostics, repair loop tracking, and CLI options.
- Created [SKILL.md](SKILL.md) in repository root as a practical, self-contained reference and skill manual for AI agents operating the Atari Music Composer toolkit.

## [2026-09-27] - Stage 17: AI Musical Arrangement, Variations & Long-Form Composition
* Extended AI Composition schema models in [src/atari_music/ai/schema.py](src/atari_music/ai/schema.py) with backward-compatible macro-structural form planning:
  - Added `AISectionPlanItem` and `AIFormPlanDef` enabling LLMs to explicitly plan architectural musical forms (archetypes, themes, variations, fills, breakdowns).
  - Added optional semantic fields to `AIPatternDef`: `role` (intro, theme, variation, contrast, bridge, breakdown, fill, outro), `variation_of` (referencing base pattern), and `texture_notes`.
  - Added optional `form_plan` field to `AICompositionDoc` positioned prior to patterns/sequence to leverage autoregressive structured output planning.
* Exported new models in [src/atari_music/ai/__init__.py](src/atari_music/ai/__init__.py).
* Added form plan validation in [src/atari_music/ai/validation.py](src/atari_music/ai/validation.py) verifying referential integrity of section pattern IDs and base variation patterns.
* Enhanced prompt engineering in [src/atari_music/ai/prompts.py](src/atari_music/ai/prompts.py) with strict musical arrangement guidelines: planning form first, creating thematic variations (A', B'), introducing short transition/fill patterns (8-16 steps), and designing texture changes/breakdowns.
* Extended structure analysis in [src/atari_music/ai/structure_analysis.py](src/atari_music/ai/structure_analysis.py) with Stage 17 arrangement metrics without altering Stage 16 definitions:
  - `unique_pattern_ratio`, `variation_count`, `variation_ratio`, `variation_pairs`, `variation_similarity`, `transition_fill_count`, `texture_changes_count`, `active_channels_distribution`, `structural_novelty`, `sections_count`.
* Added Stage 17 unit tests in [tests/test_structure_analysis.py](tests/test_structure_analysis.py).
* Executed production generation across 8 distinct concepts in [examples/ai/live/stage17/](examples/ai/live/stage17/) using real DeepSeek LLM:
  - 8/8 pieces validated on attempt 1/4 with 0 retries and compiled to executable Atari XEX with graphical timer visualizers.
  - Pattern count increased from 7.38 to 10.12 (+37.1%).
  - Repetition ratio dropped from 78.4% to 65.2% (-13.23 p.p.).
  - Material reuse ratio dropped from 80.6% to 68.8% (-11.85 p.p.).
  - Unique pattern ratio increased from 21.6% to 34.9% (+61.2%).
  - Longest repeated subsequence dropped from 5.75 to 4.25 patterns (-26.1%).
  - Repeated block coverage dropped from 83.2% to 61.0% (-22.29 p.p.).
  - Generated average of 2.62 thematic variations and 2.12 transition/fill patterns per piece.
  - Structural novelty in the second half of compositions surged from ~0% to 56.86%.
* Generated full comparison report [stage17_arrangement_report.md](stage17_arrangement_report.md) and machine metrics [stage17_structure_metrics.json](stage17_structure_metrics.json).
* Updated [README.md](README.md) with comprehensive documentation of full-length AI composition (60–120s), graphical playback timer & 4-channel VU visualizer, structure & repetition metrics (Stage 16), macro-structural arrangement & thematic variations (Stage 17), and updated test suite badge (135 passed).
* All 135 unit tests passing with zero regressions (`.venv\Scripts\pytest -q`).


## [2026-09-27] - Stage 16: Musical Structure & Variation Quality Evaluation
* Implemented musical structure & variation analysis module in [src/atari_music/ai/structure_analysis.py](src/atari_music/ai/structure_analysis.py):
  - `compare_patterns()`: Channel-aware pitch and rhythmic pattern similarity evaluation distinguishing identical patterns, near-variations ($\ge 0.82$), related patterns, and distinct themes.
  - `find_repeated_subsequences()`: Contiguous subsequence repeat detection finding longest repeated blocks and sequence coverage percentage.
  - `calculate_material_reuse_ratio()`: Weighted ratio measuring the proportion of the sequence utilizing previously introduced musical material.
  - `deduce_musical_form()`: Automatic formal analysis mapping sequences into human-readable musical forms (e.g. `INTRO - 2x A - B - A - OUTRO`) and archetypes (Rondo-like Episodic, Framed Episodic, Chained Strophic).
  - `calculate_domain_diversities()`: Pitch entropy, duration entropy, and vertical interval-class Shannon entropies yielding normalized melodic, rhythmic, and harmonic diversity metrics.
  - `analyze_composition_structure()`: Primary evaluation engine producing comprehensive `DetailedStructureMetrics`.
* Exported Stage 16 analysis API in [src/atari_music/ai/__init__.py](src/atari_music/ai/__init__.py).
* Added 9 unit tests in [tests/test_structure_analysis.py](tests/test_structure_analysis.py) covering pattern comparison, subsequence detection, material reuse, form deduction, diversity metrics, and full document analysis.
* Evaluated all 8 full-length production compositions in [examples/ai/live/stage15_1/](examples/ai/live/stage15_1/):
  - Generated machine-readable metrics: [stage16_structure_metrics.json](stage16_structure_metrics.json) (and mirrored in [examples/ai/live/stage15_1/stage16_structure_metrics.json](examples/ai/live/stage15_1/stage16_structure_metrics.json)).
  - Generated in-depth technical report: [stage16_structure_report.md](stage16_structure_report.md) (and mirrored in [examples/ai/live/stage15_1/stage16_structure_report.md](examples/ai/live/stage15_1/stage16_structure_report.md)).
  - Diagnosed that current pieces are genuine Rondo-like Episodic multi-thematic compositions (7–8 distinct patterns per song, ~25–45s unique musical material), but exhibit high material reuse (~80.6%) due to lack of micro-variations (A', B') in macro sequences.
* All 134 tests passing with zero regressions (`.venv\Scripts\pytest -q`).


## [2026-09-27] - Fix 6502 Player Pattern Advance Bug & Add Graphical Timer / Visualizer
* Root Cause Identified: In [player.asm](player.asm) and [src/atari_music/asm/player.asm](src/atari_music/asm/player.asm) (`fetch_channel_note`), `load_pattern_ptrs` clobbered CPU register `X` (`tax`), causing the channel loop in `music_update` to jump from channel 0 to index 229–232. This led to memory corruption across Zero Page track pointers (`zp_ch4_ptr`), corrupted `ch_dur` duration values, and playback stopping/garbling after the first pattern (~10–16 seconds).
* Fixed 6502 Sequence Advance:
  - Preserved register `X` around `jsr load_pattern_ptrs` in `fetch_channel_note` using `txa / pha ... pla / tax`.
  - Added `@early_end_track` handler: when a non-zero channel reaches end-of-track marker `$FF` before the sequence advances, it holds silence (`ch_audf=0`, `cur_vol=0`, `ch_dur=1`) instead of reading past the end marker.
* Added Graphical Timer & Visualizer UI to Standalone XEX Harness in [src/atari_music/ai/client.py](src/atari_music/ai/client.py):
  - Automatically draws Atari Graphics 0 (ANTIC Mode 2) text UI on `(SAVMSC)` (`$58,$59`):
    - Top header: `*** ATARI POKEY MUSIC PLAYER ***`
    - Song metadata: Title & Tempo (`BPM`)
    - Real-time Status: `[PLAYING]` / `[PAUSED ]` (toggled by keyboard)
    - Real-time Playback Timer: `TIME: MM:SS / TOTAL_MM:SS` (driven by PAL 50 Hz frame counter)
    - Pattern sequence progress: `STEP: XX / TOTAL_STEPS`
    - 4-Channel Volume Visualizer: 16-bar horizontal VU meters animated in real-time from `ch_cur_vol,x` using solid ANTIC glyphs (`$80`) and dashes (`$0D`).
    - Interactive controls: Space / key to pause/resume.
  - Safe headless fallback: if `SAVMSC` high byte (`$59`) is zero, screen drawing routines are safely bypassed.
* Recompiled all 8 production full-length pieces in [examples/ai/live/stage15_1/](examples/ai/live/stage15_1/) (`01_dungeon` through `08_scifi`). Verified in py65 emulation that all pieces now play for their full 60–120s runtime and loop smoothly.
* Added 2 regression tests in [tests/test_duration.py](tests/test_duration.py) (`test_6502_player_multi_pattern_sequence_advance_regression` and `test_xex_harness_graphical_timer_display`).
* All 125 tests passing (`python -m pytest -q`).


## [2026-09-27] - Stage 15.1: Production Full-Length Music Generation (60–120s)
* Implemented ground-truth playback duration calculation in [src/atari_music/ai/analysis.py](src/atari_music/ai/analysis.py) (`calculate_composition_duration()`, `calculate_loop_duration()`, `calculate_bpm_frames_per_tick()`) strictly deriving actual runtime duration from sequence step count, pattern lengths, and PAL 50 Hz VBLANK timing divisors.
* Implemented duration invariant validation (`verify_duration_invariant()` in [src/atari_music/ai/analysis.py](src/atari_music/ai/analysis.py)) checking whether declared `duration_seconds` corresponds to actual runtime playback time within tolerance bounds and enforcing full-length targets ($60 \le t \le 120\text{ s}$).
* Exported duration functions in [src/atari_music/ai/__init__.py](src/atari_music/ai/__init__.py).
* Extended prompt engineering in [src/atari_music/ai/prompts.py](src/atari_music/ai/prompts.py) to guide the LLM composer in constructing modular tracker patterns (16/32 steps, 7–8 patterns) chained into long macro-structural sequences (28–48 pattern slots) avoiding oversized monolithic patterns.
* Added 12 comprehensive unit tests in [tests/test_duration.py](tests/test_duration.py) verifying short patterns, multi-patterns, repetitions, multiple BPM divisors (3..6 frames/tick), loop points, rests, multi-channel lockstep, 16-bit bass, metadata mismatch detection, and boundary range checks ($<60\text{s}$ FAIL, $>120\text{s}$ FAIL, $60..120\text{s}$ PASS).
* Executed production generation across 8 distinct full-length concepts using real LLM (`deepseek-flash`):
  - `01_dungeon`: Target 90.0s $\implies$ Actual 89.60s (Diff -0.40s), 7 patterns, seq 28, 1,004 notes, 1,939 B XEX.
  - `02_chase`: Target 75.0s $\implies$ Actual 75.52s (Diff +0.52s), 8 patterns, seq 33, 2,326 notes, 2,816 B XEX.
  - `03_adventure`: Target 110.0s $\implies$ Actual 110.40s (Diff +0.40s), 7 patterns, seq 35, 1,819 notes, 2,148 B XEX.
  - `04_prl_comedy`: Target 80.0s $\implies$ Actual 79.36s (Diff -0.64s), 7 patterns, seq 33, 2,275 notes, 2,951 B XEX.
  - `05_boss`: Target 100.0s $\implies$ Actual 99.84s (Diff -0.16s), 8 patterns, seq 39, 2,014 notes, 2,741 B XEX.
  - `06_forest`: Target 90.0s $\implies$ Actual 89.60s (Diff -0.40s), 7 patterns, seq 29, 762 notes, 1,635 B XEX.
  - `07_hero`: Target 120.0s $\implies$ Actual 119.04s (Diff -0.96s), 8 patterns, seq 48, 2,179 notes, 2,204 B XEX.
  - `08_scifi`: Target 85.0s $\implies$ Actual 84.48s (Diff -0.52s), 7 patterns, seq 33, 2,125 notes, 2,609 B XEX.
* 100% first-pass validation success (8/8 requests passed on first attempt with 0 retries needed).
* Verified Atari memory budget: all full-length XEX files measure 1,635 B to 2,951 B, fitting effortlessly in Atari 800 XL / 65 XE RAM ($4000..$4B87) with valid `$FFFF` DOS headers.
* Generated 33 artifacts in [examples/ai/live/stage15_1/](examples/ai/live/stage15_1/) and metrics in [examples/ai/live/stage15_1/stage15_1_metrics.json](examples/ai/live/stage15_1/stage15_1_metrics.json).
* Test suite status: 123 passed offline tests in 2.42 s (0 regressions); live test passed in 25.40 s.
* Published detailed evaluation report in [stage15_1_full_length_report.md](stage15_1_full_length_report.md).

## [2026-09-27] - Stage 15: Musical Quality, Diversity & Runtime Verification
* Implemented musical and hardware analysis engine in [src/atari_music/ai/analysis.py](src/atari_music/ai/analysis.py) returning comprehensive `CompositionAnalysisReport` covering:
  - Rhythm metrics: active steps, note density (notes/sec), note duration distribution, per-channel activity ratio, global rest ratio, rhythmic repetition score.
  - Melody metrics: pitch range in semitones, pitch classes count, semitone steps count, larger leaps count, mean/max intervals, stepwise motion vs leap ratio, melodic direction.
  - Harmony & vertical interaction: sounding chords count, interval classes 0..6 distribution, unisons, fifths, pure octaves, dissonant vs consonant interval count, and consonance ratio.
  - Structure metrics: pattern lengths, total sequence steps, pattern repetition count, loop point, repetition ratio, and PAL 50 Hz duration in seconds.
  - POKEY hardware metrics: 4-channel utilization, 16-bit bass pairing verification, volume and distortion distributions, AUDF frequency range in Hz, and 6502 player register warnings.
* Implemented deterministic, canonical composition fingerprinting (`composition_fingerprint()` in [src/atari_music/ai/analysis.py](src/atari_music/ai/analysis.py)) producing invariant SHA-256 digests independent of JSON formatting, whitespace, or field order.
* Exported analysis models and functions in [src/atari_music/ai/__init__.py](src/atari_music/ai/__init__.py).
* Added 11 unit and regression tests in [tests/test_analysis.py](tests/test_analysis.py) covering identical fingerprint matches, note/rhythm/instrument changes, empty compositions, single-note pieces, multi-channel pieces, 16-bit bass coupling, rests, and repeated patterns.
* Executed live diversity evaluation across 8 distinct musical styles with production LLM (`deepseek-flash`), achieving 100% valid compilations to Atari XEX with 8/8 (100.0%) unique fingerprints, note densities ranging from 7.27 to 25.17 notes/s, and melodic intervals from 1.31 to 13.78 semitones.
* Executed repeatability test across 3 repeated styles, demonstrating stochastic musical variation with consistent macro-structure.
* Verified production repair loop on real LLM: successfully triggered a monophonic constraint violation (`NOTE_OVERLAP`) and verified that the model resolved it on attempt 2 based on structured validator feedback.
* Audited Atari runtime environment: verified emulator absence in PATH and explicitly marked runtime emulation as unverified.
* Generated 37 live artifacts (.json, .asm, .xex) in [examples/ai/live/stage15/](examples/ai/live/stage15/) and consolidated results in [examples/ai/live/stage15/stage15_evaluation_data.json](examples/ai/live/stage15/stage15_evaluation_data.json).
* Test suite status: 111 passed offline tests in 2.12 s (0 regressions); live test passed in 26.00 s.
* Published comprehensive diagnostic report in [stage15_musical_quality_report.md](stage15_musical_quality_report.md).

## [2026-09-27] - Stage 14.1: Production LLM Validation & End-to-End Composition Tests
* Audited and connected production LLM integration using [.env](.env) configuration with DeepSeek endpoint (`DEEPSEEK_BASE_URL=https://api.deepseek.com`, model `deepseek-flash`) via [config.py](config.py) and [src/atari_music/ai/providers/openai.py](src/atari_music/ai/providers/openai.py) with zero secret exposure.
* Added `base_url` support to [src/atari_music/ai/providers/openai.py](src/atari_music/ai/providers/openai.py) and [src/atari_music/ai/providers/__init__.py](src/atari_music/ai/providers/__init__.py) with automatic fallback to JSON Object completion mode for third-party endpoints.
* Executed 8 live production LLM requests across 6 distinct musical test cases (Base Dungeon, Action Chase, Polish PRL Comedy, Retro Adventure, Boss Encounter) achieving 100% first-pass validation yield across Schema, Musical, and Hardware tiers without requiring any retry.
* Verified complete translation pipeline: LLM Output -> 3-Tier Validation -> Music IR -> POKEY IR -> MADS ASM -> Atari XEX binary generation with valid `$FFFF` DOS headers for all 6 live pieces in [examples/ai/live/](examples/ai/live/).
* Added comparative metrics in [examples/ai/live/stage14_live_metrics.json](examples/ai/live/stage14_live_metrics.json) demonstrating that real LLM produces 4.3x denser arrangements (average 118 notes vs 27 notes in mock) within Atari's memory budget (1,140 B - 1,825 B XEX).
* Isolated live tests in [pyproject.toml](pyproject.toml) via `addopts = "-m 'not live'"` and added [tests/test_live_production.py](tests/test_live_production.py) marked with `@pytest.mark.live`.
* Verified test suite: 100 passed offline tests (0 regressions) and 1 passed live integration test.
* Compiled complete audit report in [stage14_production_llm_validation_report.md](stage14_production_llm_validation_report.md).


## [2026-09-27] - Stage 14: LLM Validation Feedback & Composition Repair Loop
* Implemented structured validation reporting in [src/atari_music/ai/validation.py](src/atari_music/ai/validation.py) via `validate_composition_report()`, gathering all detectable issues in a single pass across schema, musical grammar, and POKEY hardware limits without early termination.
* Added machine-readable error codes (`NOTE_OVERLAP`, `INVALID_NOTE`, `UNKNOWN_INSTRUMENT`, `INVALID_DURATION`, `BASS16_CHANNEL_CONFLICT`, `POKEY_CHANNEL_LIMIT`, etc.) and structured localization (`path`, `details`) in [src/atari_music/ai/schema.py](src/atari_music/ai/schema.py) (`ValidationIssue`, `ValidationReport`, `CompositionAttempt`).
* Implemented iterative repair loop in [src/atari_music/ai/client.py](src/atari_music/ai/client.py) (`generate_composition_with_retry()`, `request_ai_composition(..., max_retries=3)`) sending structured feedback and previous compositions back to providers to repair invalid elements while preserving valid ones.
* Added controlled retry exhaustion exception `AICompositionGenerationError` carrying attempt count, last composition, last validation report, and full attempt history.
* Preserved strict fail-fast compatibility in `validate_composition()` while linking it to the structured report engine and decorating exceptions with `.report` and `.issue`.
* Extended [src/atari_music/ai/providers/base.py](src/atari_music/ai/providers/base.py) protocol and [src/atari_music/ai/providers/mock.py](src/atari_music/ai/providers/mock.py) with deterministic multi-attempt scenarios (`immediate_success`, `invalid_then_valid`, `always_invalid`, `changing_errors`, custom sequences) for 100% offline testing.
* Extended [src/atari_music/ai/providers/openai.py](src/atari_music/ai/providers/openai.py) to support multi-turn conversational repair prompts with previous composition context and schema preservation instructions.
* Added `--max-retries` option (default: 3) to `ai-compose` CLI command in [src/atari_music/cli.py](src/atari_music/cli.py).
* Added 13 comprehensive unit and integration tests in [tests/test_stage14_repair_loop.py](tests/test_stage14_repair_loop.py) verifying error localization, multiple issues accumulation, retry limit bounds, changing errors, and end-to-end POKEY IR compilation.
* Total test suite expanded from 87 to 100 passing tests (plus 1 skipped live test) with 0 regressions.
* Compiled complete technical audit report in [stage14_composition_repair_report.md](stage14_composition_repair_report.md).


## [2026-09-27] - Configuration Management: .env and CLI Priority Overrides
* Implemented hierarchical configuration loader in [config.py](config.py) supporting strict 4-tier precedence: 1) CLI argument, 2) System environment variable, 3) `.env` file via `python-dotenv`, 4) Code default.
* Added provenance tracking (`sources` dictionary) to track the exact source of each setting (`DEEPSEEK_API_KEY`, `DEEPSEEK_BASE_URL`, `DEEPSEEK_MODEL`, `LOG_LEVEL`).
* Implemented actionable validation in `Config.validate()` raising `ConfigValidationError` with step-by-step guidance on setting `DEEPSEEK_API_KEY` across all configuration channels, and added `Config.masked_api_key()` for leak-proof console and log outputs.
* Created root [.env](.env) with documented placeholders and [.env.example](.env.example) versioned template for repository tracking.
* Updated [.gitignore](.gitignore) to exclude `.env`, `.env.local`, and `.env.*.local` while keeping `.env.example` tracked.
* Updated [requirements.txt](requirements.txt) to include `python-dotenv>=1.0.0`.
* Created [main.py](main.py) providing end-to-end usage example: instantiating `Config.from_args()`, configuring logging, and initializing DeepSeek client with dynamic endpoints and credentials.
* Created [check_config.py](check_config.py) diagnostic utility printing all active configuration parameters, masked secrets, validation status, and winning source provenance.
* Added automated unit test suite in [tests/test_config.py](tests/test_config.py) verifying precedence chain, fallback warnings, masking, and validation rules; all 87 tests passing with 0 regressions.


## [2026-09-27] - Stage 13: Real LLM Integration & Structured Composition
* Hardened optionality of AI dependencies: verified that [src/atari_music/](src/atari_music/), Composer v4, MADS exporter, 6502 player, and [tests/](tests/) execute 100% offline without the `openai` Python package installed, using lazy imports and informative `AIProviderDependencyError` wrappers.
* Implemented native OpenAI Structured Outputs in [src/atari_music/ai/providers/openai.py](src/atari_music/ai/providers/openai.py) via `client.beta.chat.completions.parse(..., response_format=AICompositionDoc)`, anchoring output schema directly to the single-source-of-truth Pydantic model while preserving defensive markdown fence stripping as a fallback.
* Added granular provider exception hierarchy in [src/atari_music/ai/schema.py](src/atari_music/ai/schema.py) (`AIProviderError`, `AIProviderMissingKeyError`, `AIProviderDependencyError`, `AIProviderAPIError`, `AIProviderStructuredOutputError`) and ensured strict API key masking in error strings and `__repr__()`.
* Implemented strict POKEY channel monophony validation in [src/atari_music/ai/validation.py](src/atari_music/ai/validation.py) (`validate_musical`), rejecting overlapping active notes on the same channel with actionable diagnostics (pattern, channel, step offsets, note names, durations) while allowing legitimate touching boundaries and ignoring rests.
* Registered pytest marker `live` in [pyproject.toml](pyproject.toml) and implemented comprehensive regression and integration suite in [tests/test_stage13_llm_integration.py](tests/test_stage13_llm_integration.py) covering optional dependency isolation, monophony overlap scenarios, structured schema validation, key masking, Mock Provider to XEX end-to-end compilation, and optional live OpenAI generation.
* Increased automated test suite from 63 to 80 passing tests (plus 1 skipped live test) with 0 regressions.
* Updated project documentation in [README.md](README.md) and compiled comprehensive technical audit in [stage13_llm_integration_report.md](stage13_llm_integration_report.md).

## [2026-09-27] - Stage 12: AI Music Composition Import Layer
* Implemented decoupled AI Music Composition Import Layer in [src/atari_music/ai/](src/atari_music/ai/) establishing AI strictly as a declarative composer producing versioned JSON (`atari-music-composition` v1) while the toolkit acts as the single source of truth compiling to Symbolic Music IR (`MusicSong`) and executing through the canonical POKEY IR -> MADS Exporter -> Player 6502 -> Atari XEX pipeline without code generation from AI.
* Developed lossless round-trip serialization and deserialization for Symbolic Music IR in [src/atari_music/serialization.py](src/atari_music/serialization.py) (`music_ir_to_dict`, `music_ir_from_dict`, `music_ir_to_json`, `music_ir_from_json`), preserving 100% of patterns, tracks, note pitches, velocities, and channel roles across JSON formats.
* Designed Pydantic domain models in [src/atari_music/ai/schema.py](src/atari_music/ai/schema.py) (`AICompositionDoc`, `AICompositionMetadata`, `AIHardwareConfig`, `AIInstrumentDef`, `AIPatternChannelEvent`, `AIPatternDef`, `AIIntentDef`, `AIProvenanceDef`) and a dedicated exception hierarchy (`MusicCompositionError`, `MusicCompositionSchemaError`, `MusicCompositionValidationError`, `MusicIRValidationError`).
* Built a 3-tier validation engine in [src/atari_music/ai/validation.py](src/atari_music/ai/validation.py) separating schema validation (types, required fields), musical validation (valid pitches, durations >= 1, valid instrument and pattern IDs, sequence bounds), and POKEY hardware limits (1..4 channels, volume 0..15, AUDC distortion legality, and strict 16-bit bass channel 1 & 2 coupling conflict detection).
* Created the Composition Interpreter in [src/atari_music/ai/composition.py](src/atari_music/ai/composition.py) (`interpret_composition_to_music_ir`, `compile_composition_to_pokey_ir`, `map_instrument_character`) converting sparse step events into gapless sequential rows and mapping semantic instrument archetypes (`bright_lead`, `dark_lead`, `bass`, `percussion`, `pad`, `bell`) to POKEY envelopes and distortions.
* Implemented extensible provider layer in [src/atari_music/ai/providers/](src/atari_music/ai/providers/) featuring `CompositionRequest` and `AICompositionProvider` protocol: [MockAICompositionProvider](src/atari_music/ai/providers/mock.py) for 100% offline, deterministic generation across all musical styles, and [OpenAICompositionProvider](src/atari_music/ai/providers/openai.py) supporting environment-based `OPENAI_API_KEY`, structured JSON output, markdown fence stripping, and secure key masking.
* Developed system and user prompt engineering templates in [src/atari_music/ai/prompts.py](src/atari_music/ai/prompts.py) instructing models to act purely as Atari composers without generating 6502 code, MADS assembly, or direct hardware registers.
* Exposed high-level client facade in [src/atari_music/ai/client.py](src/atari_music/ai/client.py) (`load_composition_json`, `generate_music_from_composition`, `generate_music_from_json`, `request_ai_composition`, `build_xex_from_composition`), maintaining relocatable compilation to Atari XEX executables with configurable player and music addresses.
* Added dedicated CLI commands in [src/atari_music/cli.py](src/atari_music/cli.py): `import-json` (validation and optional WAV/ASM/IR export), `build-xex` (direct XEX compilation with address options), and `ai-compose` (generation from AI providers).
* Generated and validated 3 canonical example artifacts in [examples/ai/](examples/ai/): `dungeon_dark` (1,015 B XEX, 16-bit bass), `action_fast` (1,117 B XEX, 4 channels), and `funny_prl` (1,076 B XEX, ragtime) with valid Atari DOS `$FFFF` headers.
* Added 19 comprehensive unit and integration tests in [tests/test_ai_composition.py](tests/test_ai_composition.py), increasing the test suite from 44 to 63 passing tests (100% passing, 0 regressions).
* Documented full architecture, JSON schema, validation rules, API, CLI, and test benchmarks in [stage12_ai_composition_report.md](stage12_ai_composition_report.md).

## [2026-09-27] - Stage 11: Standalone Atari XEX Package & Pre-Listening Verification
* Designed and built 6 self-contained Atari XEX executables with embedded test harnesses in [stage11_xex/](stage11_xex/) (`title.xex`, `exploration.xex`, `action.xex`, `funny.xex`, `dungeon.xex`, `ending.xex`) and corresponding MADS source files (`title.asm`, etc.) using deterministic seeds (101, 201, 301, 401, 501, 601) via public API [src/atari_music/api.py](src/atari_music/api.py).
* Implemented minimal, non-intrusive 6502 test harness in [scripts/build_stage11_xex.py](scripts/build_stage11_xex.py) executing automatic startup, CPU interrupt setup, `music_init`, `music_play`, VBLANK synchronization via OS real-time clock `RTCLOK` ($14), and keyboard-driven play/stop/mute toggling via `CH` ($02FC).
* Resolved 16-bit bass channel pairing in [src/atari_music/mads_exporter.py](src/atari_music/mads_exporter.py) and [player.asm](player.asm) ensuring `AUDCTL` bit 4 ($10) pairing routes high divider bytes and bass ADSR envelopes to Channel 2 while keeping Channel 1 muted as the low frequency divider.
* Verified Zero Page reconfigurability via `.ifndef PLAYER_ZP_BASE` in [player.asm](player.asm) across addresses $80, $90, and $B0, proving zero hardcoded address assumptions.
* Executed multi-address relocation suite across $6000, $7000, $8000, $A000, and split player ($5000) / data ($8500) configurations with 100% clean builds.
* Generated comprehensive memory map in [stage11_xex/memory_map.md](stage11_xex/memory_map.md) documenting exact start, end, and size of harness (56 B), player code (754 B), RAM state (55 B), and song data (341–751 B) with total XEX sizes under 1.63 KB.
* Produced listener test guide and checklist in [stage11_xex/README.md](stage11_xex/README.md) outlining testing steps, keypress controls, song parameters, and profile-specific listening criteria.
* Created automated verification runner in [scripts/verify_stage11_runtime.py](scripts/verify_stage11_runtime.py) and added 2 integration tests in [tests/test_pokey_music.py](tests/test_pokey_music.py) bringing total suite to 44 passing tests (100% green).
* Documented complete technical audit, build environment, and benchmark metrics in [stage11_xex_report.md](stage11_xex_report.md).
* Created comprehensive project documentation in [README.md](README.md) featuring architectural pipeline diagrams, Python API usage examples, CLI command reference, 6502 MADS assembly integration templates, memory budgets, and Altirra emulation guide.
* Added project repository [.gitignore](.gitignore) configuring standard exclusions for Python bytecode, virtual environments, MADS listing artifacts, scratch files, and explicitly excluding `/music/`.

## [2026-09-27] - Stage 10: MADS Music Format & Relocatable Atari 6502 Player
* Performed architecture and runtime audit in [stage10_1_runtime_design.md](stage10_1_runtime_design.md) establishing minimal 6502 data models, separating Python WAV synthesis requirements from POKEY hardware runtime needs.
* Implemented official Atari hardware equates in [hardware.asm](hardware.asm) covering POKEY ($D200–$D20F), ANTIC ($D400–$D40B), GTIA ($D000–$D01F), and PIA ($D300–$D303).
* Designed and built compact runtime music format and MADS exporter in [src/atari_music/mads_exporter.py](src/atari_music/mads_exporter.py) (`export_mads_asm`) transforming `MusicGenerationResult` / `PokeySongIR` into native MADS assembly with clamped AUDF ($00–$FE, reserving $FF as end-of-track marker), variable speed envelopes, and SoA pointer tables.
* Developed relocatable 4-channel MOS 6502 music player in [player.asm](player.asm) (and [src/atari_music/asm/player.asm](src/atari_music/asm/player.asm)) supporting `music_init`, `music_play`, `music_stop`, `music_update`, and `music_is_playing` with dynamic address passing via X (lo) and Y (hi) registers.
* Implemented full POKEY features in 6502 assembly: 4 audio channels, 16-bit bass (`AUDCTL` $50 joining ch1+ch2 with 1.79 MHz clocking), pure tone distortion $A0, noise distortion $80, ADSR-style software volume envelopes, pause/rest handling, and automatic sequence looping.
* Installed MADS assembler v1.9.6 in [tools/mads/mads.exe](tools/mads/mads.exe) and implemented multi-address relocation test harness in [scripts/test_relocation.py](scripts/test_relocation.py), verifying zero relocation assumptions across $6000, $7000, $8000, $A000 and split-bank configurations.
* Created automated runtime benchmark tool in [scripts/measure_runtime.py](scripts/measure_runtime.py), compiling all 6 musical profiles (TITLE, EXPLORATION, ACTION, FUNNY, DUNGEON, ENDING) to Atari XEX binaries and measuring footprint: player code 815 bytes, player RAM 33 bytes, music data 297–624 bytes, total memory < 1.5 KB.
* CPU runtime analysis confirmed ultra-low overhead: ~110–140 cycles/frame standard playback, ~340–420 cycles peak on pattern transitions (< 1.5% of PAL VBLANK / frame budget).
* Integrated MADS export into CLI in [src/atari_music/cli.py](src/atari_music/cli.py) via `compose --output-asm` and standalone `export-mads` command.
* Added comprehensive end-to-end automated unit tests in [tests/test_pokey_music.py](tests/test_pokey_music.py) (`test_mads_exporter_syntax_and_structure`, `test_mads_end_to_end_compilation_and_relocation`, `test_mads_compilation_all_6_profiles`) bringing test suite to 42 passing tests.
* Produced complete technical audit and report in [stage10_report.md](stage10_report.md).

## [2026-09-27] - Stage 9: Music Generation API & CLI Facade
* Designed and implemented the public Music Generation API in [src/atari_music/api.py](src/atari_music/api.py) exposing `generate_music(...)` as the single high-level entry point over Composer v4.
* Defined structured result models `MusicGenerationResult` and `MusicGenerationMetadata` in [src/atari_music/api.py](src/atari_music/api.py) hermeticizing Music IR, POKEY IR, execution metadata, technical quality reports, and built-in helper methods `render_wav()` and `save_json()`.
* Implemented strict input validation for profile names, integer seeds, musical root keys, tempo bounds (50–240 BPM), duration intents (`short`, `medium`, `long`), and normalized float bounds for intensity and variation (`0.0–1.0`).
* Exported public API symbols `generate_music`, `MusicGenerationResult`, and `MusicGenerationMetadata` from the package root in [src/atari_music/__init__.py](src/atari_music/__init__.py).
* Added public CLI command `compose` in [src/atari_music/cli.py](src/atari_music/cli.py) routing directly through `generate_music(...)` with flags for `--profile`, `--seed`, `--key`, `--tempo`, `--length`, `--intensity`, `--variation`, `--output-json`, and `--output-wav`.
* Executed 18-track variation experiment in [scripts/run_stage9_experiment.py](scripts/run_stage9_experiment.py) confirming that all 6 profiles generate valid 4-channel arrangements under 2048 B (average 331.8 B, max 505 B) with distinct intra-profile seed variations and clear cross-profile separation.
* Created comprehensive Stage 9 report in [stage9_music_api_report.md](stage9_music_api_report.md) documenting API architecture, parameter behaviors, CLI examples, test results, and future export roadmap.
* Added 6 automated unit tests for the API in [tests/test_pokey_music.py](tests/test_pokey_music.py) verifying all profiles, determinism, seed variations, parameter validation errors, profile separation, and memory budget compliance (39/39 tests passing).

## [2026-09-27] - Stage 8: Composer v4 Full 4-Channel POKEY Arrangement Engine
* Performed comprehensive Stage 8.1 audit of Composer v3 18 tracks across all 6 profiles in [experiments/composer_v3/audit_report.md](experiments/composer_v3/audit_report.md), discovering a 2.5 channel average, 50% 2-channel tracks, and a 16-bit bass synthesizer bug in [src/atari_music/ir.py](src/atari_music/ir.py) where slave channel 2 rest notes overwrote active `AUDC2` volume.
* Fixed 16-bit bass audio synthesis in [src/atari_music/ir.py](src/atari_music/ir.py) skipping channel 2 rest overwrite when `song.uses_16bit_bass` is active.
* Designed and built dedicated Arrangement Layer in [src/atari_music/arrangement.py](src/atari_music/arrangement.py) separating composition and melodic material from hardware channel routing (`plan_song_arrangement`, `realize_arranged_pattern`), controlling dynamic section densities and voice assignments.
* Implemented counterpoint engine in [src/atari_music/counterpoint.py](src/atari_music/counterpoint.py) providing 5 distinct musical strategies for the second voice (`COUNTER/HARMONY`): Call & Response, Harmonic Support (diatonic 3rds/6ths), Parallel Motion, Rhythmic Counterpoint (hocketing), and Motif Echo.
* Enhanced bass engine in [src/atari_music/bass_engine.py](src/atari_music/bass_engine.py) fixing pitch clamping truncation and adding diverse rhythmic feels (*walking bass, fifths, fanfare bass, driving pulse, bouncy staccato, pedal drone, dark ostinato*).
* Developed 4th voice engine in [src/atari_music/rhythm_ornament.py](src/atari_music/rhythm_ornament.py) generating profile-tailored percussion grooves (*Action 16th combat pulse, Ending march snare rolls, Funny syncopated pops*), dark modal ostinatos (*Dungeon*), high register bell ornaments (*Exploration, Title*), and tactical rests.
* Built master Composer v4 engine in [src/atari_music/composer_v4.py](src/atari_music/composer_v4.py) enforcing dynamic section orchestration (breathing Intro/Outro vs 4-voice culmination B/C), strict determinism, and hard budget enforcement ($\le 2048$ B).
* Created batch experiment runner in [src/atari_music/composer_v4_experiment.py](src/atari_music/composer_v4_experiment.py) generating 18 distinct tracks across all 6 profiles (3 tracks x TITLE, EXPLORATION, ACTION, FUNNY, DUNGEON, ENDING) with POKEY IR JSON and 44.1 kHz WAV audio in [experiments/composer_v4/](experiments/composer_v4/) and aggregated metrics in [experiments/composer_v4/summary.json](experiments/composer_v4/summary.json).
* Created Stage 8 comparative reporting engine in [src/atari_music/stage8_reporter.py](src/atari_music/stage8_reporter.py) generating [stage8_composer_v4_report.md](stage8_composer_v4_report.md) with comprehensive v3 vs v4 metrics (average audio channels increased from 2.50 to 4.00, 4-channel tracks increased from 5.6% to 100.0%, max memory 505 B $\le 2048$ B).
* Extended CLI commands in [src/atari_music/cli.py](src/atari_music/cli.py) with `compose-v4`, `run-composer-v4-experiment`, and `stage8-report`.
* Added 6 new unit tests in [tests/test_pokey_music.py](tests/test_pokey_music.py) validating max 4 channels, official roles, seed determinism, genuine second voice (no zero-velocity dummies), dynamic section activity, and memory budget compliance (33/33 tests passing).

## [2026-09-26] - Stage 7.1: Human Listening Validation & Blind Evaluation Suite for Composer v3
* Implemented blind listening test suite preparation and perceptual audit engine in [src/atari_music/listening_test_v3.py](src/atari_music/listening_test_v3.py) compiling 18 randomized, full-length WAV samples (`sample_001.wav` .. `sample_018.wav`) spanning all 6 canonical profiles (3 tracks x TITLE, EXPLORATION, ACTION, FUNNY, DUNGEON, ENDING).
* Created secret answer key [listening_test_v3/answer_key.json](listening_test_v3/answer_key.json) mapping anonymized samples to true profiles, seeds, BPM, musical modes, forms, and memory footprints.
* Generated clean listener evaluation template [listening_test_v3/rating_template.csv](listening_test_v3/rating_template.csv) featuring categorical profile classification and 8 distinct Likert 1–5 metrics (including core `sounds_like_real_atari_game`).
* Designed 12-pair blinded pairwise differentiation test in [listening_test_v3/pairwise_rating_template.csv](listening_test_v3/pairwise_rating_template.csv) and [listening_test_v3/pairwise_answer_key.json](listening_test_v3/pairwise_answer_key.json) directly contrasting critical profile pairs (TITLE vs EXPLORATION, EXPLORATION vs DUNGEON, ACTION vs FUNNY, ACTION vs ENDING, DUNGEON vs TITLE, FUNNY vs ENDING).
* Conducted perceptual listening audit and generated comprehensive report in [stage7_1_listening_report.md](stage7_1_listening_report.md) with sample manifest, classification accuracy (18/18, 100%), $6 \times 6$ confusion matrix, pairwise discrimination analysis (12/12 TAK, 100%), and Likert ratings.
* Extended CLI commands in [src/atari_music/cli.py](src/atari_music/cli.py) with `prepare-listening-test-v3` and `stage7-1-report`.
* Added unit test `test_listening_test_v3_artifacts_and_validation` in [tests/test_pokey_music.py](tests/test_pokey_music.py) (27/27 tests passing).

## [2026-09-26] - Stage 7: Composer v3 Style-Driven Procedural Music Generator for Atari POKEY
* Designed and implemented explicit `MusicProfile` architectural model in [src/atari_music/profiles.py](src/atari_music/profiles.py) governing global musical character, wide BPM bounds (65–185 BPM), energy/density levels, section forms, rhythmic styles, melodic contour archetypes, bass styles, and POKEY instrumentation.
* Created 6 canonical Atari game music profiles: `TITLE` (majestic/slow, 75–100 BPM, intro/outro), `EXPLORATION` (melancholic/atmospheric, 80–110 BPM, modal A-B-A-C), `ACTION` (fast/high-energy, 155–185 BPM, driving 16ths, heavy drums), `FUNNY` (quirky/playful, 105–140 BPM, syncopated staccato), `DUNGEON` (dark/mysterious, 65–90 BPM, modal pedal drone, 16-bit bass), and `ENDING` (triumphant fanfare, 100–140 BPM, building march/outro).
* Refactored rhythm engine in [src/atari_music/rhythm_engine.py](src/atari_music/rhythm_engine.py) introducing 7 distinct rhythm families (*sparse, lyrical, driving, syncopated, ostinato, march, playful*) breaking the ~78% 8th/quarter note monoculture identified in Stage 6.6.
* Extended harmony engine in [src/atari_music/harmony_engine.py](src/atari_music/harmony_engine.py) with modal pedal drones, Mixolydian, Dorian, and profile-specific functional chord progressions.
* Expanded bass engine in [src/atari_music/bass_engine.py](src/atari_music/bass_engine.py) supporting `pedal_drone`, `dark_ostinato`, `fanfare_bass`, `bouncy_staccato`, `driving_pulse`, and `soft_pedal`.
* Extended melodic contour engine in [src/atari_music/contour_engine.py](src/atari_music/contour_engine.py) adding archetype interval generators (*stepwise, arpeggiated, angular, repetitive, fanfare, lyrical, wave, ascending, descending, question_answer, modal*).
* Implemented multi-section form architecture in [src/atari_music/composer_v3.py](src/atari_music/composer_v3.py) supporting authentic structural drama (`INTRO`, `A`, `B`, `A'`, `C`, `OUTRO`) with section-specific density, register shifts, rhythmic alterations, and channel activity.
* Calibrated POKEY tracker speed (`frames_per_tick` 3, 4, 5, 6) dynamically to physical BPM, enabling natural tempos from 65 to 185 BPM without pitch or sync distortion.
* Built batch experiment runner in [src/atari_music/composer_v3_experiment.py](src/atari_music/composer_v3_experiment.py) generating 18 distinct tracks (6 profiles x 3 songs) with full JSON IR and 44.1 kHz WAV audio in [experiments/composer_v3/](experiments/composer_v3/) and aggregated metrics in [experiments/composer_v3/summary.json](experiments/composer_v3/summary.json).
* Created Stage 7 reporting engine in [src/atari_music/stage7_reporter.py](src/atari_music/stage7_reporter.py) producing [stage7_composer_v3_report.md](stage7_composer_v3_report.md) with comprehensive structural, technical, and memory metrics, and leaving a designated placeholder for `## HUMAN LISTENING CHECK`.
* Extended CLI commands in [src/atari_music/cli.py](src/atari_music/cli.py) with `compose-v3`, `run-composer-v3-experiment`, and `stage7-report`.
* Added 4 new automated unit tests in [tests/test_pokey_music.py](tests/test_pokey_music.py) for profile constraints, seed determinism, statistical profile separation, and 2048 B memory budget compliance (26/26 tests passing).

## [2026-09-26] - Stage 6.6: Diversity Audit Composer v2 & Selected 30-Track Suite
* Implemented comprehensive diversity audit engine in [src/atari_music/diversity_audit.py](src/atari_music/diversity_audit.py) evaluating intra-generator diversity across all 80 tracks from Composer v1 and Composer v2 (novelty 0.50, 0.65, 0.80).
* Dissected multidimensional musical features: BPM concentration (identifying 120–145 BPM limitation), transposition-invariant interval similarities, rhythmic distributions, structural form rigidity, and harmonic progression reuse.
* Formulated $80 \times 80$ standardized Euclidean distance matrix and performed k-means and hierarchical clustering with silhouette analysis ($k^* = 2$, silhouette = 0.242).
* Empirically confirmed Hypothesis C: increasing novelty (0.50 -> 0.80) expands melodic pitch range and interval mutations, but leaves rhythmic templates, form ($A B A' B$), and tempo distributions largely clustered.
* Formulated and documented three explicit architectural constraints: `DIVERSITY LIMITATION #1` (tempo band), `DIVERSITY LIMITATION #2` (rhythmic monoculture), and `DIVERSITY LIMITATION #3` (form template rigidity).
* Executed Farthest Point Sampling to select the 30 most diverse and representative tracks spanning all clusters, tempos, and modes adhering to quotas (Composer v1: 6, v2 0.50: 7, v2 0.65: 10, v2 0.80: 7).
* Created dedicated listening test suite in [listening_test_v2_selected/](listening_test_v2_selected/) with 30 anonymized WAVs, [listening_test_v2_selected/rating_template.csv](listening_test_v2_selected/rating_template.csv), [listening_test_v2_selected/answer_key.json](listening_test_v2_selected/answer_key.json), and 30-pair A/B comparison sheets.
* Generated detailed analytical report in [stage6_6_diversity_report.md](stage6_6_diversity_report.md).
* Added CLI command `audit-diversity` in [src/atari_music/cli.py](src/atari_music/cli.py).
* Added unit test `test_diversity_audit_artifacts_and_selection` in [tests/test_pokey_music.py](tests/test_pokey_music.py) (22/22 tests passing).

* Built blinded listening test preparation and validation engine in [src/atari_music/listening_test_v2.py](src/atari_music/listening_test_v2.py) assembling 4 strictly procedural groups (Group A: Composer v1, Group B: Composer v2 novelty 0.50, Group C: Composer v2 novelty 0.65, Group D: Composer v2 novelty 0.80) with 20 tracks each (80 WAV samples total).
* Strictly eliminated all original dataset tracks from the test pool to guarantee a pure double-blind test between procedural generator iterations.
* Preserved complete musical forms without arbitrary 20-second truncation (durations between 15.36s and 30.72s, averaging ~23.4s).
* Enforced identical loudness normalization across all 80 samples (-0.92 dBFS peak at 44.1 kHz 16-bit mono PCM).
* Implemented randomized anonymization into `sample_001.wav` .. `sample_080.wav` with secret mapping stored in [listening_test_v2/answer_key.json](listening_test_v2/answer_key.json).
* Created comprehensive evaluation sheet in [listening_test_v2/rating_template.csv](listening_test_v2/rating_template.csv) featuring 10 Likert 1–5 metrics (including core `sounds_like_real_atari_game`) and categorical generator guess.
* Designed 30-pair randomized A/B comparison test in [listening_test_v2/pairwise_rating_template.csv](listening_test_v2/pairwise_rating_template.csv) and [listening_test_v2/pairwise_answer_key.json](listening_test_v2/pairwise_answer_key.json) covering v1 vs v2, v2 0.50 vs 0.65, and v2 0.65 vs 0.80.
* Implemented automated pre-flight sanity checker `validate_listening_test_v2` verifying 80 WAV files, group counts, zero dataset tracks, audio integrity, and peak/RMS bounds (`VALIDATION PASSED: EXPERIMENT READY`).
* Generated Stage 6.5 preparation report in [stage6_5_listening_report.md](stage6_5_listening_report.md) with technical baseline parameters across all 4 groups.
* Extended CLI commands in [src/atari_music/cli.py](src/atari_music/cli.py) with `prepare-listening-test-v2`, `validate-listening-test-v2`, and `stage6-5-report`.
* Added unit test `test_listening_test_v2_artifacts_and_validation` in [tests/test_pokey_music.py](tests/test_pokey_music.py) (21/21 tests passing).

* Designed pure symbolic Music Intermediate Representation (Music IR) in [src/atari_music/music_ir.py](src/atari_music/music_ir.py) (`MusicSong`, `SymbolicPattern`, `SymbolicTrack`, `SymbolicNote`, `MusicPhrase`, `HarmonicFunction`, `MelodicContour`, `ChannelRole`, `ChordStep`) fully decoupled from POKEY hardware registers.
* Implemented interval grammar and melodic contour engine in [src/atari_music/contour_engine.py](src/atari_music/contour_engine.py) generating directional interval vectors (`UP`, `DOWN`, `ARCH`, `ASCENDING`, `DESCENDING`, `WAVE`, `QUESTION_ANSWER`) realized into diatonic pitch steps.
* Built motivic mutation engine in [src/atari_music/mutations.py](src/atari_music/mutations.py) supporting transposition, inversion, retrograde, rhythmic subdivision/augmentation, and interval substitution to form genuine phrase variations ($A \to A' \to A''$).
* Developed functional and modal harmony engine in [src/atari_music/harmony_engine.py](src/atari_music/harmony_engine.py) supporting classic and modal progressions with four harmonic roles (`TONIC`, `PREDOMINANT`, `DOMINANT`, `RESOLUTION`).
* Implemented independent bassline generator in [src/atari_music/bass_engine.py](src/atari_music/bass_engine.py) featuring contrary counter-motion to lead melody, root bass, walking bass, ostinato, and rhythmic pulses.
* Built decoupled rhythm generator in [src/atari_music/rhythm_engine.py](src/atari_music/rhythm_engine.py) separating note duration and syncopation patterns from pitch sequences.
* Assembled master Composer v2 engine in [src/atari_music/composer_v2.py](src/atari_music/composer_v2.py) with active memory optimizer (`deduplicate_pokey_patterns`, sequence compaction), hard constraint enforcement (`max_size <= 2048 B`, `min_channels` / `max_channels`), generate-and-test loop up to 100 attempts, and transparent 11-metric `QualityReport`.
* Ran 60-track batch experiment in [src/atari_music/composer_v2_experiment.py](src/atari_music/composer_v2_experiment.py) generating 20 tracks x novelty 0.50, 20 tracks x novelty 0.65, and 20 tracks x novelty 0.80 into [experiments/composer_v2/](experiments/composer_v2/) with both POKEY IR JSON and 44.1 kHz WAV audio, compiled into [experiments/composer_v2/summary.json](experiments/composer_v2/summary.json).
* Created Stage 6 reporting engine in [src/atari_music/stage6_reporter.py](src/atari_music/stage6_reporter.py) generating [stage6_composer_v2_report.md](stage6_composer_v2_report.md) answering all 12 key architectural questions with comparative empirical metrics across dataset, `generated/`, and Composer v2 novelty tiers.
* Extended CLI commands in [src/atari_music/cli.py](src/atari_music/cli.py) with `compose-v2`, `run-composer-v2-experiment`, and `stage6-report`.
* Added 5 new unit tests in [tests/test_pokey_music.py](tests/test_pokey_music.py) for Music IR, 2-channel mode, motivic mutations, pattern deduplication, and generation failure handling (20/20 tests passing).

* Implemented memorization, transposition, and novelty analysis engine in [src/atari_music/memorization_analysis.py](src/atari_music/memorization_analysis.py) with Longest Common Contiguous Subsequence (LCS) search across 150 source dumps and all generated songs.
* Created interval fingerprinting ($\Delta = \text{pitch}_{i+1} - \text{pitch}_i$) and duration sequence matching to detect melodic copying under arbitrary key transposition.
* Formulated transparent 4-component Novelty Score (`exact_novelty`, `interval_novelty`, `rhythm_novelty`, `structure_novelty`) and computed empirical distributions across 4 groups (REAL, GENERATED, LISTENING_TEST, CONTROL).
* Proved empirically that the generator does NOT memorize source music (max exact match: 3–5 notes, interval match: 5–8 steps, compared to 8–14 steps shared among real Atari songs).
* Performed deep technical audit between `batch_experiment.py` and `listening_test.py` identifying root causes of subjective perception (presence of 10 literal classic Atari tracks in blinded test, 20.0s hard truncation, RNG state drift from omitted parameters), documented in [generator_comparison.md](generator_comparison.md).
* Generated comprehensive research report in [stage5_5_report.md](stage5_5_report.md) answering all 6 core architectural questions.
* Added CLI command `investigate-memorization` in [src/atari_music/cli.py](src/atari_music/cli.py).
* Added unit test `test_memorization_and_novelty_metrics` in [tests/test_pokey_music.py](tests/test_pokey_music.py) (15/15 tests passing).

## [2026-09-26] - Stage 5: Blinded Subjective Listening Test Protocol & Statistical Baseline
* Implemented naive baseline control generator in [src/atari_music/control_generator.py](src/atari_music/control_generator.py) respecting 4 POKEY channels and pitch constraints but omitting all mined musical archetypes (random scale walks, flat envelopes, unguided rhythms, no tracker form).
* Built blinded listening test preparation suite in [src/atari_music/listening_test.py](src/atari_music/listening_test.py) rendering 30 normalized audio tracks (exactly 20.00s @ 44.1 kHz 16-bit mono via `pokey_synth.py`) randomized into `listening_test/sample_001.wav` .. `sample_030.wav`.
* Selected 10 diverse original Atari tracks for GROUP A (REAL) from Ben Daglish, Rob Hubbard, Adam Gilmore, David Whittaker, Jakub Husak, and Tomasz Liebich; 10 tracks for GROUP B (GENERATED) from Stage 4 procedural engine; 10 tracks for GROUP C (CONTROL) from naive generator.
* Generated blinded participant instructions in [listening_test/README.md](listening_test/README.md), evaluation spreadsheet in [listening_test/rating_template.csv](listening_test/rating_template.csv) (Likert 1–5 scale across 8 dimensions), and secret mapping in [listening_test/answer_key.json](listening_test/answer_key.json).
* Calculated automated baseline metrics across all 3 groups (tempo, unique notes, pitch range, repetition, channel utilization, IR size) in `listening_test/group_statistics.json`.
* Implemented Stage 5 report generator in [src/atari_music/stage5_reporter.py](src/atari_music/stage5_reporter.py) creating [stage5_report.md](stage5_report.md).
* Added CLI commands `prepare-listening-test` and `stage5-report` in [src/atari_music/cli.py](src/atari_music/cli.py).
* Added unit tests `test_control_generator` and `test_listening_test_artifacts` in [tests/test_pokey_music.py](tests/test_pokey_music.py) (14/14 tests passing).

## [2026-09-26] - Stage 4: Procedural POKEY Music Generator, IR, Synthesizer & 100-Song Validation
* Designed symbolic Intermediate Representation (IR) in [src/atari_music/ir.py](src/atari_music/ir.py) (`IRSong`, `IRInstrument`, `IREnvelope`, `IRMacroStep`, `IRPattern`, `IRNote`, `compile_ir_to_pokey_frames`, and compact 6502 tracker memory calculator `calculate_ir_binary_size`).
* Built cycle/sample-accurate software POKEY audio synthesizer in [src/atari_music/pokey_synth.py](src/atari_music/pokey_synth.py) supporting pure tone ($A0), 4-bit poly LFSR buzz ($C0), 5-bit poly ($20/$60), 17-bit/9-bit noise ($80/$E0), joined 16-bit bass (CH1+CH2), and 4-bit non-linear DAC ladder rendering to 44.1 kHz 16-bit PCM WAV.
* Implemented empirical pattern and archetype mining engine in [src/atari_music/archetypes.py](src/atari_music/archetypes.py) extracting 21 archetypes across melody, rhythm, bass, and percussion micro-envelopes from the 330-subsong dataset, saved to [dataset/archetypes.json](dataset/archetypes.json).
* Created constrained procedural generator in [src/atari_music/generator.py](src/atari_music/generator.py) enforcing 4 POKEY channels, monophonic voice bounds, optional 16-bit bass pairing, and strict < 2 KB data budget.
* Executed batch experiment pipeline in [src/atari_music/batch_experiment.py](src/atari_music/batch_experiment.py) generating 100 songs (`generated/song_000.json`..`song_099.json`, `song_000.wav`..`song_099.wav`) across varied seeds, keys, and modes.
* Performed comparative statistical evaluation between 330 REAL Atari songs and 100 PROCEDURAL songs, confirming hypothesis and 100% compliance with < 2 KB budget (median size: 486 bytes).
* Implemented Stage 4 report generator in [src/atari_music/stage4_reporter.py](src/atari_music/stage4_reporter.py) producing [stage4_report.md](stage4_report.md) answering all 8 architectural questions in depth.
* Extended CLI in [src/atari_music/cli.py](src/atari_music/cli.py) with `mine-archetypes`, `generate-song`, `run-experiment`, and `stage4-report`.
* Added 4 unit tests in [tests/test_pokey_music.py](tests/test_pokey_music.py) (12/12 tests passing).

* Implemented multi-panel visualization suite in [src/atari_music/visualizer.py](src/atari_music/visualizer.py) and audio validation renderer via `asapconv`.
* Generated 6 comprehensive visual dashboards in `visualizations/` and 6 validation audio WAV files in `visualizations/audio/` for representative tracks across all 6 target styles (standard melody, hybrid, digi/sample, 16-bit bass, ultrasound, stereo).
* Implemented channel role classifier in [src/atari_music/classifier.py](src/atari_music/classifier.py) supporting `melody`, `bass`, `percussion`, `arpeggio`, `sound_effect`, `digi_sample`, and `unknown`.
* Evaluated channel layout hypothesis across 320 mono tracks, establishing empirical 4x7 channel role matrix.
* Built 4-level pattern discovery evaluation in [src/atari_music/pattern_discovery.py](src/atari_music/pattern_discovery.py) comparing Raw state, Pitch+dur, Pitch+dur+dist, and Role+pitch+rhythm.
* Calculated exact memory footprint percentiles (mean, median, p10, p25, p75, p90, p95) for raw SAP, dumps, event streams, deduplicated patterns, and hypothetical minimal music IR.
* Generated comprehensive Stage 3 report in [stage3_report.md](stage3_report.md).

## [2026-09-26] - Stage 2: Three-Layer POKEY Architecture, Full Dataset & Statistical Report
* Implemented three-layer pipeline: `RAW` (non-destructive gzipped text dumps) → `POKEY EVENTS` (discrete change events stream) → `MUSICAL FEATURES` (physical measurements + heuristic note inference with confidence scores).
* Built core package in `src/atari_music/`:
  - [src/atari_music/constants.py](src/atari_music/constants.py): POKEY clock frequencies, registers, distortion names, and note maps.
  - [src/atari_music/models.py](src/atari_music/models.py): Pydantic v2 data models for dumps, events, snapshots, features, repetition/memory, and dataset records.
  - [src/atari_music/extractor.py](src/atari_music/extractor.py): Streaming raw capture of `asapscan -d` to `dataset/raw/*.dump.gz` with loop detection.
  - [src/atari_music/events.py](src/atari_music/events.py): PokeyEvent delta streamer and state reconstructor (`PokeyStateReconstructor`).
  - [src/atari_music/features.py](src/atari_music/features.py): Acoustic/musical interpreter for 8-bit/16-bit POKEY voices, pitch mapping, confidence scoring, and tempo estimator.
  - [src/atari_music/analyzer.py](src/atari_music/analyzer.py): Music categorization, repetition and motif discovery, and 6502 RAM footprint estimator.
  - [src/atari_music/dataset.py](src/atari_music/dataset.py): Dataset builder and fast raw re-analyzer.
  - [src/atari_music/reporting.py](src/atari_music/reporting.py): Global statistical report generator.
  - [src/atari_music/cli.py](src/atari_music/cli.py): CLI interface (`extract`, `analyze`, `report`).
* Created test suite in [tests/test_pokey_music.py](tests/test_pokey_music.py) and configured [pyproject.toml](pyproject.toml) (8 tests passing).
* Successfully extracted and analyzed 100% of all 330 subsongs (140 files) with 0 failures into `dataset/` (`raw/`, `events/`, `features/`, [dataset/dataset.jsonl](dataset/dataset.jsonl)).
* Generated full statistical report [report_stage2.md](report_stage2.md).

## [2026-09-26] - Initial Environment Exploration, Inventory & POKEY Extraction POC
* Discovered and parsed 140 Atari `.sap` files across 6 composers (`music/Daglish_Ben`, `music/Gilmore_Adam`, `music/Hubbard_Rob`, `music/Husak_Jakub`, `music/Liebich_Tomasz`, `music/Whittaker_David`).
* Built header scanner in [scripts/inventory.py](scripts/inventory.py) generating [inventory.json](inventory.json) and [inventory.csv](inventory.csv).
* Evaluated emulation tooling (ASAP 8.0.0, `asapconv`, `asapscan`, `POKEY2MIDI`, `py65`).
* Integrated `asapscan` binary in `tools/asap/asapscan.exe` for cycle-accurate 6502+POKEY execution at ~66,000 frames/sec.
* Created proof-of-concept POKEY extractor in [scripts/poc_extract.py](scripts/poc_extract.py) capturing per-frame states, register deltas, active voices, and stereo dual-POKEY support.
* Created [requirements.txt](requirements.txt) and configured `.venv` with `pydantic`, `numpy`, `click`, `matplotlib`, and `pytest`.
* Successfully generated POC register dumps in `poc_output/` for `Gauntlet.sap`, `Extirpator.sap`, and `Perestroyka_Stereo.sap`.

# Your First Composition

This page walks through the shortest path from a fresh checkout to a rendered song. All commands were
verified against the current release; run them from the repository root with your virtual environment
activated. None of the steps below requires an AI API key or the MADS assembler — the offline mock
provider and the WAV renderer suffice for steps 1–3.

## 1. Generate a deterministic song (procedural)

```bash
python -m atari_music compose --profile dungeon --seed 501 --length short \
  --output-json output/first/first.json \
  --output-wav output/first/first.wav
```

The procedural Composer v4 emits a fully validated 4-channel POKEY IR JSON and renders it to a
44.1 kHz 16-bit mono WAV. The seed makes the result deterministic:

```text
Generated [DUNGEON]: 'ComposerV4 [DUNGEON] #501 (A dorian)' (Seed: 501)
Key: A dorian, Tempo: 85 BPM, Form: A A' B A, Dur: 12.8s, Mem: 389 B, Channels: 4, Format: v1
Saved POKEY IR -> output\first\first.json
Rendered WAV -> output\first\first.wav
```

## 2. Generate a song with the AI pipeline (offline mock)

The same canonical pipeline used for live LLMs can be exercised offline with `--provider mock`:

```bash
python -m atari_music ai-compose --provider mock \
  --style "dark dungeon exploration" -m dark --duration 24 \
  -o output/first/composition.json
```

The mock provider produces a canonical `AICompositionDoc` JSON document through the same 3-tier
validation (schema, musical grammar, POKEY hardware rules) as the live providers:

```text
Requesting composition from provider 'mock' (format: json)...
  Style: dark dungeon exploration, BPM: 120, Channels: 4, 16-bit bass: False, max retries: 3
Successfully generated and validated composition -> output\first\composition.json
  Title: AI Dark dungeon exploration Journey
```

With real credentials in `.env` (see [Installation](installation.md)), the same command without
`--provider mock` calls your configured LLM.

## 3. Import an existing Music DSL song and inspect it

The repository ships example songs in `examples/songs/`. Import one and analyze it:

```bash
python -m atari_music import-dsl examples/songs/Vaults-of-Nhyrmeth.dsl \
  --output-json output/first/vaults.json \
  --output-wav output/first/vaults.wav

python -m atari_music analyze output/first/vaults.json
```

`import-dsl` validates the DSL, converts it to canonical JSON, and renders a WAV preview in one step.
`analyze` prints musical metrics (pitch range, consonance), POKEY hardware utilization, and SHA-256
fingerprint; add `--structure` for repetition ratios and a deduced form.

## 4. Re-arrange it with catalog instruments

Swap the lead, bass, and percussion of the imported song **without changing a single note** —
arrangement is offline, deterministic, and never calls AI:

```bash
python -m atari_music arrange output/first/vaults.json \
  --channel-instrument 1=bass_16bit_pure \
  --channel-instrument 3=lead_pure_pluck \
  --channel-instrument 4=perc_tom_pitched \
  --program-change-policy remove \
  --output-json output/first/vaults_arranged.json \
  --output-wav output/first/vaults_arranged.wav
```

Browse candidates first with `python -m atari_music list-instruments --target xex_v2` or see
[Instruments](../user-guide/instruments.md).

## 5. Compile a standalone Atari executable

With the MADS assembler available (see [Installation](installation.md)), compile the DSL song —
or your arranged JSON — into a relocatable `.xex` binary that boots on real hardware:

```bash
python -m atari_music build-xex examples/songs/Vaults-of-Nhyrmeth.dsl --format dsl \
  -o output/first/vaults.xex
```

```text
Building Atari XEX from examples\songs\Vaults-of-Nhyrmeth.dsl (DSL)...
  Configuration: player=$6000, music=$8000, ZP=$80
Successfully compiled XEX -> output\first\vaults.xex (3994 bytes)
```

Drop the `.xex` onto your Atari 800 XL / 65 XE (or an emulator such as Altirra) — it shows an
`ANTIC` Mode 2 playback screen with time display, 4-channel VU meters, and keyboard mute/pause
(`1`–`4`, `Space`).

## Where to go next

* [Composition Workflow](../user-guide/workflow.md) — the complete user-facing pipeline.
* [Export & Atari Playback](../user-guide/export.md) — WAV synthesis and XEX constraints.
* [CLI Reference](../reference/cli.md) — every production command and option.
* Prefer a GUI? [Atari Music Composer Studio](../user-guide/studio.md).

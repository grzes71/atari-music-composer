# AI-Assisted Composition

The `ai-compose` command generates a composition with an LLM provider and pushes it through the same
validation, IR compilation, and rendering pipeline as every other input. The AI's job is exclusively
*compositional*: producing a valid `AICompositionDoc` (JSON) or [Music DSL](../reference/music-dsl.md)
transcription. Hardware realization remains a non-AI concern.

## Providers

| Provider | Selection | Endpoint / client |
| --- | --- | --- |
| `deepseek` | Default; `--provider deepseek` or `AI_PROVIDER=deepseek` | `OpenAICompositionProvider` (default `https://api.deepseek.com`, model `deepseek-flash`) |
| `openai` | `--provider openai` / `AI_PROVIDER=openai` | `OpenAICompositionProvider`; honours `AI_BASE_URL` / `OPENAI_BASE_URL` and `AI_MODEL` / `OPENAI_MODEL` |
| `mock` | `--provider mock` | `MockAICompositionProvider` — offline, deterministic, no key/network |

Provider credentials come from the 4-level configuration chain (CLI → environment → `.env` → defaults);
see [Installation](../getting-started/installation.md).

## Command reference

| Option group | Options |
| --- | --- |
| Musical intent | `--style TEXT`, `-m, --mood TEXT` (repeatable), `--duration FLOAT`, `--bpm INTEGER`, `--key TEXT`, `--mode TEXT`, `--notes TEXT`, `--structure TEXT` |
| Hardware | `--channels INTEGER` (1–4), `--use-16bit-bass / --no-16bit-bass` |
| Output format | `--format [json\|dsl]`, `-o, --output PATH`, `--output-ir`, `--output-asm`, `--output-wav` |
| Prompting | `--prompt-profile [classic\|rich]`, `--tempo-grid [describe\|exact]`, `--temperature FLOAT` |
| Quality | `--plan-first / --no-plan-first`, `--quality-passes INTEGER`, `--rhythmic-density [low\|medium\|high\|extreme]` |
| Robustness | `--max-retries INTEGER` (validation repair attempts, default 3) |
| Instruments | `--channel-instrument CH=ID`, `--use-instrument-catalog / --no-use-instrument-catalog`, `--instrument-catalog FILE`, `--player-version [auto\|v1\|v2]`, `--format` |
| Provider | `--provider [mock\|openai\|deepseek]`, `--model TEXT`, `--env-file FILE`, `--log-level` |

## Example session

```bash
# Offline deterministic mock producing canonical JSON
python -m atari_music ai-compose --provider mock \
  --style "dark dungeon exploration" -m dark --duration 24 -o composition.json

# Compact Music DSL with catalog awareness enabled
python -m atari_music ai-compose --provider mock --format dsl --use-instrument-catalog -o composition.dsl

# Rich prompt profile with a musical brief, exact PAL grid tempo,
# high rhythmic density, and one critique pass (live provider)
python -m atari_music ai-compose --format dsl --prompt-profile rich --style "boss fight" \
  --key E --mode phrygian --bpm 140 --duration 40 --use-16bit-bass \
  --rhythmic-density high --plan-first --quality-passes 1 -o boss.dsl
```

## Why the AI never touches hardware

Every provider result is parsed and compiled into `AICompositionDoc` and must pass the **3-tier
validation**:

1. **Schema tier** — pydantic models for metadata, hardware flags, instruments, patterns, sequence,
   and loop point.
2. **Musical tier** — musical grammar rules (e.g. per-channel monophony, `BASS16_CHANNEL_CONFLICT`
   rejection when 16-bit bass is misused).
3. **Hardware tier** — POKEY constraints (channel count, divider modes, `AUDCTL` compatibility).

Documents that fail validation are sent back to the provider with structured error messages for up to
`--max-retries` repair attempts (default 3). Opt-in `--plan-first` asks the model for a structured
`MusicalBrief` before composing notes, and `--quality-passes N` runs post-validation musical critique
and revision rounds. See the [AI composition layer](../architecture/ai-layer.md) for the internal flow.

## Token efficiency of Music DSL

`--format dsl` asks the LLM to emit the compact line-oriented Music DSL instead of nested JSON. Empirical
100-trial benchmark runs measured **49.4 % fewer LLM tokens** than JSON (see
[the DSL specification](../reference/music-dsl.md) for the grammar and full benchmarks). The DSL is
compiled into exactly the same `AICompositionDoc`, so validation and output are identical.

## After generation

Save the JSON as your master composition and move to the arrangement loop:
[Arrangement](arrangement.md). Binary/spec details of what `--output-ir`, `--output-asm`, and
`--output-wav` contain live in [Composition Formats](composition-formats.md) and
[Export](export.md).

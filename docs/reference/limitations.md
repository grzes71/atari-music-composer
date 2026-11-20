# Technical Limitations

What the system deliberately does not (yet) do. Everything listed here is a **design boundary**, most of
them enforced by validation rather than merely discouraged. For the hardware constants behind these
rules, see the [Glossary](glossary.md) and [Audio Engine](../architecture/audio-engine.md).

## Hardware scope

| Boundary | Rationale |
| --- | --- |
| **PAL 50 Hz only** | Frames, tempo grids, and the player's VBLANK sync assume 50 Hz; no NTSC timing is generated |
| **4 monophonic channels** | The engine is built around POKEY's 4-channel layout; per pattern each channel takes a single monophonic event stream |
| **Official 6502 instructions only** | Guarantees binaries run on stock XL/XE CPUs (`player.asm` is audited for this) |
| **Player < 2048 B** | The compiled player (code + BSS) must fit the game integration budget; enforced by `player_budget`, currently 1785 B |
| **User segments `$0400–$BFFF`, disjoint** | Avoids OS ROM, hardware I/O, Zero Page, and stack; enforced by `xex_layout` on every build |

## Composition & format scope

* **`arrange` accepts JSON only** (`AICompositionDoc` / `IRSong`); `.dsl` inputs must be converted with
  `import-dsl` first. This is a deliberate input-validation boundary, not a missing feature.
* **Music DSL scope limits** — directives cover headers, instruments (character/envelope fields),
  patterns, channel blocks, notes/rests; the DSL does *not* encode Stage C/D `catalog_id` fields or
  `PROGRAM_CHANGE` events (use JSON + catalog flags for those).
* **Format v1 → v2 is one-way-aware** — `--player-version v1` raises `FormatVersionError` rather than
  degrading v2 features; `auto` keeps v1 whenever the song fits it.
* **Format v2 track headers do not store an explicit stream byte length**; integrity is guaranteed by
  exporter-side validation plus the player's runtime command cap (see
  [Song Format v2 §5](song-format-v2.md)).

## Instrument & target capabilities

Implemented targets: `xex_v1`, `xex_v2` (Format v2), and `wav` previews (v1 and v2 frame simulation).

Explicitly **deferred / blocked** (fail loudly, never silently degrade):

* `core_v2_iter2` — delayed vibrato, pitch slides, arpeggios.
* `experimental_deferred` catalog profiles — `lead_hpf_pwm` (HPF XOR PWM) and `ornament_bell_arp`
  (arpeggio ornament) are marked `[DEFERRED_FEATURE]` on all targets.
* 16-bit `CH3+CH4` bass pairing in the production workflow (16-bit joins exist for CH1+CH2 songs via
  `BASS 16BIT`).
* Built-in SAP export (`asap` targets are declared in the runtime but `is_implemented=False`).

## Environment & research scope

* **MADS is required for `.xex` compilation** and is *not* distributed with the repository (gitignored
  `tools/`); on fresh checkouts the MADS-dependent tests skip cleanly.
* **Research commands and datasets** (`analyze-stage15`…`analyze-stage25`, listening-test preparation,
  `dataset/`, `reports/`, `experiments/`, `listening_test*/`) are local research tooling outside the
  production pipeline; their tests carry the `experimental` marker (see
  [Testing Strategy](../development/testing.md)).
* **Live LLM tests** are opt-in (`-m live`) and require real credentials; they are excluded from CI.
* **NTSC/DAC/silicon caveats** — the software renderer reproduces the digital POKEY path (LFSRs, HPF
  XOR, joining, resistor-ladder DAC) but real-hardware analog mixing and speaker output can still differ
  in the last mile; the [XEX verification guide](xex-verification.md) documents the manual
  hardware checklist for that final gap.

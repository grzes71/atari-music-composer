# Rhytmizer (`rhytmizer.xex`) — Comprehensive Reverse-Engineering & Percussion Extraction Report (Revised in Phase H)

- **Source Binary:** `rhytmizer.xex` (`6,333` bytes, SHA-256: `d22206b9324ff5f9a13eaba213009aeb3d6df6d69bb56c1fdbf48cc41045c772`)
- **Original Title & Author:** `Rythmizer AT1` — `(c) MUNSIE 1986` (Startup banner: `"BRO-BEAT STRIKES BACK! ... Bustin up shits in 1986!"`)
- **Target Platform:** Atari 8-bit XL/XE (MOS 6502 CPU at `1,773,447.0 Hz` PAL, POKEY `$D200–$D20F`, ANTIC Mode 2 display lists)
- **Companion Phase Deliverables:**
  - **Phase A (Binary & Memory Layout):** [`docs/reverse_engineering/rhytmizer_binary_analysis.md`](rhytmizer_binary_analysis.md)
  - **Phase B (6502 Disassembly & Code Analysis):** [`docs/reverse_engineering/rhytmizer_disassembly.asm`](rhytmizer_disassembly.asm) and [`docs/reverse_engineering/rhytmizer_code_analysis.md`](rhytmizer_code_analysis.md)
  - **Phase C (Sound Engine Reconstruction):** [`docs/reverse_engineering/rhytmizer_sound_engine.md`](rhytmizer_sound_engine.md)
  - **Phase D (Instrument Catalog):** [`docs/reverse_engineering/rhytmizer_instrument_catalog.md`](rhytmizer_instrument_catalog.md)
  - **Phase E (Cycle-Accurate Instrument Event JSONs & WAV Recordings):** [`docs/reverse_engineering/instruments/`](instruments/) (`9` `.json` files + `9` `.wav` files)
  - **Phase F (Revised Compatibility Assessment):** [`docs/reverse_engineering/rhytmizer_compatibility.md`](rhytmizer_compatibility.md)
  - **Phase H (Independent Technical Verification & Correction Report):** [`docs/reverse_engineering/rhytmizer_verification_report.md`](rhytmizer_verification_report.md)

---

## 1. Executive Summary

We performed a complete static and dynamic (`py65` cycle-accurate 6502 emulation + `ASAP 8.0.0` reference POKEY verification) reverse-engineering analysis and Phase H technical audit of `rhytmizer.xex` (`6,333` bytes). Key verified conclusions:

1. **Two-Stage Self-Relocating Binary:**
   - `rhytmizer.xex` loads a 6,272-byte packed image at `$2A80–$42FF` and a 43-byte Stage 1 relocator stub at `$4300–$432A` (`RUNAD = $4300`).
   - Stage 1 copies `$2A80–$437F` down to `$0700–$1FFF` and invokes a descriptor-driven Stage 2 unpacker at `$0706–$0798` (`17` backward block-copy descriptors at `$079F–$0804`), which unpacks a splash screen to **`$B800–$BBEF`** (`1,008` bytes) and the main application, UI screen RAM, Display List, sound synthesis routines, and built-in 1,246-step Demo Pattern to **`$200B–$333B`** (`4,913` bytes), before jumping to the runtime entry point at **`$2540`**.
2. **Complete Percussion Inventory (`9` Playable Instruments + `1` Rest Routine):**
   - Rhytmizer provides **9 distinct percussion instruments** triggered via keyboard keys (in Record Mode) or pattern byte stream (in Play/Demo Mode):
     1. **`1>HH CLOSED`** (`$26CE`, key `'1'`, `CH=$1F`)
     2. **`2>HH ACCENT`** (`$2798`, key `'2'`, `CH=$1E`)
     3. **`3>SNARE`** (`$2571`, key `'3'`, `CH=$1A` — user-tunable noise divider `$2006` and tone sweep base `$2005`)
     4. **`SPACE>BASS DRUM`** (`$272E`, key `'SPACE'`, `CH=$21`)
     5. **`4>TOM 1`** (`$28D2`, key `'4'`, `CH=$18`)
     6. **`5>TOM 2`** (`$2937`, key `'5'`, `CH=$1D`)
     7. **`6>TOM 3`** (`$299C`, key `'6'`, `CH=$1B`)
     8. **`7>WOOD BLOCK`** (`$2844`, key `'7'`, `CH=$33`)
     9. **`8>CLAPS`** (`$27F3`, key `'8'`, `CH=$35`)
   - Plus a silent rest pseudo-instrument **`*>SKIP A BEAT`** (`$2895`, key `'*'`, `CH=$07`).
3. **Procedural Dual-Channel Sub-Frame Synthesis Engine:**
   - Rhytmizer uses **zero lookup tables** and **zero custom interrupts (no VBI, no DLI, no Timer IRQ)**.
   - Every instrument is a self-contained 6502 routine executing a **9-step software loop** (`$2000 = 8..0`). Each step calls the shared delay routine `$271E` (`12,615` CPU cycles including `JSR/RTS` at default Record tempo `$2002 = $07`) plus `53–68` cycles of loop-body register updates, totaling **`12,668–12,683` CPU cycles (`7.143–7.152 ms` PAL) per step** (`~140.0 Hz` sub-frame update rate; `113,982–114,173` cycles = **`64.271–64.379 ms` PAL** per complete 9-step beat).
   - Eight of the nine instruments simultaneously layer **POKEY Channel 1 (`$80` 17-bit poly noise)** and **POKEY Channel 2 (`$A0` pure tone sweep/ring or `$80` secondary noise)**, switching `AUDCTL ($D208)` between **`$00` (`63,337.39 Hz` PAL base clock)** for bright percussion and **`$01` (`15,556.55 Hz` PAL base clock)** for drums/toms, and prepending a **12-to-24-cycle (`6.8–13.5 µs`) Volume-Only DAC attack write (`$1F`/`$1B`)** on Snare, Bass Drum, and Toms 1–3.
4. **Confirmed Original Bug in `8>CLAPS` (`$2821: STA $D5EB`):**
   - At runtime address `$2821` (raw file offset `0x08EF–0x08F1`), `TRIG_CLAPS` contains `8D EB D5` (`STA $D5EB`, unmapped cartridge space) instead of `8D 03 D2` (`STA $D203`, `AUDC2`), leaving Channel 2 silent even though `AUDF2 = $1E` is written at `$282B`.
5. **Phase H Verified Compatibility with Atari Music Composer (Modes A, B, C, D):**
   - **Mathematical Divider Conversion Proof:** Because the PAL base-clock ratio is $\frac{114}{28} = \frac{57}{14} \approx 4.071429$, **no** `AUDCTL=$01` → `AUDCTL=$00` divider conversion in Rhytmizer is mathematically exact. For **Snare** (`$18..$28 → $65..$A6`) and **Tom 1** (`$23..$33 → $92..$D3`), the nearest 8-bit 64 kHz pure-tone dividers approximate the original frequencies within **`0.04%–0.35%`** (and `AUDF1=$01 → $07` approximates the noise clock within **`+1.786%`**). By contrast, **Tom 2** clips its last two steps (`+6.56%`, `+12.92%`), and **Tom 3** (`+3.38%` to `+35.18%`) and **Bass Drum** (`+47.91%` to `+76.54%`) lie below the 8-bit 64 kHz `$A0` pure-tone floor (`123.71 Hz` at `$FF` / `124.19 Hz` at tracker max `$FE`).
   - **Four-Mode Classification:**
     - **`DIRECT` (Single-Channel 50 Hz Mode B):** `8>CLAPS` (already 1-ch in original binary), `1>HH CLOSED`, and `2>HH ACCENT` (omitting only the `-28 dB` `vol=1` `CH2` metallic overtone).
     - **`EXTENDED` (Dual-Channel 50 Hz Mode C1/C2):** `7>WOOD BLOCK` (Mode C1 `AUDCTL=$00` preserves simultaneous dual-noise interference), `3>SNARE` and `4>TOM 1` (Mode C1 `AUDCTL=$00` or Mode C2 `AUDCTL=$01`/`$29` preserves simultaneous noise + tone sweep at 50 Hz VBI), and `5>TOM 2` (Mode C2 `AUDCTL=$01`/`$29` required for unclipped tail).
     - **`CUSTOM` (Sub-Frame `150 Hz` + `AUDCTL=$01` Mode D, or Mode C2 15 kHz approximation):** `6>TOM 3` (requires `AUDCTL` Bit 0 = `1` or 16-bit divider to reach `91.5 Hz` in `$A0` pure tone) and `SPACE>BASS DRUM` (requires both `AUDCTL` Bit 0 = `1` for the `83.6→70.1 Hz` `$A0` sub-bass and sub-frame `~140–150 Hz` stepping to execute the `14.31 ms` 2-step pitch drop without stretching it to `40 ms`).

---

## 2. Binary Structure and Memory Map

| Stage / Segment | File Offset | Load Address | Runtime Destination | Size | Description |
| --- | :---: | :---: | :---: | :---: | --- |
| **XEX Segment 0** | `0x0002–0x1885` | `$2A80–$42FF` | Relocated twice | `6,272` B | Packed application image + Stage 2 unpacker |
| **XEX Segment 1** | `0x1888–0x18B6` | `$4300–$432A` | `$4300–$432A` | `43` B | Stage 1 page copier (`$2A80..$437F -> $0700..$1FFF`) |
| **XEX Segment 2** | `0x18B7–0x18BC` | `$02E0–$02E1` | `RUNAD` (`$02E0`) | `2` B | Entry point vector `RUNAD = $4300` |
| **Stage 2 Unpacker** | `0x0002–0x0106` | `$2A80–$2B84` | **`$0700–$0804`** | `261` B | Unpacks 17 descriptors at `$079F–$0804`, calls `$B800`, jumps to `$2540` |
| **Splash Screen** | `0x1445–0x1834` | `$3EC3–$42B2` | **`$B800–$BBEF`** | `1,008` B | `$B800` init routine, `$B810` Mode 2 DLIST, `$B830` `"BRO-BEAT STRIKES BACK!"` screen |
| **Main App & Engine** | `0x0107–0x1437` | `$2B85–$3EB5` | **`$200B–$333B`** | `4,913` B | UI screen RAM (`$200B–$24BA`), CIO filename buffer (`$24BB`), Main DLIST (`$24F2`), Code (`$2540–$2E5C`), Demo Pattern (`$2E5D–$333B`) |

---

## 3. Sound-Generation Architecture & Exact Timing Model

- **PAL Clock Baseline:** $f_{\text{CPU,PAL}} = 1,773,447.0\text{ Hz}$, $f_{64\text{kHz}} = \frac{f_{\text{CPU}}}{28} = 63,337.3929\text{ Hz}$, $f_{15\text{kHz}} = \frac{f_{\text{CPU}}}{114} = 15,556.5526\text{ Hz}$.
- **Shared Delay Subroutine (`$271E–$272D`):**
  $$\text{Cycles}(\text{JSR }\$271\text{E}) = 6_{\text{JSR}} + (9 + 1800 \times \text{M}[\$2002]) = 15 + 1800 \times \text{M}[\$2002]\text{ CPU cycles}$$
  - At Record Mode default `M[$2002] = $07`: **`12,615` CPU cycles (`7.1133 ms` PAL)** inside `JSR $271E`, plus **`53–68` CPU cycles** of caller loop-body overhead = **`12,668–12,683` CPU cycles (`7.143–7.152 ms` PAL) per step**.

---

## 4. Complete Instrument Inventory & Verified Timings (`$2002 = $07`, PAL)

| # | ID | UI Label | Key (`CH`) | Routine | Channels | `AUDCTL` | Active Steps (`/9`) | Exact Active Sound Duration (`Cycles` / `ms`) | Total Routine Duration (`Cycles` / `ms`) | CH1 (`$80` 17-Bit Poly Noise) | CH2 (`$A0` Tone / `$80` Noise) | Pre-Loop DAC Pop |
| :---: | --- | --- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | --- | --- | :---: |
| **1** | `rhytmizer_hh_closed` | `1>HH CLOSED` | `'1'` (`$1F`) | `$26CE` | `CH1+CH2` | `$00` | `3 / 9` (`8..6`) | `38,003` cyc (`21.429 ms`) | `113,992` cyc (`64.277 ms`) | `AUDF1=$00`, `AUDC1=$84→$82` (vol `4→2`) | `AUDF2=$08` (`3518.7 Hz`), `AUDC2=$A1` (vol `1`) | None |
| **2** | `rhytmizer_hh_accent` | `2>HH ACCENT` | `'2'` (`$1E`) | `$2798` | `CH1+CH2` | `$00` | `8 / 9` (`8..1`) | `101,355` cyc (`57.151 ms`) | `114,068` cyc (`64.320 ms`) | `AUDF1=$00`, `AUDC1=$88→$81` (vol `8→1`) | `AUDF2=$08` (`3518.7 Hz`), `AUDC2=$A1` (vol `1`) | None |
| **3** | `rhytmizer_snare` | `3>SNARE` | `'3'` (`$1A`) | `$2571` | `CH1+CH2` | `$01` | `9 / 9` (`8..0`) | `114,141` cyc (`64.361 ms`) | `114,173` cyc (`64.379 ms`) | `AUDF1=$2006` (def `$01`), `AUDC1=$88→$80` (vol `8→0`) | `AUDF2=$18→$28` (`+$02`/step, `311.1→189.7 Hz`), `AUDC2=$A9→$A1` (vol `9→1`) | `C2=$1F`, `C1=$1B` (`24` cyc) |
| **4** | `rhytmizer_bass_drum` | `SPACE>BASS DRUM` | `' '` (`$21`) | `$272E` | `CH1+CH2` | `$01` | `2 / 9` (`8..7`) | `25,384` cyc (`14.313 ms`) | `114,000` cyc (`64.282 ms`) | `AUDF1=$02`, `AUDC1=$85` (const vol `5`) | `AUDF2=$5C→$6E` (`+$12`/step, `83.64→70.07 Hz`), `AUDC2=$AC` (const vol `12`) | `C2=$1F`, `C1=$1B` (`22` cyc) |
| **5** | `rhytmizer_tom_1` | `4>TOM 1` | `'4'` (`$18`) | `$28D2` | `CH1+CH2` | `$01` | `5 / 9` (`8..4`) | `63,455` cyc (`35.781 ms`) | `114,093` cyc (`64.334 ms`) | `AUDF1=$01`, `AUDC1=$87→$83` (vol `7→3`) | `AUDF2=$23→$33` (`+$04`/step, `216.1→149.6 Hz`), `AUDC2=$AB→$A7` (vol `11→7`) | `C2=$1F` (`12` cyc) |
| **6** | `rhytmizer_tom_2` | `5>TOM 2` | `'5'` (`$1D`) | `$2937` | `CH1+CH2` | `$01` | `6 / 9` (`8..3`) | `76,126` cyc (`42.925 ms`) | `114,104` cyc (`64.340 ms`) | `AUDF1=$01`, `AUDC1=$87→$82` (vol `7→2`) | `AUDF2=$32→$46` (`+$04`/step, `152.5→109.6 Hz`), `AUDC2=$AB→$A6` (vol `11→6`) | `C2=$1F` (`12` cyc) |
| **7** | `rhytmizer_tom_3` | `6>TOM 3` | `'6'` (`$1B`) | `$299C` | `CH1+CH2` | `$01` | `7 / 9` (`8..2`) | `88,814` cyc (`50.080 ms`) | `114,136` cyc (`64.358 ms`) | `AUDF1=$01`, `AUDC1=$87→$81` (vol `7→1`) | `AUDF2=$3C→$54` (`+$04`/step, `127.5→91.5 Hz`), `AUDC2=$AB→$A5` (vol `11→5`) | `C2=$1F` (`12` cyc) |
| **8** | `rhytmizer_wood_block` | `7>WOOD BLOCK` | `'7'` (`$33`) | `$2844` | `CH1+CH2` | `$00` | `3 / 9` (`8..6`) | `38,000` cyc (`21.427 ms`) | `113,982` cyc (`64.271 ms`) | `AUDF1=$07` (`7917.2 Hz` clk), `AUDC1=$85→$83` (vol `5→3`) | `AUDF2=$14` (`3016.1 Hz` clk), `AUDC2=$85→$83` (poly17 noise, vol `5→3`) | None |
| **9** | `rhytmizer_claps` | `8>CLAPS` | `'8'` (`$35`) | `$27F3` | `CH1` *(CH2 bug)* | `$00` | `8 / 9` (`8..1`) | `101,345` cyc (`57.146 ms`) | `114,042` cyc (`64.305 ms`) | `AUDF1=$12` (`3333.5 Hz` clk), `AUDC1=$88→$81` (vol `8→1`) | `AUDF2=$1E` written, but `$2821` writes `STA $D5EB` so `AUDC2=$00` | None |
| — | *(Rest)* | `*>SKIP A BEAT` | `'*'` (`$07`) | `$2895` | Muted | `$00` | `0 / 9` | `0` cyc (`0.000 ms`) | `113,922` cyc (`64.238 ms`) | `AUDC1=$00` | `AUDC2=$00` | None |

---

## 5. Synthesis Techniques Identified

1. **Counter-Added Linear `AUDC` Volume Envelopes (`LDA #base / ADC $2000`):** Computes both distortion bits and linear volume decay inline in 3 instructions without lookup tables.
2. **Simultaneous Noise (`CH1` `$80`) + Downward Pitch-Swept Pure Tone (`CH2` `$A0`) Layering:** Used in `Snare`, `Bass Drum`, and `Toms 1–3` under `AUDCTL = $01` (`15.56 kHz` PAL clock).
3. **High-Frequency Metallic Sheen Underlay (`AUDF2=$08, AUDC2=$A1`):** Adds a quiet `3,518.7 Hz` (`vol=1`) pure tone underneath `CH1` white noise (`AUDF1=$00`) in `HH Closed` and `HH Accent`.
4. **Dual Inharmonic Sample-and-Hold Poly17 Interference (`7>WOOD BLOCK`):** Clocks `$80` (17-bit LFSR) on both `CH1` (`AUDF1=$07`) and `CH2` (`AUDF2=$14`) simultaneously under `AUDCTL=$00` (`21:8` period ratio).
5. **Downsampled 17-Bit LFSR Band-Limited Clap Texture (`8>CLAPS`):** Clocks `$80` at `AUDF1=$12` (`3,333.5 Hz` sample-and-hold rate) over 8 steps (`57.15 ms`, `vol 8→1`).
6. **Microsecond Volume-Only DAC Attack Transients (`$1F` / `$1B`):** `12–24` CPU-cycle (`6.8–13.5 µs`) DAC writes before step 0 on `Snare`, `Bass Drum`, and `Toms 1–3`.

---

## 6. Representative Disassembly Excerpts

See [`docs/reverse_engineering/rhytmizer_disassembly.asm`](rhytmizer_disassembly.asm) for the complete 1,185-line annotated disassembly of all executable segments (`$4300–$432A`, `$0706–$0798`, `$B800–$B80F`, and `$2540–$2E5C`).

---

## 7. Reconstructed POKEY Register Sequences & Audio Reconstruction Methodology

- **Cycle-Accurate Register Traces (`docs/reverse_engineering/instruments/*.json`):** 100% exact hardware register write logs (`cpu_cycle`, `time_ms_pal`, `pc`, `register`, `address`, `value`) captured directly from `py65` execution of `rhytmizer.xex`.
- **Phase E Software-Synthesized WAVs (`docs/reverse_engineering/instruments/*.wav`):** Rendered via `render_cycle_accurate_pokey_to_wav()` (a sub-frame cycle-interval extension of `src/atari_music/pokey_synth.py`), and independently benchmarked against **`ASAP 8.0.0` (`tools/asap_all/asapconv.exe`, SAP `TYPE D`)** running the original 6502 machine code. See [`docs/reverse_engineering/rhytmizer_verification_report.md`](rhytmizer_verification_report.md) Section 6 for the complete methodology comparison, per-instrument normalization differences (`0.90` normalized peak in `pokey_synth` vs. absolute hardware amplitude in `ASAP 8.0.0`), and envelope correlation table (`r = 0.79–0.94`).

---

## 8. Revised Compatibility Assessment Summary (Modes A, B, C, D)

| Instrument ID | Original Name | Mode B: Single-Channel 50 Hz (`AUDCTL=$00`) | Mode C1: Dual-Channel 50 Hz (`AUDCTL=$00` Converted) | Mode C2: Dual-Channel 50 Hz (`AUDCTL=$01`/`$29` 15 kHz) | Mode D: Dedicated Sub-Frame (`150 Hz`, 2-Ch, `$00`/`$01`) | Recommended Classification |
| --- | --- | :---: | :---: | :---: | :---: | :---: |
| **`rhytmizer_claps`** | `8>CLAPS` | **`DIRECT` (`~92%`, 1-ch native)** | Identical (`~92%`) | N/A (`AUDCTL=$00` native) | Near-Exact (`~99%`) | **`DIRECT` (Mode B)** |
| **`rhytmizer_hh_closed`** | `1>HH CLOSED` | **`DIRECT` (`~85%`, omits `vol=1` ring)** | **`EXTENDED` (`~93%`, `0%` freq err)** | N/A (`AUDCTL=$00` native) | Near-Exact (`~99%`) | **`DIRECT` (Mode B)** / **`EXTENDED` (Mode C1)** |
| **`rhytmizer_hh_accent`** | `2>HH ACCENT` | **`DIRECT` (`~90%`, omits `vol=1` ring)** | **`EXTENDED` (`~95%`, `0%` freq err)** | N/A (`AUDCTL=$00` native) | Near-Exact (`~99%`) | **`DIRECT` (Mode B)** / **`EXTENDED` (Mode C1)** |
| **`rhytmizer_wood_block`** | `7>WOOD BLOCK` | Approx (`~65%`, interleaved) | **`EXTENDED` (`~92%`, `0%` freq err)** | N/A (`AUDCTL=$00` native) | Near-Exact (`~99%`) | **`EXTENDED` (Mode C1)** |
| **`rhytmizer_snare`** | `3>SNARE` | Approx (`~55%`, interleaved) | **`EXTENDED` (`~82%`, `<0.35%` tone err)** | **`EXTENDED` (`~85%`, `0%` freq err)** | Near-Exact (`~98%`) | **`EXTENDED` (Mode C1/C2)** |
| **`rhytmizer_tom_1`** | `4>TOM 1` | Approx (`~60%`, 1-layer) | **`EXTENDED` (`~82%`, `<0.29%` tone err)** | **`EXTENDED` (`~84%`, `0%` freq err)** | Near-Exact (`~98%`) | **`EXTENDED` (Mode C1/C2)** |
| **`rhytmizer_tom_2`** | `5>TOM 2` | Approx (`~52%`, tail clips `+13%`) | **`EXTENDED` (`~75%`, tail clips `+13%`)** | **`EXTENDED` (`~85%`, `0%` freq err)** | Near-Exact (`~98%`) | **`EXTENDED` (Mode C2 preferred)** |
| **`rhytmizer_tom_3`** | `6>TOM 3` | Poor (`~35%` `$A0` clips `+35%`; `~45%` `$C0` buzz) | Poor Pitch (`$A0` clips at `124 Hz`) | **`EXTENDED` (`~85%`, `0%` freq err)** | **`CUSTOM` (`~98%`)** | **`CUSTOM` / `EXTENDED (Mode C2 15 kHz required)`** |
| **`rhytmizer_bass_drum`** | `SPACE>BASS DRUM` | Poor (`~30%` `$A0` clips `+77%`; `~45%` `$C0` buzz) | Poor Pitch (`$A0` clips at `124 Hz`) | **`EXTENDED` (`~70%`, `20–40 ms` vs `14.3 ms`)** | **`CUSTOM` (`~98%`)** | **`CUSTOM` (for `14.3 ms` 2-step `$A0` sub-bass)** |

---

## 9. Technical Limitations & Unresolved Questions

1. **Historical Origin of `$2821: STA $D5EB` (`8D EB D5`) in `8>CLAPS`:** Confirmed present in the binary at file offset `0x08EF–0x08F1`; whether it was an accidental corruption of `STA $D203` (`8D 03 D2`) or an intentional patch to silence Channel 2 remains a historical question.
2. **Swapped UI Labels for Snare Pitch (`$2006`) vs. Snare Tone (`$2005`):** Confirmed in code (`$2B19–$2B2A` vs. `$2B34–$2B51`) that Up/Down (`CH=$0E/$0F`) tunes `$2005` (`CH2` pure-tone sweep base `AUDF2`) whereas Ctrl+Up/Down (`CH=$8E/$8F`) tunes `$2006` (`CH1` noise clock divider `AUDF1`).
3. **50 Hz VBI Temporal Quantization & 8-Bit 64 kHz Pure-Tone Floor (`123.71 Hz`):** In a 50 Hz VBI engine (`20.0 ms`/frame) running at `AUDCTL=$00` (`63.34 kHz` PAL clock), 8-bit `$A0` pure tone cannot reach below `123.71 Hz` (`124.19 Hz` at tracker max `$FE`) and cannot resolve a `14.31 ms` 2-step pitch drop within a single `20.0 ms` frame.

---

## 10. Recommendations for Next Implementation Stage

1. **Tier 1 (`DIRECT` Single-Channel 50 Hz `AUDCTL=$00` Profiles):** Add `8>CLAPS`, `1>HH CLOSED`, and `2>HH ACCENT` to `data/instruments/catalog.json` as single-channel `core_v2_iter1` percussion profiles using `TransientMacroSpec`.
2. **Tier 2 (`EXTENDED` Dual-Channel 50 Hz Paired Percussion Profiles):** Support paired dual-channel percussion triggers (`CH1` `$80` noise + `CH2` `$A0` pure-tone sweep / secondary noise) so `7>WOOD BLOCK`, `3>SNARE`, and `4>TOM 1` can be played under `AUDCTL=$00` (with `<0.35%` tone frequency error), and `5>TOM 2` / `6>TOM 3` can be played with full downward pitch range when `AUDCTL` Bit 0 (`$01` or `$29`) is enabled.
3. **Tier 3 (`CUSTOM` Sub-Frame `150 Hz` Drum Mode or Per-Step `AUDCTL` Override):** For faithful reproduction of `SPACE>BASS DRUM` (`14.31 ms` 2-step `83.6→70.1 Hz` `$A0` sub-bass drop) and mixed `$00`/`$01` drum kits within a single track, introduce either a per-macro-step `AUDCTL` bit-0 flag or an optional `3×`/frame (`150 Hz`) DLI/Timer update tick.

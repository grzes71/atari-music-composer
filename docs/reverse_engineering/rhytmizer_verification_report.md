# Phase H — Independent Technical Verification and Correction Report (`rhytmizer.xex`)

- **Target Binary:** `rhytmizer.xex` (`6,333` bytes, SHA-256: `d22206b9324ff5f9a13eaba213009aeb3d6df6d69bb56c1fdbf48cc41045c772`)
- **Verification Scope:** Independent technical audit of all Phase A–G reverse-engineering claims, POKEY hardware register semantics (`AUDCTL`), frequency divider conversion math (`15 kHz ↔ 64 kHz`), CPU cycle timing calculations, Phase E WAV audio synthesis methodology vs. reference `ASAP 8.0.0` POKEY emulation, dynamic trace consistency against raw machine code, and Atari Music Composer compatibility classification.
- **Scope Constraint:** Strictly a technical verification and documentation correction task. Zero changes made to `rhytmizer.xex` or production Atari Music Composer code.

---

## 1. Confirmed Findings (Verified Against Original Binary & `py65` Execution)

The following findings from Phases A–E were independently re-verified against the raw bytes of `rhytmizer.xex` and cycle-stepped 6502 execution:

1. **XEX Segment Layout & Two-Stage Relocation Pipeline (`Confirmed`):**
   - Segment 0 (`file 0x0002–0x1885` → `$2A80–$42FF`, `6,272` B), Segment 1 (`file 0x1888–0x18B6` → `$4300–$432A`, `43` B), Segment 2 (`file 0x18B7–0x18BC` → `$02E0–$02E1`, `RUNAD = $4300`).
   - Stage 1 (`$4300–$432A`) copies 25 pages (`$1900` bytes) from `$2A80–$437F` to `$0700–$1FFF` and calls `JSR $0706`.
   - Stage 2 (`$0706–$0798`) reads 17 backward block-copy descriptors from `$079F–$0804` (`count = $11` at `$0700`), unpacking the splash screen to `$B800–$BBEF` (`1,008` B) and the main program/UI/demo pattern to `$200B–$333B` (`4,913` B), then executes `JSR $B800` and `JMP $2540`.
2. **Complete Inventory of Playable Percussion Routines (`Confirmed`):**
   - Exactly **9 playable percussion routines** plus **1 silent rest routine** exist in the executable code (`$2540–$2E5C`) and built-in 1,246-step demonstration pattern (`$2E5D–$333B`, terminated by `$64`):
     - `1>HH CLOSED` (`$26CE`, key `'1'`, `CH=$1F`)
     - `2>HH ACCENT` (`$2798`, key `'2'`, `CH=$1E`)
     - `3>SNARE` (`$2571`, key `'3'`, `CH=$1A`)
     - `SPACE>BASS DRUM` (`$272E`, key `'SPACE'`, `CH=$21`)
     - `4>TOM 1` (`$28D2`, key `'4'`, `CH=$18`)
     - `5>TOM 2` (`$2937`, key `'5'`, `CH=$1D`)
     - `6>TOM 3` (`$299C`, key `'6'`, `CH=$1B`)
     - `7>WOOD BLOCK` (`$2844`, key `'7'`, `CH=$33`)
     - `8>CLAPS` (`$27F3`, key `'8'`, `CH=$35`)
     - `*>SKIP A BEAT` (`$2895`, key `'*'`, `CH=$07`)
3. **Synchronous Main-Thread Execution & Zero Interrupts (`Confirmed`):**
   - No VBI, DLI, or POKEY Timer IRQ vectors are read or modified.
   - Every instrument executes a 9-step software loop (`$2000 = 8..0`) calling `JSR $271E` once per step.
4. **All 88 POKEY Register Write Instructions & Dynamic Trace Sequences (`Confirmed`):**
   - Every event in `docs/reverse_engineering/instruments/*.json` matches the disassembled instruction stream byte-for-byte (`PC`, register address, written value, and cumulative CPU cycle count).
5. **Original Coding Bug at `$2821` in `8>CLAPS` (`Confirmed`):**
   - In `rhytmizer.xex` at file offset `0x08EF–0x08F1` (which relocates to Stage 1 `$0FE9–$0FEB` and Stage 2 runtime address **`$2821–$2823`**), the raw bytes are **`8D EB D5`** (`STA $D5EB`).
   - Context at `$2818–$282D`:
     ```asm
     $2818: 18        CLC
     $2819: A9 80     LDA #$80
     $281B: 6D 00 20  ADC $2000       ; A = $88..$81
     $281E: 8D 01 D2  STA $D201       ; AUDC1 = $88..$81
     $2821: 8D EB D5  STA $D5EB       ; Writes to cartridge space $D5EB instead of $D203 (AUDC2)
     $2824: A9 12     LDA #$12
     $2826: 8D 00 D2  STA $D200       ; AUDF1 = $12
     $2829: A9 1E     LDA #$1E
     $282B: 8D 02 D2  STA $D202       ; AUDF2 = $1E
     ```
   - Because `$D5EB` is unmapped cartridge control memory (`CCTL`), `AUDC2 ($D203)` is never given a non-zero volume during `TRIG_CLAPS`, even though `AUDF2 ($D202)` is loaded with `$1E` at `$282B` and `AUDC2 ($D203)` is explicitly cleared to `$00` on step 0 (`$280F`) and exit (`$2840`).

---

## 2. Corrected Findings & Inaccurate or Unsupported Claims Audited

| # | Location in Phase A–G Docs | Previous Claim / Statement | Technical Correction & Verification Finding | Impact on Composer Integration |
| :---: | --- | --- | --- | --- |
| **C-1** | `rhytmizer_compatibility.md` §3, `RHYTMIZER_RESEARCH_REPORT.md` §1, §8 | Described `AUDCTL=$01` → `AUDCTL=$00` converted `AUDF` dividers (`AUDF1=$07` for `$01`, `AUDF2=$65..$A6` for Snare, `AUDF2=$92..$D3` for Tom 1) as *"exact 8-bit equivalent dividers"* / *"exact 64 kHz translated dividers"*. | **Not mathematically exact.** Because the PAL clock divisor ratio is $\frac{114}{28} = \frac{57}{14} \approx 4.071429$ (non-integer), $(N_{15} + 1) \times \frac{57}{14} - 1$ is **only an integer when $(N_{15} + 1)$ is a multiple of 14** (e.g., $N_{15} = 13, 27, 41, 55, 69$). None of the original `AUDF` values in Snare, Bass Drum, or Toms 1–3 satisfy $(N_{15}+1) \equiv 0 \pmod{14}$. Every converted 64 kHz divider is a **nearest-integer approximation** with relative error ranging from **`0.032%` to `1.786%`** for in-range values (and **`+3.38%` to `+76.54%`** where clamped at `$FF`/`$FE`). All occurrences of *"exact"* for these conversions have been corrected to *"nearest 8-bit approximation"* with full error tables (Section 4). | Frequency approximations for Snare and Tom 1 are within `< 0.35%` (`< 6.1` cents) for CH2 pure tone and `+1.786%` (`+30.6` cents) for CH1 noise clock (`$01 -> $07`), which is musically close for percussion, whereas Bass Drum and Tom 3 clip severely under 8-bit 64 kHz `$A0` pure tone. |
| **C-2** | `rhytmizer_sound_engine.md` §1, §2.2–2.7 (`63.92 kHz` / `15.70 kHz` numbers) | Used nominal textbook PAL base clock approximations (`63,920.4 Hz` and `15,699.8 Hz`) in prose paragraphs of `rhytmizer_sound_engine.md`, while `rhytmizer_compatibility.md` used exact PAL constants (`63,337.39 Hz` and `15,556.55 Hz`). | **Standardized on exact PAL hardware clock divisors** matching `atari_music.constants` and `atari800`: $f_{\text{CPU,PAL}} = 1,773,447.0\text{ Hz}$, $f_{64\text{kHz}} = \frac{1,773,447}{28} = \mathbf{63,337.3929\text{ Hz}}$, and $f_{15\text{kHz}} = \frac{1,773,447}{114} = \mathbf{15,556.5526\text{ Hz}}$. | Eliminates a `~0.9%` discrepancy between prose frequency citations in Phase C and calculated tables in Phase F/H. |
| **C-3** | `rhytmizer_code_analysis.md` §3.3, `rhytmizer_sound_engine.md` §2.1 (`12,615` vs `12,670` cycles) | Cited `12,615` CPU cycles for `$271E` in §2.1 and `~12,670` CPU cycles per step in §1 without explicitly breaking down the `53–68` cycle difference. | **Reconciled with exact cycle accounting (Section 5):** `JSR $271E` + `DELAY_TEMPO_STEP` (`$271E–$272D`) consumes **exactly `12,615` CPU cycles** at `$2002 = $07` (`12,609` cycles inside `$271E` including `RTS`, plus `6` cycles for caller `JSR $271E`). The remaining **`53 to 68` CPU cycles per iteration** are consumed by the caller's surrounding step loop body (POKEY register writes, `$2000` counter comparison/decrement, and loop branch), yielding **`12,668` to `12,683` total CPU cycles between consecutive step updates**. | Clarifies exact sub-frame step timing (`7.143–7.152 ms` PAL per step, `64.271–64.379 ms` total per 9-step trigger). |
| **C-4** | `rhytmizer_compatibility.md` §2, §3 (`$C0` `poly4` substitution for Tom 3 and Bass Drum) | Suggested substituting `$C0` (`poly4` 4-bit LFSR distortion) at 64 kHz to reach `70–120 Hz` fundamentals for `SPACE>BASS DRUM` and `6>TOM 3` under `AUDCTL=$00`. | **Explicit Timbre Warning Added:** Changing `AUDC2` from `$A0` (pure square wave) to `$C0` (15-step 4-bit polynomial LFSR) reaches the target fundamental pitch (`70–120 Hz`) under `AUDCTL=$00`, but **fundamentally alters the harmonic spectrum and timbre** from a clean sinusoidal/square drum body to a gritty, buzzy pulse train with strong odd/even subharmonics. It is a **timbral substitution**, not a transparent frequency translation. | Prevents misclassifying `$C0` bass drum / low tom substitutions as timbrally faithful reproductions of Rhytmizer's `$A0` pure-tone body. |
| **C-5** | `RHYTMIZER_RESEARCH_REPORT.md` §7 (Phase E WAV provenance) | Described Phase E `.wav` files as *"rendered from captured POKEY register sequences"* without detailing the internal signal model of `render_cycle_accurate_pokey_to_wav()` or comparing against a reference C/C++ POKEY emulator (`ASAP 8.0.0`). | **Full Audio Methodology Audit & `ASAP 8.0.0` Comparison Completed (Section 6):** Documented all 7 aspects of the custom Python box-integrating POKEY synthesizer (`pokey_synth.py` + `generate_phase_e.py`) and benchmarked all 9 instruments against **`ASAP 8.0.0` (`asapconv.exe`, SAP `TYPE D`)** running the actual 6502 machine code from `rhytmizer.xex`. Identified two subtle modeling differences in `generate_phase_e.py` (unipolar vs. AC-coupled Volume-Only `$10` DAC steps and timer phase continuity when `AUDF` changes). | Distinguishes cycle-accurate register traces (`100%` exact) from Python software synthesis (`pokey_synth`) and reference `ASAP 8.0.0` hardware emulation. |

---

## 3. `AUDCTL` Register Semantics Verification (`$D208`)

### 3.1 Verification of `AUDCTL` Hardware Bit Definitions
We verified the hardware bit layout of `AUDCTL ($D208)` against three authoritative primary sources:
1. **Atari Inc., *CO12294 POKEY Data Sheet* / *Atari 400/800 Hardware Manual* (Section II.5, Audio Control Register `AUDCTL` `$D208`)**
2. **Atari Inc., *De Re Atari* (Chapter 7, Sound)**
3. **Reference POKEY Silicon Emulators (`atari800` `pokeysnd.c` / `mzpokeysnd.c`, `ASAP 8.0.0` `asap.c`, and `src/atari_music/pokey_hw.py` lines 178–218)**

| `AUDCTL` Bit | Hex Mask | Hardware Function (Authoritative POKEY Specification) | Channels Affected |
| :---: | :---: | --- | --- |
| **Bit 0** | **`$01`** | **15 kHz / 64 kHz Base Clock Select:** `0` = 64 kHz base clock (`CPU ÷ 28` ≈ `63.34 kHz` PAL); `1` = 15 kHz base clock (`CPU ÷ 114` ≈ `15.56 kHz` PAL). **POKEY contains only ONE shared 64 kHz / 15 kHz polynomial prescaler counter** feeding the base clock line of all channels that use the base clock. | **CH1, CH2, CH3, CH4** *(except any channel explicitly switched to the 1.79 MHz CPU clock via Bit 6 or Bit 5)* |
| **Bit 1** | **`$02`** | **High-Pass Filter CH2 by CH4:** Inserts high-pass XOR D-latch into **Channel 2**, clocked by **Channel 4** timer underflows. *(Does NOT select a 15 kHz base clock for CH3/CH4.)* | **CH2** (filtered by **CH4**) |
| **Bit 2** | **`$04`** | **High-Pass Filter CH1 by CH3:** Inserts high-pass XOR D-latch into **Channel 1**, clocked by **Channel 3** timer underflows. | **CH1** (filtered by **CH3**) |
| **Bit 3** | **`$08`** | **Join CH3 + CH4 into 16-Bit Counter:** Clocks Channel 4 from Channel 3 underflows (`AUDF3` = LSB, `AUDF4` = MSB). | **CH3 + CH4** |
| **Bit 4** | **`$10`** | **Join CH1 + CH2 into 16-Bit Counter:** Clocks Channel 2 from Channel 1 underflows (`AUDF1` = LSB, `AUDF2` = MSB). | **CH1 + CH2** |
| **Bit 5** | **`$20`** | **Clock CH3 at 1.79 MHz (`1.77 MHz` PAL):** Disconnects **Channel 3** (and **CH3+CH4** when Bit 3 `$08` is also set) from the shared 64 kHz/15 kHz base clock and clocks it directly from the $\Phi_2$ CPU clock (`1.773447 MHz` PAL). | **CH3** (or **CH3+CH4** if Bit 3 `$08` is set) |
| **Bit 6** | **`$40`** | **Clock CH1 at 1.79 MHz (`1.77 MHz` PAL):** Disconnects **Channel 1** (and **CH1+CH2** when Bit 4 `$10` is also set) from the shared 64 kHz/15 kHz base clock and clocks it directly from the $\Phi_2$ CPU clock (`1.773447 MHz` PAL). | **CH1** (or **CH1+CH2** if Bit 4 `$10` is set) |
| **Bit 7** | **`$80`** | **9-Bit / 17-Bit Polynomial Select:** `0` = 17-bit LFSR (`131,071` states); `1` = 9-bit LFSR (`511` states). | Global `$00` / `$80` noise |

> [!IMPORTANT]
> **Critical Clarification on `AUDCTL` Bit 0 (`$01`) vs. Bit 1 (`$02`) and Bit 5 (`$20`):**
> - In real POKEY silicon (`CO12294`), **Bit 0 (`$01`)** switches the chip's single shared base-clock prescaler between `÷28` (`64 kHz`) and `÷114` (`15 kHz`). **Bit 1 (`$02`) is the Channel 2 / Channel 4 High-Pass Filter enable (`AUDCTL_HIPASS_CH2_CH4`), NOT an independent 15 kHz clock selector for Channels 3 and 4.**
> - However, **`AUDCTL = $01` does NOT unconditionally force Channels 3 and 4 to run at 15 kHz!** Specifically, **Bit 5 (`$20`, `AUDCTL_CH3_179MHZ`)** (and **Bit 3 + Bit 5 (`$28`, 16-bit CH3+CH4 at 1.79 MHz)**) clocks Channel 3 (or the joined CH3+CH4 16-bit pair) directly from the **1.77 MHz CPU clock**, completely bypassing the Bit 0 (`64 kHz / 15 kHz`) base-clock prescaler!
> - Therefore, describing `AUDCTL = $01` as *"unconditionally switching all four channels to 15 kHz without exception"* is incomplete:
>   1. **In `rhytmizer.xex` itself:** Rhytmizer writes `AUDCTL = $01` (with Bits 5 and 3 clear) and only ever uses **Channels 1 and 2** (`$D200–$D203`); Channels 3 and 4 (`$D204–$D207`) are unused (`$00`).
>   2. **In Atari Music Composer:** How `AUDCTL` bit 0 (`$01`) affects Channels 3 and 4 depends on the clocking mode of Channels 3 and 4, as answered in detail below.

### 3.2 Answers to the 5 Composer Channel & `AUDCTL` Architecture Questions

1. **Which Composer channels are affected by Rhytmizer's `AUDCTL = $01`?**
   - **Directly used by Rhytmizer:** Only **Channel 1** (`AUDF1/AUDC1`) and **Channel 2** (`AUDF2/AUDC2`).
   - **Clocking impact of setting `AUDCTL` Bit 0 (`$01`):** Any channel clocked from POKEY's shared base-clock prescaler (i.e., any channel **not** using Bit 6 `$40` [CH1 1.79 MHz] or Bit 5 `$20` [CH3 1.79 MHz]) has its clock divided by `114` (`15.56 kHz` PAL) instead of `28` (`63.34 kHz` PAL).
2. **Can Channels 3 and 4 continue melodic playback without frequency changes when `AUDCTL` Bit 0 (`$01`) is active?**
   - **Case A — Standard 8-bit base-clocked CH3 and CH4 (`AUDCTL` Bits 5 & 3 = `0`):** If CH3 and CH4 rely on the 64 kHz base clock (`preferred_clock_hz = "64khz"`), setting `AUDCTL` Bit 0 (`$01`) lowers their base clock from `63.34 kHz` to `15.56 kHz` (`÷4.0714`). To play melodic notes on 8-bit CH3/CH4 while `AUDCTL` Bit 0 = `1` without pitch shift, their `AUDF3`/`AUDF4` lookup table must use 15 kHz dividers (`audf_from_hz_8bit(freq_hz, audctl=0x01)`), which supports melodic notes from **`30.5 Hz` (`AUDF=$FE`, ~B0) up to `972 Hz` (`AUDF=$07`, ~B5)** with `< 3.5%` quantization step at the top of the range.
   - **Case B — Joined 16-bit CH3+CH4 clocked at 1.79 MHz (`AUDCTL = $28` + `$01` = `$29`):** When `AUDCTL` Bits 5 (`$20`) and 3 (`$08`) are set (`divider_mode = "16bit_ch34"` at 1.79 MHz), **CH3+CH4 is clocked directly from the 1.77 MHz CPU clock and is 100% immune to `AUDCTL` Bit 0 (`$01`)!** In `AUDCTL = $29`, CH1 and CH2 run at the **15 kHz base clock** (for Rhytmizer percussion) while CH3+CH4 plays **16-bit 1.79 MHz melody/bass with zero frequency change!**
   - **Case C — Translating Rhytmizer percussion from `AUDCTL=$01` to `AUDCTL=$00` (64 kHz base clock):** Conversely, if `AUDCTL` is kept at `$00` (or `$50` for 16-bit CH1+CH2 bass), CH3 and CH4 continue standard 64 kHz 8-bit melodic playback with zero changes, and the Rhytmizer percussion dividers are converted to 64 kHz (`AUDF_64 ≈ (AUDF_15 + 1) * 57/14 - 1`).
3. **Can Channels 1 and 2 be reserved for percussion while Channels 3 and 4 handle melody?**
   - **Yes, at the hardware level:** POKEY allows CH1 and CH2 to run independent 8-bit percussion layers (at either 15 kHz `AUDCTL=$01`/`$29` or 64 kHz `AUDCTL=$00`), while CH3 and CH4 play two 8-bit melodic tracks (or one 16-bit high-precision melodic track under `AUDCTL=$29`).
4. **Does the existing Atari Music Composer player architecture (`player.asm` + `POKEYRuntime`) permit such allocation?**
   - **`player.asm` (6502 engine):** `player.asm` treats all 4 channels (`X = 0..3` for CH1..CH4) symmetrically for 8-bit instruments, ADSR envelopes, `TransientMacroSpec`, and `PitchEnvelopeSpec`, and loads one song-wide `audctl_mode` byte from the song header (`ldy #1 / lda (zp_tmp_ptr),y / sta audctl_mode`). Thus `player.asm` **already supports** putting percussion on CH1+CH2 and melody on CH3+CH4 under a static song-wide `audctl_mode` (`$00` or `$01`).
   - **`POKEYRuntime` (`src/atari_music/instruments/runtime.py`) & Planner (`planner.py`):**
     - Currently, `POKEYRuntime.resolve()` computes a **single static song-wide `effective_audctl`** by taking the bitwise OR of `required_audctl_bits` across all 4 channels and checking against `forbidden_audctl_bits`.
     - Existing melodic catalog profiles (`data/instruments/catalog.json`) specify `preferred_clock_hz: "64khz"` and `required_audctl_bits: 0`. If a percussion profile on CH1/CH2 sets `required_audctl_bits: 0x01` (`AUDCTL_15KHZ`), `effective_audctl` becomes `$01` for the entire song, which will cause `frame_simulator.py` and `mads_exporter.py` to compile all 8-bit channels (including CH3 and CH4) using the 15 kHz clock (`hz_from_audf_8bit(audf, audctl=0x01)`).
     - Furthermore, `player.asm` v2 does **not** currently support changing `AUDCTL` dynamically mid-song (e.g., switching `AUDCTL` between `$00` for Hi-Hats/Wood Block/Claps and `$01` for Snare/Bass Drum/Toms on a per-note basis).
5. **Do `AUDCTL` changes introduce additional conflicts with existing instrument configurations?**
   - **Yes — three specific conflicts must be accounted for:**
     1. **Conflict between `AUDCTL = $01` (15 kHz drums) and `AUDCTL = $00` (64 kHz hi-hats/claps/wood block) within the same drum kit:** In `rhytmizer.xex`, the CPU switches `$D208` between `$00` and `$01` at the start of every drum hit. Because `player.asm` v2 uses a single static `audctl_mode` per song, a song cannot mix native `AUDCTL=$00` hi-hats (`AUDF1=$00` at 64 kHz) and native `AUDCTL=$01` bass drum/toms (`AUDF2=$3C..$6E` at 15 kHz) without either translating one group's dividers to the other's clock or adding a per-macro-step `AUDCTL` override flag in a future player version.
     2. **Conflict with 16-bit Joined Bass on CH1+CH2 (`AUDCTL = $50`):** Existing 16-bit bass profiles (`bass_16bit_pure`, `bass_16bit_poly5`) require `AUDCTL = $50` (`CH1+CH2` joined at 1.79 MHz) on Channels 1 and 2, leaving only **Channels 3 and 4** available for melody and percussion (and setting `forbidden_audctl_bits: 0x01` on profiles that require 64 kHz on CH3/CH4).
     3. **Conflict with High-Frequency 8-Bit Melodic Leads (`MIDI > 83 / B5`):** Under `AUDCTL = $01` (15 kHz base clock), the highest 8-bit pure tone (`AUDF = $00`) is `7,778.3 Hz`, and at `AUDF = $0E` (~518 Hz, C5) the semitone step resolution is `~3.3%` (`~56` cents), making 8-bit 15 kHz unsuitable for high-register melodic leads on CH3/CH4 unless CH3 uses 1.79 MHz (`AUDCTL` Bit 5 `$20`).

---

## 4. Mathematical Verification of Frequency Divider Conversions (`AUDCTL=$01` → `AUDCTL=$00`)

### 4.1 Mathematical Proof That No `AUDCTL=$01` → `AUDCTL=$00` Conversion in Rhytmizer Is Exact
- Under `AUDCTL = $01` (15 kHz base clock on PAL, $f_{15} = \frac{f_{\text{CPU}}}{114} = 15,556.5526\text{ Hz}$), an 8-bit divider $N_{15} \in [0, 255]$ produces timer underflows every:
  $$T_{15}(N_{15}) = 114 \times (N_{15} + 1)\text{ CPU cycles}$$
  and a pure-tone output frequency (half the timer underflow rate) of:
  $$f_{15}(N_{15}) = \frac{f_{\text{CPU}}}{2 \times 114 \times (N_{15} + 1)} = \frac{15,556.5526\text{ Hz}}{2 \times (N_{15} + 1)}$$
- Under `AUDCTL = $00` (64 kHz base clock on PAL, $f_{64} = \frac{f_{\text{CPU}}}{28} = 63,337.3929\text{ Hz}$), an 8-bit divider $N_{64} \in [0, 255]$ produces timer underflows every:
  $$T_{64}(N_{64}) = 28 \times (N_{64} + 1)\text{ CPU cycles}$$
  and a pure-tone output frequency of:
  $$f_{64}(N_{64}) = \frac{f_{\text{CPU}}}{2 \times 28 \times (N_{64} + 1)} = \frac{63,337.3929\text{ Hz}}{2 \times (N_{64} + 1)}$$
- For $f_{64}(N_{64}) = f_{15}(N_{15})$ to hold **exactly**, we require:
  $$28 \times (N_{64} + 1) = 114 \times (N_{15} + 1) \iff N_{64} + 1 = \frac{57}{14} \times (N_{15} + 1)$$
  Since $\gcd(57, 14) = 1$, $N_{64}$ is an integer **if and only if $(N_{15} + 1)$ is an integer multiple of $14$** ($N_{15} \in \{13, 27, 41, 55, 69, \dots\}$).
- **None** of the `AUDF1` (`$01, $02`) or `AUDF2` (`$18..$2A`, `$5C, $6E`, `$23..$33`, `$32..$46`, `$3C..$54`) values used by Rhytmizer's `AUDCTL=$01` instruments satisfy $(N_{15} + 1) \equiv 0 \pmod{14}$. Therefore, **every single converted divider under `AUDCTL=$00` is a mathematical approximation, never exact.**

### 4.2 Complete Master Frequency Conversion Table (`AUDCTL=$01` → `AUDCTL=$00`, PAL `1,773,447 Hz`)

*(Note: For `CH1` `$80` 17-bit poly noise, the table reports the half-clock reference frequency $f = \frac{f_{\text{base}}}{2(N+1)}$; the actual timer underflow / LFSR sample-and-hold clock rate is $2f = \frac{f_{\text{base}}}{N+1}$, which has the exact same relative percentage error.)*

| Instrument | Original `AUDF` | Original Frequency | Converted `AUDF` (`8-bit` / Tracker) | Converted Frequency | Absolute Error (`Hz`) | Error (`%`) |
| --- | :---: | :---: | :---: | :---: | :---: | :---: |
| **`3>SNARE` (CH1 `$80` noise clock)** | `$01` (`1`) | `3889.14 Hz` *(clock `7778.28 Hz`)* | `$07` (`7`) | `3958.59 Hz` *(clock `7917.17 Hz`)* | `+69.45 Hz` *(clock `+138.90 Hz`)* | **`+1.786%`** |
| **`3>SNARE` (CH2 `$A0` tone step 0, def `$2005=$16`)** | `$18` (`24`) | `311.13 Hz` | `$65` (`101`) | `310.48 Hz` | `-0.65 Hz` | **`-0.210%`** |
| **`3>SNARE` (CH2 `$A0` tone step 1)** | `$1A` (`26`) | `288.08 Hz` | `$6D` (`109`) | `287.90 Hz` | `-0.19 Hz` | **`-0.065%`** |
| **`3>SNARE` (CH2 `$A0` tone step 2)** | `$1C` (`28`) | `268.22 Hz` | `$75` (`117`) | `268.38 Hz` | `+0.16 Hz` | **`+0.061%`** |
| **`3>SNARE` (CH2 `$A0` tone step 3)** | `$1E` (`30`) | `250.91 Hz` | `$7D` (`125`) | `251.34 Hz` | `+0.43 Hz` | **`+0.170%`** |
| **`3>SNARE` (CH2 `$A0` tone step 4)** | `$20` (`32`) | `235.71 Hz` | `$85` (`133`) | `236.33 Hz` | `+0.63 Hz` | **`+0.267%`** |
| **`3>SNARE` (CH2 `$A0` tone step 5)** | `$22` (`34`) | `222.24 Hz` | `$8E` (`142`) | `221.46 Hz` | `-0.78 Hz` | **`-0.350%`** |
| **`3>SNARE` (CH2 `$A0` tone step 6)** | `$24` (`36`) | `210.22 Hz` | `$96` (`150`) | `209.73 Hz` | `-0.50 Hz` | **`-0.237%`** |
| **`3>SNARE` (CH2 `$A0` tone step 7)** | `$26` (`38`) | `199.44 Hz` | `$9E` (`158`) | `199.17 Hz` | `-0.27 Hz` | **`-0.135%`** |
| **`3>SNARE` (CH2 `$A0` tone step 8)** | `$28` (`40`) | `189.71 Hz` | `$A6` (`166`) | `189.63 Hz` | `-0.08 Hz` | **`-0.043%`** |
| **`3>SNARE` (CH2 `$A0` demo `$2005=$18` step 8)** | `$2A` (`42`) | `180.89 Hz` | `$AE` (`174`) | `180.96 Hz` | `+0.07 Hz` | **`+0.041%`** |
| **`SPACE>BASS DRUM` (CH1 `$80` noise clock)** | `$02` (`2`) | `2592.76 Hz` *(clock `5185.52 Hz`)* | `$0B` (`11`) | `2639.06 Hz` *(clock `5278.12 Hz`)* | `+46.30 Hz` *(clock `+92.60 Hz`)* | **`+1.786%`** |
| **`SPACE>BASS DRUM` (CH2 `$A0` tone step 0)** | `$5C` (`92`) | `83.64 Hz` | `$FF` (`255`, clamped from `$17A=378`) / `$FE` (`254` tracker) | `123.71 Hz` (`$FF`) / `124.19 Hz` (`$FE`) | `+40.07 Hz` (`$FF`) / `+40.55 Hz` (`$FE`) | **`+47.907%`** (`$FF`) / **`+48.487%`** (`$FE`) |
| **`SPACE>BASS DRUM` (CH2 `$A0` tone step 1)** | `$6E` (`110`) | `70.07 Hz` | `$FF` (`255`, clamped from `$1C3=451`) / `$FE` (`254` tracker) | `123.71 Hz` (`$FF`) / `124.19 Hz` (`$FE`) | `+53.63 Hz` (`$FF`) / `+54.12 Hz` (`$FE`) | **`+76.535%`** (`$FF`) / **`+77.227%`** (`$FE`) |
| **`4>TOM 1` (CH1 `$80` noise clock)** | `$01` (`1`) | `3889.14 Hz` *(clock `7778.28 Hz`)* | `$07` (`7`) | `3958.59 Hz` *(clock `7917.17 Hz`)* | `+69.45 Hz` | **`+1.786%`** |
| **`4>TOM 1` (CH2 `$A0` tone step 0)** | `$23` (`35`) | `216.06 Hz` | `$92` (`146`) | `215.43 Hz` | `-0.63 Hz` | **`-0.292%`** |
| **`4>TOM 1` (CH2 `$A0` tone step 1)** | `$27` (`39`) | `194.46 Hz` | `$A2` (`162`) | `194.29 Hz` | `-0.17 Hz` | **`-0.088%`** |
| **`4>TOM 1` (CH2 `$A0` tone step 2)** | `$2B` (`43`) | `176.78 Hz` | `$B2` (`178`) | `176.92 Hz` | `+0.14 Hz` | **`+0.080%`** |
| **`4>TOM 1` (CH2 `$A0` tone step 3)** | `$2F` (`47`) | `162.05 Hz` | `$C2` (`194`) | `162.40 Hz` | `+0.36 Hz` | **`+0.220%`** |
| **`4>TOM 1` (CH2 `$A0` tone step 4)** | `$33` (`51`) | `149.58 Hz` | `$D3` (`211`) | `149.38 Hz` | `-0.20 Hz` | **`-0.135%`** |
| **`5>TOM 2` (CH1 `$80` noise clock)** | `$01` (`1`) | `3889.14 Hz` *(clock `7778.28 Hz`)* | `$07` (`7`) | `3958.59 Hz` *(clock `7917.17 Hz`)* | `+69.45 Hz` | **`+1.786%`** |
| **`5>TOM 2` (CH2 `$A0` tone step 0)** | `$32` (`50`) | `152.52 Hz` | `$CF` (`207`) | `152.25 Hz` | `-0.26 Hz` | **`-0.172%`** |
| **`5>TOM 2` (CH2 `$A0` tone step 1)** | `$36` (`54`) | `141.42 Hz` | `$DF` (`223`) | `141.38 Hz` | `-0.05 Hz` | **`-0.032%`** |
| **`5>TOM 2` (CH2 `$A0` tone step 2)** | `$3A` (`58`) | `131.84 Hz` | `$EF` (`239`) | `131.95 Hz` | `+0.12 Hz` | **`+0.089%`** |
| **`5>TOM 2` (CH2 `$A0` tone step 3)** | `$3E` (`62`) | `123.46 Hz` | `$FF` (`255`, ideal `255.5`) / `$FE` (`254` tracker) | `123.71 Hz` (`$FF`) / `124.19 Hz` (`$FE`) | `+0.24 Hz` (`$FF`) / `+0.73 Hz` (`$FE`) | **`+0.195%`** (`$FF`) / **`+0.588%`** (`$FE`) |
| **`5>TOM 2` (CH2 `$A0` tone step 4)** | `$42` (`66`) | `116.09 Hz` | `$FF` (`255`, clamped from `$110=272`) / `$FE` (`254`) | `123.71 Hz` (`$FF`) / `124.19 Hz` (`$FE`) | `+7.61 Hz` (`$FF`) / `+8.10 Hz` (`$FE`) | **`+6.557%`** (`$FF`) / **`+6.975%`** (`$FE`) |
| **`5>TOM 2` (CH2 `$A0` tone step 5)** | `$46` (`70`) | `109.55 Hz` | `$FF` (`255`, clamped from `$120=288`) / `$FE` (`254`) | `123.71 Hz` (`$FF`) / `124.19 Hz` (`$FE`) | `+14.15 Hz` (`$FF`) / `+14.64 Hz` (`$FE`) | **`+12.919%`** (`$FF`) / **`+13.361%`** (`$FE`) |
| **`6>TOM 3` (CH1 `$80` noise clock)** | `$01` (`1`) | `3889.14 Hz` *(clock `7778.28 Hz`)* | `$07` (`7`) | `3958.59 Hz` *(clock `7917.17 Hz`)* | `+69.45 Hz` | **`+1.786%`** |
| **`6>TOM 3` (CH2 `$A0` tone step 0)** | `$3C` (`60`) | `127.51 Hz` | `$F7` (`247`) | `127.70 Hz` | `+0.18 Hz` | **`+0.144%`** |
| **`6>TOM 3` (CH2 `$A0` tone step 1)** | `$40` (`64`) | `119.67 Hz` | `$FF` (`255`, clamped from `$108=264`) / `$FE` (`254`) | `123.71 Hz` (`$FF`) / `124.19 Hz` (`$FE`) | `+4.04 Hz` (`$FF`) / `+4.53 Hz` (`$FE`) | **`+3.376%`** (`$FF`) / **`+3.782%`** (`$FE`) |
| **`6>TOM 3` (CH2 `$A0` tone step 2)** | `$44` (`68`) | `112.73 Hz` | `$FF` (`255`, clamped from `$118=280`) / `$FE` (`254`) | `123.71 Hz` (`$FF`) / `124.19 Hz` (`$FE`) | `+10.98 Hz` (`$FF`) / `+11.46 Hz` (`$FE`) | **`+9.738%`** (`$FF`) / **`+10.168%`** (`$FE`) |
| **`6>TOM 3` (CH2 `$A0` tone step 3)** | `$48` (`72`) | `106.55 Hz` | `$FF` (`255`, clamped from `$128=296`) / `$FE` (`254`) | `123.71 Hz` (`$FF`) / `124.19 Hz` (`$FE`) | `+17.15 Hz` (`$FF`) / `+17.64 Hz` (`$FE`) | **`+16.099%`** (`$FF`) / **`+16.555%`** (`$FE`) |
| **`6>TOM 3` (CH2 `$A0` tone step 4)** | `$4C` (`76`) | `101.02 Hz` | `$FF` (`255`, clamped from `$138=312`) / `$FE` (`254`) | `123.71 Hz` (`$FF`) / `124.19 Hz` (`$FE`) | `+22.69 Hz` (`$FF`) / `+23.17 Hz` (`$FE`) | **`+22.461%`** (`$FF`) / **`+22.941%`** (`$FE`) |
| **`6>TOM 3` (CH2 `$A0` tone step 5)** | `$50` (`80`) | `96.03 Hz` | `$FF` (`255`, clamped from `$149=329`) / `$FE` (`254`) | `123.71 Hz` (`$FF`) / `124.19 Hz` (`$FE`) | `+27.68 Hz` (`$FF`) / `+28.16 Hz` (`$FE`) | **`+28.823%`** (`$FF`) / **`+29.328%`** (`$FE`) |
| **`6>TOM 3` (CH2 `$A0` tone step 6)** | `$54` (`84`) | `91.51 Hz` | `$FF` (`255`, clamped from `$159=345`) / `$FE` (`254`) | `123.71 Hz` (`$FF`) / `124.19 Hz` (`$FE`) | `+32.20 Hz` (`$FF`) / `+32.68 Hz` (`$FE`) | **`+35.184%`** (`$FF`) / **`+35.714%`** (`$FE`) |

### 4.3 Separate Evaluation of `$C0` (`poly4`) Alternatives Under `AUDCTL = $00`
For `SPACE>BASS DRUM` (`83.64 Hz → 70.07 Hz`) and `6>TOM 3` (`127.51 Hz → 91.51 Hz`), 8-bit `$A0` pure tone under `AUDCTL = $00` (64 kHz) hits its floor at `AUDF = $FF` (`123.71 Hz`, or `124.19 Hz` at tracker max `$FE`).
- **Why `$C0` (`poly4`) reaches lower pitches at 64 kHz:** Distortion `$C0` samples POKEY's 15-bit-period 4-bit polynomial LFSR, producing a repeating 15-tick pattern of fundamental period $15 \times (N + 1)$ base-clock ticks (instead of $2 \times (N + 1)$ for `$A0` pure tone) whenever $\gcd(N+1, 15) = 1$.
- **Why `$C0` does NOT preserve the original timbre:**
  - Rhytmizer's `CH2` uses `$A0` (`PURE_TONE`), which outputs a symmetric `50%` duty-cycle square wave containing only odd harmonics ($1f, 3f, 5f, \dots$) with $1/n$ roll-off — producing a smooth, round, hollow drum shell resonance.
  - Distortion `$C0` outputs the asymmetric 15-bit sequence `000111011001010` (7 ones, 8 zeros), which is rich in both even and odd harmonics ($2f, 3f, 4f, 5f, \dots$) with a raspy, nasal, sawtooth/pulse buzz.
  - Therefore, replacing `$A0` (at 15 kHz `AUDCTL=$01`) with `$C0` (at 64 kHz `AUDCTL=$00`) for Bass Drum or Tom 3 must be classified as a **timbral redesign / substitute**, not a faithful reproduction of Rhytmizer's synthesis. To preserve the genuine `$A0` pure-tone body below `124 Hz`, the channel **must** either use `AUDCTL` Bit 0 (`$01`, 15 kHz clock) or a 16-bit joined divider (`AUDCTL` Bit 4 `$10` or Bit 3 `$08`).

---

## 5. Timing Verification & Cycle-Count Reconciliation

All timing figures below are verified at the **PAL Atari 8-bit CPU clock frequency**:
$$f_{\text{CPU,PAL}} = 1,773,447.0\text{ Hz} \quad (1\text{ CPU cycle} = 0.563874\ \mu\text{s}, \quad 1\text{ PAL 50 Hz frame} = 35,468.94\text{ cycles} = 20.000\text{ ms})$$

### 5.1 Reconciliation of `12,615` vs. `~12,670` CPU Cycles per Step
In the Phase B/C documentation, two cycle counts were cited: `12,615` cycles and `~12,670` cycles. Here is the exact instruction-level proof of both numbers:

1. **Cost of `JSR $271E` (`DELAY_TEMPO_STEP`) Alone = `12,615` CPU Cycles (at `$2002 = $07`):**
   ```asm
   ; Caller executes:
   JSR $271E               ; 6 cycles

   ; Inside $271E..$272D:
   $271E: A2 00     LDX #$00        ; 2 cycles (executed once)
   $2720: A0 00     LDY #$00        ; 2 cycles (executed once; Y is already $00 on subsequent outer loops!)
   $2722: C8        INY             ; 2 cycles \
   $2723: C0 00     CPY #$00        ; 2 cycles  | Inner Y-loop: 255 * 7 + 6 = 1,791 cycles
   $2725: D0 FB     BNE $2722       ; 3/2 cyc  /  (page $27 -> $27, no page boundary crossed)
   $2727: E8        INX             ; 2 cycles
   $2728: EC 02 20  CPX $2002       ; 4 cycles
   $272B: D0 F5     BNE $2722       ; 3 cycles (taken T-1 times), 2 cycles (fallthrough on X == T)
   $272D: 60        RTS             ; 6 cycles
   ```
   - Notice that on outer iterations `2..T`, `BNE $2722` at `$272B` branches directly to `$2722` (`INY`), because `Y` wrapped to `$00` when the previous inner loop exited!
   - Therefore, for $T = \text{M}[\$2002]$ outer iterations:
     $$\text{Cycles}_{\text{inside }\$271\text{E}} = 2_{\text{LDX}} + 2_{\text{LDY}} + T \times (1791 + 2_{\text{INX}} + 4_{\text{CPX}} + 3_{\text{BNE}}) - 1 + 6_{\text{RTS}} = 9 + 1800 \times T$$
   - Including the caller's `6`-cycle `JSR $271E`:
     $$\text{Cycles}(\text{JSR }\$271\text{E}) = 15 + 1800 \times T$$
     - For **$T = \$07$ (Record Mode default):** $15 + 1800 \times 7 = \mathbf{12,615\text{ CPU cycles}} = \mathbf{7.1133\text{ ms PAL}}$.
     - For **$T = \$08$ (Demo Mode default):** $15 + 1800 \times 8 = \mathbf{14,415\text{ CPU cycles}} = \mathbf{8.1282\text{ ms PAL}}$.

2. **Cost of the Surrounding Instrument Loop Body = `+53` to `+68` CPU Cycles per Step:**
   - In every instrument subroutine, `JSR $271E` sits inside a 9-iteration loop (`$2000 = 8..0`) that also executes:
     - Loop header & cutoff check (`CLC / LDA $2000 / CMP #cutoff / BPL active`: `11` cycles when taken, `10` cycles when falling through to mute branch),
     - Active register updates (`29–42` cycles depending on whether `AUDF1`, `AUDC1`, `AUDF2`, `AUDC2`, and `$2001` are updated) **or** silent mute writes (`LDA #$00 / STA $D201 / STA $D203 / STA $20xx / JMP delay`: `17` cycles), and
     - Loop footer after `JSR $271E` (`DEC $2000 / LDA $2000 / CMP #$FF / BNE loop`: `6 + 4 + 2 + 3 = 15` cycles, or `14` cycles on the final exit iteration).
   - Adding these **`53–68` loop-body cycles** to the **`12,615` delay cycles** gives the exact step-to-step period of **`12,668` to `12,683` CPU cycles (`7.143–7.152 ms` PAL)** between consecutive POKEY register updates!

### 5.2 Complete Verified Cycle & Duration Table for All 10 Routines (`$2002 = $07`, PAL)

| Instrument (`Routine`) | Setup + DAC Pop Cycles (Before Loop) | Active Step Period (Cycles / `ms`) | Silent Step Period (Cycles / `ms`) | Active Steps (`/9`) | Exact Active Sound Duration (`First Audible Write → Mute Write`) | Exact Silent Tail Duration (`Total − Active`) | Total Subroutine Execution Time (`JSR → RTS`) |
| --- | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **`1>HH CLOSED`** (`$26CE`) | `22` cyc (no pop) | `12,672` cyc (`7.145 ms`) | `12,658` cyc (`7.137 ms`) | `3 / 9` (`8..6`) | **`38,003` cyc (`21.429 ms` = `1.071` PAL frames)** *(cyc `49 → 38,052`)* | `75,989` cyc (`42.848 ms`) | **`113,992` cyc (`64.277 ms` = `3.214` frames)** |
| **`2>HH ACCENT`** (`$2798`) | `22` cyc (no pop) | `12,671` cyc (`7.145 ms`) | `12,658` cyc (`7.137 ms`) | `8 / 9` (`8..1`) | **`101,355` cyc (`57.151 ms` = `2.858` PAL frames)** *(cyc `49 → 101,404`)* | `12,713` cyc (`7.169 ms`) | **`114,068` cyc (`64.320 ms` = `3.216` frames)** |
| **`3>SNARE`** (`$2571`) | `46` cyc (`24`-cyc pop `cyc 14..38`) | `12,678` cyc (`7.149 ms`) | N/A (all 9 active) | `9 / 9` (`8..0`) | **`114,141` cyc (`64.361 ms` = `3.218` PAL frames)** *(cyc `14 → 114,155`)* | `32` cyc (`0.018 ms`) | **`114,173` cyc (`64.379 ms` = `3.219` frames)** |
| **`SPACE>BASS DRUM`** (`$272E`) | `44` cyc (`22`-cyc pop `cyc 14..36`) | `12,669` cyc (`7.144 ms`) | `12,657` cyc (`7.137 ms`) | `2 / 9` (`8..7`) | **`25,384` cyc (`14.313 ms` = `0.716` PAL frames)** *(cyc `14 → 25,398`)* | `88,616` cyc (`49.968 ms`) | **`114,000` cyc (`64.282 ms` = `3.214` frames)** |
| **`4>TOM 1`** (`$28D2`) | `38` cyc (`12`-cyc pop `cyc 14..26`) | `12,683` cyc (`7.152 ms`) | `12,658` cyc (`7.137 ms`) | `5 / 9` (`8..4`) | **`63,455` cyc (`35.781 ms` = `1.789` PAL frames)** *(cyc `14 → 63,469`)* | `50,638` cyc (`28.553 ms`) | **`114,093` cyc (`64.334 ms` = `3.217` frames)** |
| **`5>TOM 2`** (`$2937`) | `38` cyc (`12`-cyc pop `cyc 14..26`) | `12,681` cyc (`7.150 ms`) | `12,657` cyc (`7.137 ms`) | `6 / 9` (`8..3`) | **`76,126` cyc (`42.925 ms` = `2.146` PAL frames)** *(cyc `14 → 76,140`)* | `37,978` cyc (`21.415 ms`) | **`114,104` cyc (`64.340 ms` = `3.217` frames)** |
| **`6>TOM 3`** (`$299C`) | `38` cyc (`12`-cyc pop `cyc 14..26`) | `12,682` cyc (`7.151 ms`) | `12,658` cyc (`7.137 ms`) | `7 / 9` (`8..2`) | **`88,814` cyc (`50.080 ms` = `2.504` PAL frames)** *(cyc `14 → 88,828`)* | `25,322` cyc (`14.278 ms`) | **`114,136` cyc (`64.358 ms` = `3.218` frames)** |
| **`7>WOOD BLOCK`** (`$2844`) | `16` cyc (no pop) | `12,669` cyc (`7.144 ms`) | `12,657` cyc (`7.137 ms`) | `3 / 9` (`8..6`) | **`38,000` cyc (`21.427 ms` = `1.071` PAL frames)** *(cyc `37 → 38,037`)* | `75,982` cyc (`42.844 ms`) | **`113,982` cyc (`64.271 ms` = `3.214` frames)** |
| **`8>CLAPS`** (`$27F3`) | `16` cyc (no pop) | `12,669` cyc (`7.144 ms`) | `12,657` cyc (`7.137 ms`) | `8 / 9` (`8..1`) | **`101,345` cyc (`57.146 ms` = `2.857` PAL frames)** *(cyc `37 → 101,382`)* | `12,697` cyc (`7.160 ms`) | **`114,042` cyc (`64.305 ms` = `3.215` frames)** |
| **`*>SKIP A BEAT`** (`$2895`) | `14` cyc (mutes CH1/2) | N/A | `12,653–12,661` cyc | `0 / 9` | **`0` cyc (`0.000 ms`)** | `113,922` cyc (`64.238 ms`) | **`113,922` cyc (`64.238 ms` = `3.212` frames)** |

---

## 6. POKEY Audio Reconstruction Verification & `ASAP 8.0.0` Benchmark

### 6.1 Explicit Distinction Between the Three Artifact Tiers
1. **CPU-Cycle-Accurate Register Traces (`docs/reverse_engineering/instruments/*.json`):**
   - **Authoritative & 100% Exact.** Captured directly by executing the original 6502 machine code from `rhytmizer.xex` in `py65` and recording every store instruction to `$D200–$D20F` with exact 6502 instruction cycle counts.
2. **Custom Python Sub-Frame POKEY Simulation (`docs/reverse_engineering/instruments/*.wav` generated by `generate_phase_e.py` using `atari_music.pokey_synth` primitives):**
   - **Software Signal Approximation.** Synthesizes 44.1 kHz PCM audio from the cycle-accurate register trace using analytical box-integration over POKEY timer underflows and lookup-table LFSR bitstreams (`_POLY17_BITS`, `_POLY4_BITS`, `_POLY5_HW_GATE`).
3. **Reference Cycle-Level Hardware Emulation (`ASAP 8.0.0` `asapconv.exe` executing the original 6502 subroutines in a `TYPE D` SAP harness):**
   - **Reference POKEY Emulator Benchmark.** Executes the actual 6502 subroutine and cycle-accurate POKEY silicon state machine inside Piotr Fusik's `ASAP 8.0.0` core (`tools/asap_all/asapconv.exe`).

### 6.2 Audit of the 7 Technical Aspects of the Phase E WAV Renderer (`generate_phase_e.py`)

| # | Evaluation Question | How Phase E WAV Renderer (`generate_phase_e.py` + `pokey_synth.py`) Works | Fidelity Assessment & Identified Limitations |
| :---: | --- | --- | --- |
| **1** | **Real POKEY emulator or custom signal approximation?** | Uses a **custom Python cycle-interval extension** of `src/atari_music/pokey_synth.py` (`render_cycle_accurate_pokey_to_wav()`), not `ASAP` or `Altirra`. | Reproduces exact timer periods (`(N+1)*28` and `(N+1)*114` CPU cycles) and LFSR sequences, but simplifies sub-sample interval boundaries and DAC coupling (see items 5–7). |
| **2** | **How are `poly17` and other polynomial generators implemented?** | Precomputes the maximal-length 17-bit LFSR sequence (`131,071` bits, polynomial $1 + x^{12} + x^{17}$ in `_POLY17_BITS`) and indexes it by absolute CPU cycle (`ticks_cycle % 131071`) whenever a channel's timer underflows. Pure tone (`$A0`) toggles output bit `0 ↔ 1` on every timer underflow. | Hardware-accurate LFSR period and bit distribution; since the 17-bit LFSR advances once per CPU cycle (`1.773447 MHz`), indexing `_POLY17_BITS[ticks_cycle % 131071]` at timer underflow cycles matches hardware sample-and-hold clocking. |
| **3** | **Is generator state continuous or reset between events?** | `next_tick_cycle`, `was_ticking`, `prev_periods`, and `out_bits` are **preserved continuously** across all register-write intervals `[c0, c1)` within an instrument render. When `AUDF` changes (`prev_periods[ch] != period`) and `next_tick_cycle[ch] > t0 + period`, it clamps `next_tick_cycle[ch] = t0 + period`. | **Minor divergence from POKEY down-counter hardware:** On real POKEY silicon (without a write to `STIMER` `$D209`), writing a new value to `AUDF2` only updates the reload latch; the current down-counter finishes counting down from its previous value before reloading the new `AUDF2`. Clamping `next_tick_cycle` when `period` decreases cannot occur in Rhytmizer (because all Rhytmizer pitch sweeps increase `AUDF2`), so timer phase continuity is preserved for all downward sweeps. |
| **4** | **How are simultaneous channels mixed?** | Channels 1 and 2 are evaluated independently, mapped through the non-linear resistor-ladder lookup table `POKEY_DAC[vol]` (`0.0000..1.0000`), and summed linearly (`audio_mix[s0:s1] += wave_samples * amp`). | Matches `pokey_synth.py`'s per-channel non-linear DAC ladder (`POKEY_DAC`), whereas real POKEY hardware exhibits slight cross-channel compression when multiple channels drive the shared sum node simultaneously. |
| **5** | **Is the DAC volume-only bit (`$10`) modeled?** | **Yes, but with a polarity offset relative to bipolar oscillators:** In `pokey_synth.py`, oscillating waveforms (`$80`, `$A0`) swing symmetrically between **`-amp` and `+amp`** (zero-centered AC), whereas `Waveform.VOLUME_ONLY` (`$10`) adds **`+amp * overlap_scale`** (unipolar positive). | When `AUDC2 = $1F` (volume-only `15`) is held for `12–24` CPU cycles (`0.3–0.6` audio samples at 44.1 kHz) and weighted by `overlap_scale = (t1 - t0) / cps`, the sub-sample impulse is attenuated compared to real unipolar POKEY hardware (where `0..amp` is the swing of both volume-only and oscillating modes). |
| **6** | **Are POKEY output characteristics modeled?** | Applies `POKEY_DAC[0..15]` non-linear volume curve, followed by a single-pole high-pass DC-blocking filter ($y[n] = x[n] - x[n-1] + 0.995\,y[n-1]$, cutoff $\approx 35\text{ Hz}$), and normalizes peak amplitude of each individual WAV file to **`0.90` (`90%` full scale)**. | **Important Normalization Difference:** Because `render_cycle_accurate_pokey_to_wav()` peak-normalizes each WAV independently to `0.90`, a quiet instrument like `1>HH CLOSED` (max volume 4, `POKEY_DAC[4] = 0.046`) is boosted to the same `0.90` peak in its standalone `.wav` file as `SPACE>BASS DRUM` (volume 12 + pop 15). In contrast, `ASAP 8.0.0` preserves absolute hardware amplitude across instruments (`0.231` peak for `HH CLOSED` vs `0.677` peak for `TOM 1–3`). |
| **7** | **Does sample-rate conversion introduce timing errors?** | In `generate_phase_e.py`, each register interval `[t0, t1)` is mapped to `s0 = floor(t0 / cps)` and `s1 = ceil(t1 / cps)` ($1\text{ sample} = 40.214\text{ CPU cycles}$ at 44.1 kHz). When multiple register writes occur within `< 40` CPU cycles (such as the 4–5 initialization writes at cycles `8, 14, 20, 26, 32, 61`), their `[s0, s1)` sample bins overlap (`s0 = 0, s1 = 1` or `2`). | For the `12,670`-cycle (`~315`-sample) active envelope steps, a $\pm 0.5$ sample boundary rounding is only `0.011 ms` (`0.16%` of a step), which is imperceptible. Only during the initial `60`-cycle (`1.5`-sample) setup burst do overlapping `[s0, s1)` bins slightly smear the 1-sample attack transient. |

### 6.3 Direct Benchmark: Phase E `pokey_synth` WAVs vs. Reference `ASAP 8.0.0` (`TYPE D` 6502 Execution)
We assembled each of the 9 relocated Rhytmizer subroutines (`$2000–$2E5C`) into a standalone `SAP TYPE D` executable initialized with `$2002 = $07`, `$2005 = $16`, `$2006 = $01` and rendered 44.1 kHz 16-bit WAV audio via **`ASAP 8.0.0` (`tools/asap_all/asapconv.exe`)**:

| Instrument ID | `ASAP 8.0.0` Absolute Peak (Unnormalized) | `pokey_synth` Peak (Normalized to `0.90`) | `ASAP 8.0.0` Crest Ratio (`RMS / Peak`) | `pokey_synth` Crest Ratio (`RMS / Peak`) | `ASAP 8.0.0` Active Burst Duration | `pokey_synth` Active Burst Duration | 1 ms Envelope Correlation (`r`) |
| --- | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **`rhytmizer_hh_closed`** | `0.2309` | `0.9000` | `0.1638` | `0.1353` | `21.5 ms` *(+ DC tail)* | `22.0 ms` | **`0.8848`** |
| **`rhytmizer_hh_accent`** | `0.4280` | `0.9000` | `0.2023` | `0.1706` | `57.2 ms` *(+ DC tail)* | `57.0 ms` | **`0.9442`** |
| **`rhytmizer_snare`** | `0.6095` | `0.9000` | `0.2391` | `0.1496` | `64.4 ms` *(+ DC tail)* | `64.4 ms` | **`0.8197`** |
| **`rhytmizer_bass_drum`** | `0.5890` | `0.9000` | `0.2428` | `0.2047` | `14.3 ms` *(+ DC tail)* | `15.0 ms` | **`0.8004`** |
| **`rhytmizer_tom_1`** | `0.6769` | `0.9000` | `0.2321` | `0.2409` | `35.8 ms` *(+ DC tail)* | `41.0 ms` | **`0.8183`** |
| **`rhytmizer_tom_2`** | `0.6769` | `0.9000` | `0.2362` | `0.2018` | `42.9 ms` *(+ DC tail)* | `43.0 ms` | **`0.7923`** |
| **`rhytmizer_tom_3`** | `0.6769` | `0.9000` | `0.2403` | `0.2377` | `50.1 ms` *(+ DC tail)* | `53.0 ms` | **`0.8097`** |
| **`rhytmizer_wood_block`** | `0.3820` | `0.9000` | `0.1864` | `0.2360` | `21.4 ms` *(+ DC tail)* | `22.0 ms` | **`0.8090`** |
| **`rhytmizer_claps`** | `0.3286` | `0.9000` | `0.2729` | `0.3404` | `57.1 ms` *(+ DC tail)* | `57.0 ms` | **`0.8633`** |

---

## 7. Revised Composer Compatibility Assessment (4-Mode Evaluation)

Every instrument is now evaluated across **four distinct implementation architectures (Modes A, B, C, D)** rather than a single flat label:

- **Mode A — Original Two-Channel Synthesis (`rhytmizer.xex` Native Baseline):**
  - Blocking 6502 main-thread loop (`~140 Hz` step rate = `7.14 ms`/step at `$2002=$07`), simultaneous `CH1 + CH2`, dynamic per-instrument `AUDCTL` (`$00` vs `$01`), and `12–24` cycle `$1F/$1B` DAC attack pop.
- **Mode B — Single-Channel 50 Hz VBI Approximation (`core_v2_iter1`, `1` POKEY Channel, `AUDCTL=$00`):**
  - Uses 1 channel (`CH4`) in `player.asm` v2 at 50 Hz VBI (`20.0 ms`/frame) with `TransientMacroSpec` (up to 8 frames) and `PitchEnvelopeSpec` under standard 64 kHz clocking (`AUDCTL=$00`).
- **Mode C — Dual-Channel 50 Hz VBI Synthesis (`core_v2_iter1`, `2` POKEY Channels):**
  - Uses 2 simultaneous 8-bit channels in `player.asm` v2 at 50 Hz VBI (`20.0 ms`/frame) — one channel dedicated to the `$80` 17-bit poly noise layer and the second channel dedicated to the `$A0` pure-tone sweep/ring (or secondary `$80` noise layer), evaluated under either **`C1: AUDCTL=$00` (64 kHz converted dividers)** or **`C2: AUDCTL=$01` / `$29` (native 15 kHz dividers on CH1+CH2, with CH3+CH4 running at 15 kHz or 16-bit 1.79 MHz)**.
- **Mode D — Dedicated Sub-Frame Playback Mechanism (`~140–150 Hz` DLI / Timer IRQ Custom Engine):**
  - Updates POKEY registers `3×` per 50 Hz PAL frame (`150 Hz` = `6.67 ms`/step, within `6.6%` of Rhytmizer's `7.14 ms` step) across `CH1 + CH2` with per-instrument `AUDCTL` (`$00`/`$01`) and attack transient support.

| Instrument (`ID`) | Mode B: Single-Channel 50 Hz (`AUDCTL=$00`) Acoustic Similarity & Loss | Mode C: Dual-Channel 50 Hz (`player.asm` v2) Acoustic Similarity & Loss | Mode D: Dedicated Sub-Frame (`150 Hz`, 2-Ch) Acoustic Similarity & Cost | Overall Compatibility Classification |
| --- | --- | --- | --- | --- |
| **`8>CLAPS`** (`rhytmizer_claps`) | **High Similarity (`~92%`):** Already single-channel (`CH1`) and `AUDCTL=$00` in original binary due to `$2821: STA $D5EB` bug! Exact same `AUDF1=$12` (`3.36 kHz`) poly17 noise texture. Only difference is temporal quantization of the volume decay from 8 steps (`57.15 ms` at `140 Hz`) to **3 VBI frames (`60.0 ms` at `50 Hz`, `vol 8 → 5 → 2`)**. | **Identical to Mode B** for as-executed binary (1 channel). If the intended 2nd channel (`AUDF2=$1E`, `AUDC2=$88..$81`) is restored, Mode C (`AUDCTL=$00`) layers both exact dividers (`$12` and `$1E`) across 3 VBI frames. | **Near-Exact (`~99%`):** 8 steps at `150 Hz` (`53.3 ms`) reproduces the exact 8-step volume staircase `8..1`. Requires custom 3×/frame interrupt handler. | **`DIRECT` (Mode B)** |
| **`1>HH CLOSED`** (`rhytmizer_hh_closed`) | **Good Similarity (`~85%`):** Reproduces the primary `CH1` `$80` white-noise burst (`AUDF1=$00`, `AUDCTL=$00`) in **1 VBI frame (`20.0 ms` vs `21.43 ms` original, `-6.7%` duration)**. Loses the secondary `CH2` `3,551 Hz` (`AUDF2=$08`) pure-tone metallic ring (`AUDC2=$A1`, `vol=1`, which contributes `14%` of linear DAC amplitude) and compresses the `4→3→2` decay into 1 frame (or 2 frames `40 ms`). | **High Similarity (`~93%` under `AUDCTL=$00`):** Simultaneously triggers `CH1` (`$84`, `AUDF1=$00`) and `CH2` (`$A1`, `AUDF2=$08`) with **zero frequency error** (`AUDCTL=$00` native). Only difference is 1-frame (`20 ms`) vs 3-sub-step (`21.4 ms`) envelope resolution. | **Near-Exact (`~99%`):** Reproduces the exact 3-step `4→3→2` decay (`20.0 ms` at `150 Hz`) and simultaneous `$A1` metallic ring. | **`DIRECT` (Mode B, minor metallic ring loss)** / **`EXTENDED` (Mode C)** |
| **`2>HH ACCENT`** (`rhytmizer_hh_accent`) | **High Similarity (`~90%`):** Reproduces the primary `CH1` `$80` white-noise decay (`AUDF1=$00`, `AUDCTL=$00`, `vol 8→1` over `57.15 ms`) in **3 VBI frames (`60.0 ms`, `vol 8→5→2`)**. Omits the quiet `CH2` `$A1` (`vol=1`) metallic ring (`-28 dB` below peak noise). | **Very High Similarity (`~95%` under `AUDCTL=$00`):** Simultaneously layers `CH1` (`AUDF1=$00`, `vol 8→5→2`) and `CH2` (`AUDF2=$08`, `AUDC2=$A1`) with **zero frequency error** over 3 VBI frames (`60 ms`). | **Near-Exact (`~99%`):** Reproduces all 8 volume steps (`8..1`) + `CH2` `$A1` ring at `150 Hz` (`53.3 ms`). | **`DIRECT` (Mode B)** / **`EXTENDED` (Mode C)** |
| **`7>WOOD BLOCK`** (`rhytmizer_wood_block`) | **Moderate Similarity (`~65%`):** Cannot play both simultaneous sample-and-hold noise dividers (`AUDF1=$07` and `AUDF2=$14`) at once on 1 channel; a 2-frame macro alternating `$07` (`20 ms`) and `$14` (`20 ms`) stretches duration from `21.43 ms` to `40.0 ms` and loses the simultaneous cross-correlated interference knock. | **High Similarity (`~92%` under `AUDCTL=$00`):** Simultaneously plays `AUDF1=$07` (`$85`) and `AUDF2=$14` (`$85`) with **zero frequency error** (`AUDCTL=$00` native) for 1 VBI frame (`20.0 ms` vs `21.43 ms`). Preserves the true dual-channel interference timbre! | **Near-Exact (`~99%`):** Preserves both simultaneous channels and the 3-step `5→4→3` decay over `20.0 ms`. | **`EXTENDED` (Mode C recommended; Mode B degrades dual-noise interference)** |
| **`3>SNARE`** (`rhytmizer_snare`) | **Low-to-Moderate Similarity (`~55%`):** On 1 channel at 50 Hz, the simultaneous `64.4 ms` pure-tone shell sweep (`311→190 Hz`) and `7.78 kHz` snare wire noise must be time-interleaved across 3–4 frames (e.g., Frame 0 tone `$65`, Frame 1 noise `$07`, Frame 2 tone `$8E`, Frame 3 noise `$07`), losing simultaneous tone+noise blend, reducing pitch sweep from 9 steps to 2 steps, and omitting the 24-cycle DAC pop. | **Good Similarity (`~82%` in Mode C1 `AUDCTL=$00`; `~85%` in Mode C2 `AUDCTL=$01`/`$29`):** Simultaneously layers the `$80` noise track (`AUDF=$07` at 64 kHz [`+1.79%` error] or `$01` at 15 kHz [`0%` error]) and the `$A0` pure-tone downward sweep (`$65→$7D→$96→$A6` at 64 kHz [`<0.27%` error] or `$18..$28` at 15 kHz) across 3–4 VBI frames (`60–80 ms`). Loses only the 9-step `140 Hz` sweep density (quantized to 3–4 VBI steps) and the 24-cycle DAC pop. | **Near-Exact (`~98%`):** Reproduces simultaneous 9-step tone sweep + noise decay at `150 Hz` (`60 ms`). | **`EXTENDED` (Mode C required for simultaneous shell+wires; Mode B is an approximation)** |
| **`4>TOM 1`** (`rhytmizer_tom_1`) | **Moderate Similarity (`~60%`):** On 1 channel (`AUDCTL=$00`), Frame 0 must choose either the noise attack (`AUDF=$07`) or start of the pure-tone sweep (`AUDF=$92`, `215.4 Hz`), leaving only 1–2 frames for the pitch drop to `$D3` (`149.4 Hz`). Loses simultaneous noise+tone layering and 5-step `140 Hz` sweep smoothness. | **Good Similarity (`~82%` in Mode C1 `AUDCTL=$00`; `~84%` in Mode C2 `AUDCTL=$01`/`$29`):** Simultaneously layers the noise transient channel (`AUDF=$07` at 64 kHz [`+1.79%`] or `$01` at 15 kHz) with the pure-tone sweep channel (`AUDF=$92→$B2→$D3` at 64 kHz [`<0.29%` frequency error!]) over 2 VBI frames (`40.0 ms` vs `35.78 ms`). | **Near-Exact (`~98%`):** Reproduces all 5 sub-frame sweep steps (`$23..$33`) + simultaneous noise decay over `33.3 ms`. | **`EXTENDED` (Mode C preserves dual-layer tom; Mode B is single-layer)** |
| **`5>TOM 2`** (`rhytmizer_tom_2`) | **Low-to-Moderate Similarity (`~52%`):** On 1 channel (`AUDCTL=$00`), loses simultaneous noise+tone layering, quantizes the 6-step sweep (`42.93 ms`) to 2–3 VBI frames, and clips the final 2 sweep steps (`116.1 Hz, 109.6 Hz`) at the 8-bit 64 kHz tracker floor `$FE` (`124.19 Hz`, **`+6.98%` and `+13.36%` error**). | **Moderate-to-Good Similarity (`~75%` in Mode C1 `AUDCTL=$00`; `~85%` in Mode C2 `AUDCTL=$01`/`$29`):** Mode C1 (`AUDCTL=$00`) preserves simultaneous noise+tone for the first `30 ms` (`152.5→123.5 Hz` via `$CF→$EF→$FE`), clipping only the final tail frame at `124.2 Hz`. Mode C2 (`AUDCTL=$01` or `$29`) reaches the full `152.5→109.6 Hz` range with `0%` frequency error across 2–3 VBI frames. | **Near-Exact (`~98%` under `AUDCTL=$01`):** Reproduces all 6 sub-frame steps (`$32..$46`) and simultaneous noise decay. | **`EXTENDED` (Mode C2 for full pitch range; Mode C1 clips tail by `+13%`)** |
| **`6>TOM 3`** (`rhytmizer_tom_3`) | **Low Similarity (`~35%` with `$A0` at `AUDCTL=$00`; `~45%` with `$C0` poly4 substitute):** Under `AUDCTL=$00`, 6 of the 7 pure-tone steps (`119.7 Hz → 91.5 Hz`) lie below the 8-bit 64 kHz `$A0` floor (`124.19 Hz`, up to **`+35.71%` pitch error**), effectively flattening the pitch sweep into a static `124 Hz` tone! Substituting `$C0` (`poly4`) reaches `128→92 Hz` but changes the timbre from a clean tom to a buzzy saw/pulse wave. | **Low Pitch Fidelity in Mode C1 (`AUDCTL=$00` `$A0`); Good Similarity (`~85%`) in Mode C2 (`AUDCTL=$01`/`$29`) or 16-bit CH1+CH2:** To preserve the genuine `$A0` pure-tone sweep from `127.5 Hz` down to `91.5 Hz` at 50 Hz VBI, the tone channel **must** run at 15 kHz (`AUDCTL=$01` or `$29`) or use 16-bit joining (`AUDCTL=$50`, which consumes CH1+CH2 for the tone alone). | **Near-Exact (`~98%` under `AUDCTL=$01`):** Requires `AUDCTL=$01` and `150 Hz` sub-frame stepping. | **`CUSTOM` / `EXTENDED (Mode C2 15 kHz required)`** *(Cannot be faithfully reproduced in 8-bit `AUDCTL=$00` `$A0`)* |
| **`SPACE>BASS DRUM`** (`rhytmizer_bass_drum`) | **Low Similarity (`~30%` with `$A0` at `AUDCTL=$00`; `~45%` with `$C0` poly4 substitute):** Original active sound is an ultra-fast **`14.31 ms` (`0.72` PAL frame)** two-step sub-bass drop (`83.64 Hz → 70.07 Hz`, `$A0` pure tone at `vol=12`) layered with `5.19 kHz` poly17 noise (`vol=5`) and a 22-cycle DAC pop. Under 8-bit `AUDCTL=$00` (`64 kHz`), `$A0` pure tone cannot go below `124.19 Hz` (**`+48.5%` to `+77.2%` frequency error** — over half an octave too high!), and a 50 Hz VBI frame (`20.0 ms`) is longer than the entire `14.31 ms` drum hit! Using `$C0` (`poly4`) reaches `84→70 Hz` at 64 kHz but replaces the clean sine/square kick thump with a buzzy 4-bit LFSR waveform. | **Moderate Similarity (`~70%`) in Mode C2 (`AUDCTL=$01`/`$29` at 50 Hz VBI):** Under `AUDCTL=$01` (or `$29`), CH1 (`AUDF1=$02, AUDC1=$85`) and CH2 (`AUDF2=$5C→$6E, AUDC2=$AC`) produce the **exact `83.64 Hz` and `70.07 Hz` pure-tone frequencies**, but at 50 Hz VBI (`20.0 ms`/frame) a 1-frame hit plays only a single pitch (`83.6 Hz` or `70.1 Hz` for `20 ms`), while a 2-frame hit stretches the `14.31 ms` kick to `40.0 ms` (`2.8×` longer). | **Near-Exact (`~98%` under `AUDCTL=$01` at `150 Hz`):** Two `6.67 ms` sub-frame steps (`13.33 ms` total) under `AUDCTL=$01` reproduce both the exact `83.64 Hz → 70.07 Hz` `$A0` sub-bass drop and the `14.3 ms` punch duration. | **`CUSTOM` (for authentic `14.3 ms` 2-step `$A0` sub-bass drop)** / **`EXTENDED (Mode C2 15 kHz 50 Hz approximation)`** |

---

## 8. Remaining Technical Uncertainties

1. **Historical Origin of `$2821: STA $D5EB` (`8D EB D5`) in `8>CLAPS`:**
   - **Confirmed from binary:** Bytes at `$2821–$2823` (file offset `0x08EF–0x08F1`) are `8D EB D5` (`STA $D5EB`).
   - **Unresolved historical question:** Whether the author (`MUNSIE`, 1986) corrupted `$03 D2` (`AUDC2`) to `$EB D5` via an assembler/memory-patch typo or intentionally disabled Channel 2 during tuning by poking a dummy high address into the `STA` operand cannot be proven from the binary alone. Both the as-executed single-channel trace (`CH1` only) and the structural evidence of the adjacent `STA $D202` (`AUDF2=$1E`) instruction are documented.
2. **Acoustic Perceptibility of the `12–24` CPU-Cycle (`~6.8–13.5 µs`) Pre-Loop `$1F/$1B` DAC Writes:**
   - **Confirmed from binary:** `Snare`, `Bass Drum`, and `Toms 1–3` write `AUDC2 = $1F` (and `AUDC1 = $1B` for Snare/Bass Drum) for `12–24` CPU cycles before clearing `AUDC2 = $00` and entering the step loop.
   - **Hardware analog filter behavior:** On real Atari XL/XE analog audio output circuitry (which includes an RC low-pass filter and AC coupling capacitor after the POKEY audio pin), a `6.8–13.5 µs` pulse is heavily attenuated by the analog output stage (`f_{-3\text{dB}} \approx 12–16\text{ kHz}$), contributing only a very faint high-frequency click compared to the `7.14 ms` step 0 body. Measuring its exact analog voltage contribution would require oscilloscope capture from physical Atari XL/XE hardware (or Altirra's analog output filter model).

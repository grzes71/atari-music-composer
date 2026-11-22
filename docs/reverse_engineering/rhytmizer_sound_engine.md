# Phase C — Rhytmizer Sound Engine & Percussion Synthesis Reconstruction

---

## 1. Architectural Overview of the Sound Engine

Rhytmizer implements a **procedural, dual-channel (CH1 + CH2), sub-frame blocking POKEY percussion engine**. Unlike table-driven tracker engines that update POKEY registers once per VBI frame (50 Hz PAL / 60 Hz NTSC), Rhytmizer synthesizes each percussion sound algorithmically inside a dedicated 6502 subroutine that monopolizes the CPU for one beat (9 sub-frame steps).

### Key Architectural Characteristics (Confirmed)
1. **Procedural Code Representation (Zero Lookup Tables):**
   - There are **no envelope tables, frequency tables, or command streams** for sound synthesis.
   - Instead, each of the 9 percussion instruments (plus `*>SKIP A BEAT`) is a self-contained 6502 subroutine (`80–106` bytes each, located contiguously at `$2571–$25D7` and `$26CE–$2A00`).
   - Volume envelopes and pitch sweeps are computed arithmetically in real time from the loop counter `$2000` (`8` down to `0`) and the pitch accumulator `$2001`:
     - Volume decay: `LDA #base_audc / ADC $2000 / STA $D201` (or `$D203`), exploiting the fact that `base_audc` has its upper nibble set to the POKEY distortion (`$80` or `$A0`) and `$2000` (`8..0`) adds directly into the 4-bit volume nibble (`$00..$0F`).
     - Pitch sweep: `LDA $2001 / ADC #step_delta / STA $2001 / STA $D202`.
2. **Synchronous Sub-Frame Update Rate (~140 Hz at default tempo):**
   - Every instrument routine executes **9 loop iterations** (`$2000 = 8, 7, 6, 5, 4, 3, 2, 1, 0`), calling `JSR $271E` (`DELAY_TEMPO_STEP`) once per iteration.
   - At the default Record Mode tempo (`$2002 = $07`), each iteration takes **`~12,670` CPU cycles (`7.14 ms` PAL)** — equivalent to **`~140.0 Hz`**, or **`2.80` register updates per 50 Hz PAL frame**.
   - Active sound duration is controlled by comparing `$2000` against an instrument-specific cutoff threshold (`CMP #cutoff / BPL active_branch`). Once `$2000 < cutoff`, the routine writes `$00` to `AUDC1` and `AUDC2` (and clears the on-screen trigger indicator character) for the remaining steps of the 9-step beat so that every instrument call consumes the exact same rhythmic step duration (`~114,000` cycles = `64.28 ms` PAL at `$2002 = $07`).
3. **Dual-Channel Layered Synthesis (`CH1` Noise + `CH2` Tone/Noise):**
   - **POKEY Channel 1 (`AUDF1/AUDC1`)** is always the **17-bit polynomial noise layer** (`AUDC1` upper nibble = `$80`).
   - **POKEY Channel 2 (`AUDF2/AUDC2`)** provides the **tonal body or secondary resonator**:
     - Pure tone (`$A0`) with downward frequency sweep for **Snare**, **Bass Drum**, **Tom 1**, **Tom 2**, and **Tom 3**.
     - Pure tone (`$A0`) at fixed high frequency (`AUDF2 = $08`, volume `1`) for **HH Closed** and **HH Accent** to give the white noise a metallic cymbal sheen.
     - 17-bit polynomial noise (`$80`) at a second fixed divider (`AUDF2 = $14` vs. `AUDF1 = $07`) for **Wood Block**.
     - Intended secondary voice for **Claps** (`AUDF2 = $1E`), rendered silent by an original coding bug at `$2821` (`STA $D5EB` instead of `STA $D203`).
   - **POKEY Channels 3 and 4 (`$D204–$D207`) are completely unused.**
4. **Per-Instrument `AUDCTL` Base-Clock Switching (`$00` vs. `$01`):**
   - High-frequency / bright percussion (**HH Closed**, **HH Accent**, **Wood Block**, **Claps**) sets **`AUDCTL = $00` (64 kHz base clock, `63,337.39 Hz` PAL)**.
   - Low/mid-frequency drums (**Snare**, **Bass Drum**, **Tom 1**, **Tom 2**, **Tom 3**) set **`AUDCTL = $01` (15 kHz base clock, `15,556.55 Hz` PAL)** so that 8-bit `AUDF2` dividers can reach deep bass and tom fundamentals (`70.07 Hz–311.13 Hz`) and `AUDF1` (`$01` or `$02`) clocks the 17-bit LFSR at a coarser, crunchier sample rate (`7,778.28 Hz` or `5,185.52 Hz`).
   - Note on `AUDCTL` Bit 0 (`$01`): In Rhytmizer, only Channels 1 and 2 (`$D200–$D203`) are used (Channels 3 and 4 are unused). In POKEY hardware (`CO12294`), Bit 0 selects the `15 kHz / 64 kHz` base-clock prescaler for all channels running from the base clock (whereas Bit 1 `$02` is the CH2/CH4 High-Pass Filter and Bit 5 `$20` clocks CH3 directly from the `1.77 MHz` CPU clock, independent of Bit 0).
5. **Microsecond Volume-Only DAC Attack Transients (`$1F` / `$1B`):**
   - **Snare**, **Bass Drum**, **Tom 1**, **Tom 2**, and **Tom 3** precede their 9-step loop with a brief **10-to-24 CPU-cycle Volume-Only DAC spike** (`AUDC2 = $1F` [vol 15] and, for Snare/Bass Drum, `AUDC1 = $1B` [vol 11]) before immediately writing `AUDC2 = $00` and entering the step loop.
   - On real POKEY hardware, toggling the DAC output bit (`bit 4 = 1`) to maximum amplitude for `~8–14 µs` and releasing it injects an audible high-frequency impulse click at the exact attack onset (`t = 0 ms`).

---

## 2. Detailed Specification of Every Sound Routine

### 2.1 Shared Timing Subroutine: `DELAY_TEMPO_STEP` (`$271E–$272D`)
- **Entry address:** `$271E`
- **Input parameters:** `$2002` (`TEMPO_DELAY_HI`, default `$07` in Record Mode, `$08` in Demo Mode)
- **Modified registers:** `X`, `Y`, flags `N`, `Z`, `C`
- **Timing formula:** $15 + 1800 \times \text{M}[\$2002]$ CPU cycles (`12,615` cycles = `7.1133 ms` PAL for `JSR $271E` + `RTS` at `$2002 = $07`, plus `53–68` cycles of caller loop-body overhead = `12,668–12,683` cycles / `7.143–7.152 ms` PAL per step).

---

### 2.2 Instrument 1: `1>HH CLOSED` (`TRIG_HH_CLOSED`, `$26CE–$271D`)
- **Entry address:** `$26CE` (triggered by key `'1'`, `CH = $1F`)
- **Input parameters:** `$2002` (step delay)
- **Modified memory:** `$2036` (screen indicator `'T'` `$54` while active, `$00` when muted), `$2000` (`8..$FF`), `$2001` (`$00`)
- **POKEY registers written:** `AUDCTL ($D208)`, `AUDF1 ($D200)`, `AUDC1 ($D201)`, `AUDF2 ($D202)`, `AUDC2 ($D203)`
- **Active duration:** **3 steps** (`$2000 = 8, 7, 6` → `38,052` cycles = **`21.46 ms` PAL** at `$2002=$07`), followed by **6 silent steps** (`$2000 = 5..0` → `42.82 ms` PAL). Total routine duration: `113,992` cycles (`64.28 ms` PAL).
- **Algorithm & Register Evolution:**
  1. Sets `AUDCTL = $00` (64 kHz clock).
  2. For `$2000` in `8, 7, 6` (`CMP #$06 / BPL $26F8`):
     - `AUDF1 = $00` ($f_{\text{clock},1} = 63920.4 / (2 \times 1)$ → `63.92 kHz` poly17 shift rate)
     - `AUDC1 = $7C + $2000` → **`$84`, `$83`, `$82`** (17-bit poly noise, volume `4 → 3 → 2`)
     - `AUDF2 = $08`, `AUDC2 = $A1` (pure tone at $63920.4 / (2 \times 9) = 3551.1\text{ Hz}$, volume `1`)
  3. For `$2000` in `5, 4, 3, 2, 1, 0`: writes `AUDC1 = $00`, `AUDC2 = $00`, `$2036 = $00`.
- **Disassembly (`$26CE–$271D`):**
```asm
TRIG_HH_CLOSED:
    $26CE: A9 54     LDA #$54        ; Screen code 'T' indicator
    $26D0: 8D 36 20  STA $2036       ; Display indicator next to 1>HH CLOSED
    $26D3: A9 08     LDA #$08
    $26D5: 8D 00 20  STA $2000       ; ENV_STEP_CNT = 8
    $26D8: A9 00     LDA #$00
    $26DA: 8D 08 D2  STA $D208       ; AUDCTL = $00 (64 kHz clock)
    $26DD: A9 00     LDA #$00
    $26DF: 8D 01 20  STA $2001
loop_hh_closed:
    $26E2: 18        CLC
    $26E3: AD 00 20  LDA $2000
    $26E6: C9 06     CMP #$06        ; Active while $2000 >= 6 (steps 8, 7, 6)
    $26E8: 10 0E     BPL $26F8
    $26EA: A9 00     LDA #$00        ; Silent tail for steps 5..0
    $26EC: 8D 01 D2  STA $D201       ; AUDC1 = $00
    $26EF: 8D 03 D2  STA $D203       ; AUDC2 = $00
    $26F2: 8D 36 20  STA $2036       ; Clear UI indicator
    $26F5: 4C 10 27  JMP $2710
active_hh_closed:
    $26F8: A9 00     LDA #$00
    $26FA: 8D 00 D2  STA $D200       ; AUDF1 = $00
    $26FD: 18        CLC
    $26FE: A9 7C     LDA #$7C
    $2700: 6D 00 20  ADC $2000       ; $7C + (8..6) = $84, $83, $82
    $2703: 8D 01 D2  STA $D201       ; AUDC1 = poly17 noise, vol 4->3->2
    $2706: A9 A1     LDA #$A1
    $2708: 8D 03 D2  STA $D203       ; AUDC2 = pure tone, vol 1
    $270B: A9 08     LDA #$08
    $270D: 8D 02 D2  STA $D202       ; AUDF2 = $08 (3,551 Hz metallic sheen)
step_delay_hh_closed:
    $2710: 20 1E 27  JSR $271E       ; Delay 1 sub-frame step (~7.14 ms)
    $2713: CE 00 20  DEC $2000
    $2716: AD 00 20  LDA $2000
    $2719: C9 FF     CMP #$FF
    $271B: D0 C5     BNE $26E2
    $271D: 60        RTS
```

---

### 2.3 Instrument 2: `2>HH ACCENT` (`TRIG_HH_ACCENT`, `$2798–$27F2`)
- **Entry address:** `$2798` (triggered by key `'2'`, `CH = $1E`)
- **Input parameters:** `$2002` (step delay)
- **Modified memory:** `$205E` (UI indicator), `$2000` (`8..$FF`), `$2001` (`$00`)
- **POKEY registers written:** `AUDCTL ($D208)`, `AUDF1 ($D200)`, `AUDC1 ($D201)`, `AUDF2 ($D202)`, `AUDC2 ($D203)`
- **Active duration:** **8 steps** (`$2000 = 8..1` → `101,404` cycles = **`57.18 ms` PAL** at `$2002=$07`), followed by **1 silent step** (`$2000 = 0` → `7.14 ms` PAL). Total routine duration: `114,068` cycles (`64.32 ms` PAL).
- **Algorithm & Register Evolution:**
  - Identical dual-channel architecture to `HH CLOSED` (`AUDCTL = $00`, `AUDF1 = $00` poly17 noise + `AUDF2 = $08`, `AUDC2 = $A1` metallic overtone), except:
    1. Cutoff threshold is `CMP #$01 / BPL $27C2` (8 active steps instead of 3 — 2.67× longer open/accented decay).
    2. Noise volume base is `$80 + $2000` (`$88` down to `$81`, starting at **volume 8** instead of volume 4 — 2× higher peak amplitude).

---

### 2.4 Instrument 3: `3>SNARE` (`TRIG_SNARE`, `$2571–$25D7`)
- **Entry address:** `$2571` (triggered by key `'3'`, `CH = $1A`, and also called as audible key-click feedback during filename typing at `$2C8C`)
- **Input parameters:**
  - `$2002` (`TEMPO_DELAY_HI`, default `$07`, demo `$08`)
  - `$2005` (`SNARE_TONE_BASE`, default `$16` [22], demo `$18` [24], tunable via Up/Down keys `$0E/$0F`)
  - `$2006` (`SNARE_PITCH_AUDF1`, default `$01`, demo `$01`, tunable via Ctrl+Up/Down keys `$8E/$8F`)
- **Modified memory:** `$2086` (UI indicator), `$2000` (`8..$FF`), `$2001` (`$2005` incremented by `+$02` per step)
- **POKEY registers written:** `AUDCTL ($D208)`, `AUDF1 ($D200)`, `AUDC1 ($D201)`, `AUDF2 ($D202)`, `AUDC2 ($D203)`
- **Active duration:** **All 9 steps** (`$2000 = 8..0` → `114,173` cycles = **`64.38 ms` PAL** at `$2002=$07`). There is no early cutoff branch in `TRIG_SNARE`; both channels are muted at `$25CC–$25D1` immediately after step `$2000 = 0` finishes.
- **Algorithm & Register Evolution:**
  1. **Attack DAC Pop (`cycles 8..34`):**
     - `AUDCTL = $01` (15 kHz base clock, `15,699.8 Hz` PAL).
     - `AUDC2 = $1F` (volume-only DAC level 15 on CH2 at cycle 14).
     - `AUDC1 = $1B` (volume-only DAC level 11 on CH1 at cycle 20).
     - `AUDF1 = $2006` (default `$01` at cycle 28).
     - `AUDC2 = $00` (clears CH2 DAC pop at cycle 34; CH1 stays at `$1B` until cycle 60).
  2. **9-Step Dual-Channel Body + Snare Wire Decay (`$2000 = 8..0`):**
     - **Channel 1 (Snare Wires — 17-bit poly noise at 15 kHz clock):**
       - `AUDF1 = $2006` (at default `$01`, divider is $N = 2$, clock rate $= 15699.8 / 2 = 7849.9\text{ Hz}$).
       - `AUDC1 = $80 + $2000` → **`$88, $87, $86, $85, $84, $83, $82, $81, $80`** (linearly decaying from volume 8 to volume 0 on the 9th step).
     - **Channel 2 (Drum Shell Fundamental — Pure Tone downward pitch sweep):**
       - `AUDF2 = $2001` where `$2001` starts at `$2005` (`$16`) and adds `+$02` before each step write:
         - At default `$2005 = $16`: `AUDF2` sweeps **`$18, $1A, $1C, $1E, $20, $22, $24, $26, $28`** (`314.0 Hz → 191.5 Hz`).
         - At demo `$2005 = $18`: `AUDF2` sweeps **`$1A, $1C, $1E, $20, $22, $24, $26, $28, $2A`** (`290.7 Hz → 182.6 Hz`).
       - `AUDC2 = $A1 + $2000` → **`$A9, $A8, $A7, $A6, $A5, $A4, $A3, $A2, $A1`** (pure tone linearly decaying from volume 9 down to volume 1).
  3. **Exit Mute (`cycle 114,155`):** `AUDC1 = $00`, `AUDC2 = $00`, `$2086 = $00`.
- **Disassembly (`$2571–$25D7`):**
```asm
TRIG_SNARE:
    $2571: A9 54     LDA #$54        ; Screen code 'T' indicator
    $2573: 8D 86 20  STA $2086       ; Display indicator next to 3>SNARE
    $2576: A9 01     LDA #$01
    $2578: 8D 08 D2  STA $D208       ; AUDCTL = $01 (15 kHz base clock)
    $257B: A9 1F     LDA #$1F
    $257D: 8D 03 D2  STA $D203       ; AUDC2 = $1F (DAC pop vol 15)
    $2580: A9 1B     LDA #$1B
    $2582: 8D 01 D2  STA $D201       ; AUDC1 = $1B (DAC pop vol 11)
    $2585: AD 06 20  LDA $2006       ; SNARE_PITCH_AUDF1 (default $01)
    $2588: 8D 00 D2  STA $D200       ; AUDF1 = $2006
    $258B: A9 00     LDA #$00
    $258D: 8D 03 D2  STA $D203       ; AUDC2 = $00 (end CH2 pop)
    $2590: A9 08     LDA #$08
    $2592: 8D 00 20  STA $2000       ; ENV_STEP_CNT = 8
    $2595: AD 05 20  LDA $2005       ; SNARE_TONE_BASE (default $16)
    $2598: 8D 01 20  STA $2001       ; SWEEP_AUDF_ACC = $2005
loop_snare:
    $259B: 18        CLC
    $259C: A9 80     LDA #$80
    $259E: 6D 00 20  ADC $2000       ; $88..$80
    $25A1: 8D 01 D2  STA $D201       ; AUDC1 = poly17 noise, vol 8->0
    $25A4: AD 06 20  LDA $2006
    $25A7: 8D 00 D2  STA $D200       ; AUDF1 = $2006
    $25AA: 18        CLC
    $25AB: AD 01 20  LDA $2001
    $25AE: 69 02     ADC #$02        ; Sweep AUDF2 downward by +$02 per step
    $25B0: 8D 01 20  STA $2001
    $25B3: 8D 02 D2  STA $D202       ; AUDF2 = $2001 ($18..$28)
    $25B6: 18        CLC
    $25B7: A9 A1     LDA #$A1
    $25B9: 6D 00 20  ADC $2000       ; $A9..$A1
    $25BC: 8D 03 D2  STA $D203       ; AUDC2 = pure tone, vol 9->1
    $25BF: 20 1E 27  JSR $271E       ; Delay 1 sub-frame step (~7.14 ms)
    $25C2: CE 00 20  DEC $2000
    $25C5: AD 00 20  LDA $2000
    $25C8: C9 FF     CMP #$FF
    $25CA: D0 CF     BNE $259B
    $25CC: A9 00     LDA #$00
    $25CE: 8D 01 D2  STA $D201       ; AUDC1 = $00
    $25D1: 8D 03 D2  STA $D203       ; AUDC2 = $00
    $25D4: 8D 86 20  STA $2086       ; Clear UI indicator
    $25D7: 60        RTS
```

---

### 2.5 Instrument 4: `SPACE>BASS DRUM` (`TRIG_BASS_DRUM`, `$272E–$2797`)
- **Entry address:** `$272E` (triggered by key `'SPACE'`, `CH = $21`)
- **Input parameters:** `$2002` (step delay)
- **Modified memory:** `$20AE` (UI indicator), `$2000` (`8..$FF`), `$2001` (starts at `$4A`, adds `+$12` per active step)
- **POKEY registers written:** `AUDCTL ($D208)`, `AUDF1 ($D200)`, `AUDC1 ($D201)`, `AUDF2 ($D202)`, `AUDC2 ($D203)`
- **Active duration:** **2 steps** (`$2000 = 8, 7` → `25,398` cycles = **`14.32 ms` PAL** at `$2002=$07`), followed by **7 silent steps** (`$2000 = 6..0` → `49.96 ms` PAL). Total routine duration: `114,000` cycles (`64.28 ms` PAL).
- **Algorithm & Register Evolution:**
  1. **Attack DAC Pop (`cycles 8..32`):**
     - `AUDCTL = $01` (15 kHz base clock).
     - `AUDC2 = $1F` (DAC pop vol 15), `AUDC1 = $1B` (DAC pop vol 11), `AUDF1 = $02`, `AUDC2 = $00`.
  2. **2-Step Low-Frequency Punch (`$2000 = 8, 7`; `CMP #$07 / BPL $276C`):**
     - Initializes `$2001 = $4A` (74).
     - **Step 0 (`$2000 = 8`):**
       - `AUDC1 = $85` (17-bit poly noise at `AUDF1 = $02` [5.23 kHz clock], constant volume 5 — beater click/thud).
       - `AUDF2 = $4A + $12 = $5C` (92 decimal → $15699.8 / (2 \times 93) = \mathbf{84.41\text{ Hz}}$ fundamental).
       - `AUDC2 = $AC` (pure tone, constant **volume 12**).
     - **Step 1 (`$2000 = 7`):**
       - `AUDC1 = $85` (constant volume 5).
       - `AUDF2 = $5C + $12 = $6E` (110 decimal → $15699.8 / (2 \times 111) = \mathbf{70.72\text{ Hz}}$ sub-bass drop).
       - `AUDC2 = $AC` (constant **volume 12**).
  3. **Silent Tail (`$2000 = 6..0`):** `AUDC1 = $00`, `AUDC2 = $00`, `$20AE = $00`.

---

### 2.6 Instruments 5, 6, 7: `4>TOM 1` (`$28D2`), `5>TOM 2` (`$2937`), `6>TOM 3` (`$299C`)
All three Tom subroutines share the **exact same 101-byte code template** under `AUDCTL = $01` (15 kHz base clock), differing only in three constants:
1. Screen UI indicator address (`$20D6`, `$20FE`, `$2126`),
2. Initial pitch accumulator `$2001` (`$1F`, `$2E`, `$38`), and
3. Active step cutoff threshold (`CMP #$04` [5 steps], `CMP #$03` [6 steps], `CMP #$02` [7 steps]):

| Parameter / Behavior | `4>TOM 1` (`$28D2–$2936`) | `5>TOM 2` (`$2937–$299B`) | `6>TOM 3` (`$299C–$2A00`) |
| --- | :---: | :---: | :---: |
| **Trigger Key (`CH`)** | `'4'` (`$18`) | `'5'` (`$1D`) | `'6'` (`$1B`) |
| **`AUDCTL`** | `$01` (15 kHz clock) | `$01` (15 kHz clock) | `$01` (15 kHz clock) |
| **Initial DAC Pop** | `AUDC2=$1F`, `AUDF1=$01`, `AUDC2=$00` (12 cyc) | `AUDC2=$1F`, `AUDF1=$01`, `AUDC2=$00` (12 cyc) | `AUDC2=$1F`, `AUDF1=$01`, `AUDC2=$00` (12 cyc) |
| **Active Steps (`$2000`)** | **5 steps** (`8..4`, `35.79 ms` PAL) | **6 steps** (`8..3`, `42.93 ms` PAL) | **7 steps** (`8..2`, `50.09 ms` PAL) |
| **Silent Steps (`$2000`)** | 4 steps (`3..0`, `28.54 ms` PAL) | 3 steps (`2..0`, `21.41 ms` PAL) | 2 steps (`1..0`, `14.27 ms` PAL) |
| **CH1 Noise (`AUDF1=$01`)** | `AUDC1 = $7F + $2000`: **`$87..$83`** (vol `7→3`) | `AUDC1 = $7F + $2000`: **`$87..$82`** (vol `7→2`) | `AUDC1 = $7F + $2000`: **`$87..$81`** (vol `7→1`) |
| **CH2 Initial `$2001`** | `$1F` (`+$04`/step) | `$2E` (`+$04`/step) | `$38` (`+$04`/step) |
| **CH2 `AUDF2` Sequence** | **`$23, $27, $2B, $2F, $33`** | **`$32, $36, $3A, $3E, $42, $46`** | **`$3C, $40, $44, $48, $4C, $50, $54`** |
| **CH2 Frequency Sweep (PAL)** | **`218.1 Hz → 150.9 Hz`** | **`153.9 Hz → 110.6 Hz`** | **`128.7 Hz → 92.4 Hz`** |
| **CH2 Tone `AUDC2` (`$A3+$2000`)** | **`$AB, $AA, $A9, $A8, $A7`** (vol `11→7`) | **`$AB, $AA, $A9, $A8, $A7, $A6`** (vol `11→6`) | **`$AB, $AA, $A9, $A8, $A7, $A6, $A5`** (vol `11→5`) |

---

### 2.7 Instrument 8: `7>WOOD BLOCK` (`TRIG_WOOD_BLOCK`, `$2844–$2894`)
- **Entry address:** `$2844` (triggered by key `'7'`, `CH = $33`)
- **Input parameters:** `$2002` (step delay)
- **Modified memory:** `$214E` (UI indicator), `$2000` (`8..$FF`)
- **POKEY registers written:** `AUDCTL ($D208)`, `AUDF1 ($D200)`, `AUDC1 ($D201)`, `AUDF2 ($D202)`, `AUDC2 ($D203)`
- **Active duration:** **3 steps** (`$2000 = 8, 7, 6` → `38,037` cycles = **`21.45 ms` PAL** at `$2002=$07`), followed by **6 silent steps** (`$2000 = 5..0`). Total routine duration: `113,982` cycles (`64.27 ms` PAL).
- **Algorithm & Register Evolution:**
  - Sets `AUDCTL = $00` (64 kHz base clock).
  - During active steps `8, 7, 6` (`CMP #$06 / BPL $2869`), drives **both CH1 and CH2 with 17-bit poly noise (`$80`) at two fixed, inharmonic clock dividers**:
    - `AUDC1 = AUDC2 = $7D + $2000` → **`$85, $84, $83`** (volume `5 → 4 → 3` on both channels simultaneously).
    - `AUDF1 = $07` (clock rate $= 63920.4 / 8 = 7990.1\text{ Hz}$, toggle max $3995.0\text{ Hz}$).
    - `AUDF2 = $14` (20 decimal; clock rate $= 63920.4 / 21 = 3043.8\text{ Hz}$, toggle max $1521.9\text{ Hz}$).
  - Because both channels sample the same shared 17-bit polynomial counter at a `21 : 8` divider ratio (`2.625 : 1`), their cross-correlated sample-and-hold outputs interfere to produce a short, hollow, band-limited percussive knock.

---

### 2.8 Instrument 9: `8>CLAPS` (`TRIG_CLAPS`, `$27F3–$2843`) — Including Confirmed `$D5EB` Bug
- **Entry address:** `$27F3` (triggered by key `'8'`, `CH = $35`)
- **Input parameters:** `$2002` (step delay)
- **Modified memory:** `$2176` (UI indicator), `$2000` (`8..$FF`)
- **POKEY registers written:** `AUDCTL ($D208)`, `AUDF1 ($D200)`, `AUDC1 ($D201)`, `AUDF2 ($D202)`, `AUDC2 ($D203)` (on mute only!), plus bogus write to **`$D5EB`**
- **Active duration:** **8 steps** (`$2000 = 8..1` → `101,382` cycles = **`57.17 ms` PAL** at `$2002=$07`), followed by **1 silent step** (`$2000 = 0`). Total routine duration: `114,042` cycles (`64.31 ms` PAL).
- **Disassembly & Bug Analysis (`$27F3–$2843`):**
```asm
TRIG_CLAPS:
    $27F3: A9 54     LDA #$54
    $27F5: 8D 76 21  STA $2176       ; Display 'T' indicator next to 8>CLAPS
    $27F8: A9 00     LDA #$00
    $27FA: 8D 08 D2  STA $D208       ; AUDCTL = $00 (64 kHz base clock)
    $27FD: A9 08     LDA #$08
    $27FF: 8D 00 20  STA $2000       ; ENV_STEP_CNT = 8
loop_claps:
    $2802: 18        CLC
    $2803: AD 00 20  LDA $2000
    $2806: C9 01     CMP #$01        ; Active for 8 steps ($2000 = 8..1)
    $2808: 10 0E     BPL $2818
    $280A: A9 00     LDA #$00        ; Silent step ($2000 = 0)
    $280C: 8D 01 D2  STA $D201       ; AUDC1 = $00
    $280F: 8D 03 D2  STA $D203       ; AUDC2 = $00
    $2812: 8D 76 21  STA $2176       ; Clear UI indicator
    $2815: 4C 2E 28  JMP $282E
active_claps:
    $2818: 18        CLC
    $2819: A9 80     LDA #$80
    $281B: 6D 00 20  ADC $2000       ; $80 + (8..1) = $88..$81
    $281E: 8D 01 D2  STA $D201       ; AUDC1 = $88..$81 (poly17 noise, vol 8->1)
    $2821: 8D EB D5  STA $D5EB       ; *** BUG: writes to $D5EB instead of $D203 (AUDC2)! ***
    $2824: A9 12     LDA #$12
    $2826: 8D 00 D2  STA $D200       ; AUDF1 = $12 (18 -> 3,364 Hz sample rate / 1,682 Hz toggle)
    $2829: A9 1E     LDA #$1E
    $282B: 8D 02 D2  STA $D202       ; AUDF2 = $1E (30 -> intended 2,062 Hz CH2 clock, but AUDC2=$00!)
step_delay_claps:
    $282E: 20 1E 27  JSR $271E
    $2831: CE 00 20  DEC $2000
    $2834: AD 00 20  LDA $2000
    $2837: C9 FF     CMP #$FF
    $2839: D0 C7     BNE $2802
    $283B: A9 00     LDA #$00
    $283D: 8D 01 D2  STA $D201       ; AUDC1 = $00
    $2840: 8D 03 D2  STA $D203       ; AUDC2 = $00
    $2843: 60        RTS
```

> [!WARNING]
> **Confirmed Bug in Original `rhytmizer.xex` (`$2821: 8D EB D5`):**
> Compare `TRIG_CLAPS` (`$2818–$282D`) with `TRIG_WOOD_BLOCK` (`$2869–$287E`) immediately following it in memory:
> - `TRIG_WOOD_BLOCK` writes `STA $D201` (`8D 01 D2`), `STA $D203` (`8D 03 D2`), `LDA #$07 / STA $D200`, `LDA #$14 / STA $D202`.
> - `TRIG_CLAPS` writes `STA $D201` (`8D 01 D2`), **`STA $D5EB` (`8D EB D5`)**, `LDA #$12 / STA $D200`, `LDA #$1E / STA $D202`, and still mutes `STA $D203` (`AUDC2`) at `$280F` and `$2840`.
> - Because `$D5EB` is unmapped cartridge space (`CCTL`), **actual hardware execution of `rhytmizer.xex` plays `8>CLAPS` as a single-channel (`CH1`) 17-bit poly noise burst at `AUDF1 = $12` (`AUDC1 = $88..$81`)**, while `CH2` remains silent (`AUDC2 = $00`). Both the authentic as-executed single-channel behavior and the intended dual-channel (`AUDC2 = $88..$81`, `AUDF2 = $1E`) reconstruction are documented in our catalog and compatibility report.

# Phase A — Rhytmizer Binary Inspection & Memory Layout Analysis

- **Target binary:** `rhytmizer.xex`
- **File size:** `6,333` bytes (`$18BD` bytes)
- **SHA-256:** `d22206b9324ff5f9a13eaba213009aeb3d6df6d69bb56c1fdbf48cc41045c772`
- **Original program title & credit:** `Rythmizer AT1` / `(c)MUNSIE 1986` (with startup splash screen `"BRO-BEAT STRIKES BACK! ... Bustin up shits in 1986!"`)
- **Target architecture:** Atari 8-bit (MOS 6502 CPU, POKEY `$D200–$D20F`, ANTIC Mode 2 display lists, Atari OS CIO/SIO)

---

## 1. Executive Findings on Binary Structure

> [!IMPORTANT]
> **Two-Stage Self-Relocating Binary Architecture:**
> Static inspection of `rhytmizer.xex` at its raw XEX load addresses (`$2A80–$42FF`) will yield completely wrong code addresses unless the **two-stage relocation pipeline** is resolved first:
> 1. **Stage 1 (`$4300–$432A`, executed via `RUNAD = $4300`)** copies 25 pages (`$1900` = 6,400 bytes) downward by `-$2380` bytes from `$2A80–$437F` to **`$0700–$1FFF`**, zeroes `CASINI` (`$02/$03`) and `DOSINI` (`$0C/$0D`), and calls `JSR $0706`.
> 2. **Stage 2 (`$0706–$0798`)** iterates through a **17-entry 6-byte backward block-copy descriptor table** at `$079F–$0804` (`count = $11` at `$0700`), moving and unpacking the payload from `$0805–$1F36` into two runtime regions while zeroing the source bytes behind it:
>    - **`$B800–$BBEF` (`1,008` bytes):** Splash/title screen routine (`$B800–$B80F`), ANTIC Mode 2 Display List (`$B810–$B82F`), and 24×40 screen RAM (`$B830–$BBEF`).
>    - **`$200B–$333B` (`4,913` bytes):** Main application variables, main UI screen RAM, main Display List, all 6502 executable code (including all 9 percussion synthesis routines and the `SKIP A BEAT` rest routine), and the 1,246-byte built-in Demonstration Pattern (`$2E5D–$333B`).
> 3. **Final Entry Transfer (`$073A–$073D`):** Stage 2 executes `JSR $B800` (displaying the `$B830` splash screen) and then `JMP $2540` (never returning to the `$4325: JSR $1880` instruction in Stage 1).

---

## 2. XEX File Segment Map

`rhytmizer.xex` is a standard Atari DOS binary load file consisting of **3 segments**:

| Segment | File Offset (Hex) | `$FF $FF` Marker | Start Address | End Address | Payload Size | Classification & Role |
| :---: | :---: | :---: | :---: | :---: | :---: | --- |
| **0** | `0x0000–0x1885` | Yes (`0x0000–0x0001`) | `$2A80` | `$42FF` | `6,272` bytes (`$1880`) | **Packed Runtime Image:** Stage 2 unpacker (`$2A80–$2B84` → `$0700–$0804`), main program/UI/demo pattern (`$2B85–$3EB5` → `$0805–$1B35` → `$200B–$333B`), padding descriptors (`$3EB6–$3EC2`), title screen (`$3EC3–$42B2` → `$1B43–$1F32` → `$B800–$BBEF`), vector values (`$42B3–$42B6`), trailing zeros (`$42B7–$42FF`). |
| **1** | `0x1886–0x18B6` | Yes (`0x1886–0x1887`) | `$4300` | `$432A` | `43` bytes (`$002B`) | **Stage 1 Relocator Stub:** Self-modifying page-copy loop moving `$2A80–$437F` to `$0700–$1FFF`, followed by `JSR $0706`. |
| **2** | `0x18B7–0x18BC` | No | `$02E0` | `$02E1` | `2` bytes (`$0002`) | **DOS Run Address Vector (`RUNAD`):** Little-endian word `00 43` → **`$4300`**. |

---

## 3. Two-Stage Relocation & Unpacking Pipeline

### 3.1 Stage 1 Relocator (`$4300–$432A`)

```asm
$4300: A0 00     LDY #$00
$4302: A2 19     LDX #$19        ; Copy 25 pages ($1900 = 6,400 bytes)
$4304: B9 80 2A  LDA $2A80,Y     ; Self-modified high byte at $4306 ($2A -> $42)
$4307: 99 00 07  STA $0700,Y     ; Self-modified high byte at $4309 ($07 -> $1F)
$430A: C8        INY
$430B: D0 F7     BNE $4304
$430D: EE 06 43  INC $4306       ; Advance source page
$4310: EE 09 43  INC $4309       ; Advance destination page
$4313: CA        DEX
$4314: D0 EE     BNE $4304
$4316: A9 00     LDA #$00
$4318: 85 02     STA $02         ; CASINI lo = $00
$431A: 85 0C     STA $0C         ; DOSINI lo = $00
$431C: A9 00     LDA #$00
$431E: 85 03     STA $03         ; CASINI hi = $00
$4320: 85 0D     STA $0D         ; DOSINI hi = $00
$4322: 20 06 07  JSR $0706       ; Enter Stage 2 unpacker (never returns!)
$4325: 20 80 18  JSR $1880       ; Dead instruction (residue of generic packer stub)
$4328: 6C 0A 00  JMP ($000A)     ; Dead instruction (DOSVEC)
```

### 3.2 Stage 2 Descriptor-Driven Backward Copier (`$0700–$0804`)

Stage 2 (`$0706–$0798`) first writes an `RTS` (`$60`) opcode into `$06FF` and points `INITAD` (`$02E2/$02E3`) to `$06FF`. It then initializes zero-page pointer `$80/$81 = $079F` and loops `X` from `$00` up to `$0700` (`$11` = 17 descriptors).

For each 6-byte descriptor at `($80),Y`, it copies 6 bytes into Zero Page `$82–$87`:
- `$82/$83`: `copy_length` (16-bit byte count)
- `$84/$85`: `dst_end` (inclusive end address of destination block)
- `$86/$87`: `src_end` (inclusive end address of source block in Stage 1 `$0700–$1FFF` buffer)

It copies each byte from `($86)` to `($84)`, **clears `($86)` to `$00`**, and decrements `$86/$87`, `$84/$85`, and `$82/$83` until `copy_length == 0`.

| Desc # | Table Addr | Length | Stage 1 Source Range | Raw XEX Offset | Runtime Destination Range | Purpose |
| :---: | :---: | :---: | :---: | :---: | :---: | --- |
| **0** | `$079F` | `$0002` (2 B) | `$1F33–$1F34` | `0x1835–0x1836` | `$02E0–$02E1` (`RUNAD`) | Sets `RUNAD = $2540` |
| **1** | `$07A5` | `$0002` (2 B) | `$1F35–$1F36` | `0x1837–0x1838` | `$02E2–$02E3` (`INITAD`) | Sets `INITAD = $B800` |
| **2** | `$07AB` | `$03F0` (1,008 B) | `$1B43–$1F32` | `0x1445–0x1834` | **`$B800–$BBEF`** | **Title Screen Code, DLIST & Screen RAM** |
| **3** | `$07B1` | `$1331` (4,913 B) | `$0805–$1B35` | `0x0107–0x1437` | **`$200B–$333B`** | **Main Application Variables, UI Screen RAM, DLIST, Code & Demo Pattern** |
| **4–16** | `$07B7–$07FF` | `$0001` × 13 (13 B) | `$1B36–$1B42` | `0x1438–0x1444` | `$2020` (×13) | 13 single-byte transfers writing `$29` (`')'`) or `$00` to `$2020` (top border of UI screen RAM, finally `$52` `'R'` horizontal bar). |

After processing all 17 descriptors (198,766 CPU instructions total from `$4300`), Stage 2 executes:
- `$0725`: `LDA #$00 / STA $0244` (`COLDST = 0`)
- `$072A`: `LDA #$03 / STA $09` (`BOOT? = 3`)
- `$072E`: `CASINI ($02/$03) = $06FF`, `DOSINI ($0C/$0D) = $06FF` (points warm-start vectors to the `RTS` at `$06FF`)
- `$073A`: `JSR $B800` (initializes splash screen Display List at `$B810`)
- `$073D`: `JMP $2540` (transfers control to Main Application Entry at `$2540`)

---

## 4. Complete Runtime Memory Map (Post-Relocation)

| Runtime Address Range | Size | Type | Classification & Detailed Contents |
| :---: | :---: | :---: | --- |
| `$0002–$0003` | 2 B | OS ZP | `CASINI` vector → set to `$06FF` (`RTS`) |
| `$0009` | 1 B | OS ZP | `BOOT?` flag → set to `$03` |
| `$000C–$000D` | 2 B | OS ZP | `DOSINI` vector → set to `$06FF` (`RTS`) |
| `$004D` | 1 B | OS ZP | `ATRACT` attract-mode timer → reset to `$00` every playback step (`$2AD9`) |
| `$0080–$0087` | 8 B | App ZP | Stage 2 unpacker pointers (`$80/$81` table ptr, `$82/$83` len, `$84/$85` dst, `$86/$87` src) |
| `$00CC–$00CD` | 2 B | App ZP | **`ZP_PAT_PTR`**: 16-bit pointer to current step in active rhythm pattern (`$2E5D` for Demo, `$333C` for User pattern) |
| `$0230–$0231` | 2 B | OS Shadow | `SDLSTL`/`SDLSTH`: set to `$B810` by `$B800`, then immediately overwritten with **`$24F2`** at `$2557–$255C` |
| `$0244` | 1 B | OS Shadow | `COLDST`: cleared to `$00` |
| `$02C6`, `$02C8` | 2 B | OS Shadow | `COLOR2` (background) and `COLOR4` (border): set to `$90` (blue) by `$B80A`, then `$00` (black) by `$254F–$2552` |
| `$02E0–$02E3` | 4 B | OS Vector | `RUNAD` (`$2540`) and `INITAD` (`$B800`) |
| `$02FC` | 1 B | OS Shadow | `CH`: hardware keyboard keycode shadow register polled by Record/Play loops (`$FF` = no key) |
| `$0340–$035F` | 32 B | OS IOCB | `IOCB #1` (`X = $10`): used for disk file I/O (`D:xxxxxxxx.DRM`) and `K:` keyboard input via `CIOV ($E456)` |
| `$0600` | 1 B | Scratch | Temporary storage for first byte of user pattern during `^S` Save Pattern (`$2CF8`) |
| `$06FF` | 1 B | Stub / Scratch | Initialized to `$60` (`RTS`) for `CASINI`/`DOSINI`; later used to cache `ICSTA` (`$0353`) during disk I/O (`$2CE4`, `$2DDD`) |
| `$0700–$0804` | 261 B | Code + Table | Stage 2 unpacker code (`$0706–$0798`) and 17-entry relocation descriptor table (`$079F–$0804`) |
| **`$2000–$200A`** | **11 B** | **State / Vars** | **Sound Engine & Sequencer Runtime Variables** (see Section 5 below) |
| **`$200B–$24BA`** | **1,200 B** | **Screen RAM** | **Main UI Screen Buffers** (30 rows × 40 columns of Atari screen codes, mapped into 24 visible lines by `$24F2` Display List; includes alternate status lines `MODE=RECORD`, `MODE=PLAY`, `INPUT FILENAME TO LOAD`, `INPUT FILENAME TO SAVE`, `DISK ERROR`, `FILE NOT FOUND!!`) |
| **`$24BB–$24CD`** | **19 B** | **I/O Buffer** | CIO filename string buffer: `"D:        .DRM\x9b"` (`$24BB–$24C9`, where `$24BD–$24C4` holds the 8-char filename) |
| `$24CE–$24F1` | 36 B | Padding | Unused screen/buffer padding |
| **`$24F2–$253F`** | **78 B** | **Display List** | **Main UI ANTIC Mode 2 Display List:** `70 70 70`, 24 × (`42 lo hi` LMS Mode 2 lines), `41 F2 24` (`JVB $24F2`). Dynamically modified at `$252F/$2530` (Mode line LMS) and `$2535/$2536` (Prompt/Error line LMS). |
| **`$2540–$2570`** | **49 B** | **Code** | **Main Entry & Initialization (`APP_MAIN_ENTRY`)** |
| **`$2571–$25D7`** | **103 B** | **Code (Sound)** | **Instrument Trigger Routine: `3>SNARE` (`$2571`)** |
| **`$25D8–$26CD`** | **246 B** | **Code** | **Record Mode Loop & Key Dispatcher (`ENTER_RECORD_MODE`)** |
| **`$26CE–$271D`** | **80 B** | **Code (Sound)** | **Instrument Trigger Routine: `1>HH CLOSED` (`$26CE`)** |
| **`$271E–$272D`** | **16 B** | **Code (Timing)** | **Shared Sub-Frame Tempo Delay Loop (`DELAY_TEMPO_STEP`)** |
| **`$272E–$2797`** | **106 B** | **Code (Sound)** | **Instrument Trigger Routine: `SPACE>BASS DRUM` (`$272E`)** |
| **`$2798–$27F2`** | **91 B** | **Code (Sound)** | **Instrument Trigger Routine: `2>HH ACCENT` (`$2798`)** |
| **`$27F3–$2843`** | **81 B** | **Code (Sound)** | **Instrument Trigger Routine: `8>CLAPS` (`$27F3`)** |
| **`$2844–$2894`** | **81 B** | **Code (Sound)** | **Instrument Trigger Routine: `7>WOOD BLOCK` (`$2844`)** |
| **`$2895–$28D1`** | **61 B** | **Code (Sound)** | **Rest / Silence Routine: `*>SKIP A BEAT` (`$2895`)** |
| **`$28D2–$2936`** | **101 B** | **Code (Sound)** | **Instrument Trigger Routine: `4>TOM 1` (`$28D2`)** |
| **`$2937–$299B`** | **101 B** | **Code (Sound)** | **Instrument Trigger Routine: `5>TOM 2` (`$2937`)** |
| **`$299C–$2A00`** | **101 B** | **Code (Sound)** | **Instrument Trigger Routine: `6>TOM 3` (`$299C`)** |
| **`$2A01–$2B66`** | **358 B** | **Code** | **Pattern Sequencer, Event Recorder & Play Mode Dispatcher** |
| **`$2B67–$2BB5`** | **79 B** | **Code** | **UI Step Counter (`00000`) & Snare Tone (`$2005`) Adjustment Helpers** |
| **`$2BB6–$2E46`** | **657 B** | **Code + Data** | **CIO Disk Load/Save (`^L`/`^S`), Filename Prompt & Error Handlers** |
| **`$2E47–$2E5C`** | **22 B** | **Code** | **Snare Pitch (`$2006`) Adjustment Helpers** |
| **`$2E5D–$333B`** | **1,247 B** | **Pattern Data** | **Built-in Demonstration Pattern (`DEMO_PATTERN_DATA`):** 1,246 step keycodes (`$2E5D–$333A`) terminated by `$64` at `$333B`. |
| **`$333C+`** | **Variable** | **RAM Buffer** | **User Record/Play/Load Pattern Buffer (`USER_PATTERN_BUFFER`):** Starts at `$333C` (immediately after the demo pattern). Note: prior to recording or loading a pattern, `$333C–$42FF` still holds unzeroed pre-relocation bytes from Segment 0. |
| **`$B800–$BBEF`** | **1,008 B** | **Code + Screen** | **Splash Screen Module:** `$B800–$B80F` init subroutine, `$B810–$B82F` Mode 2 Display List, `$B830–$BBEF` 24×40 screen RAM (`"BRO-BEAT STRIKES BACK!"`). |

---

## 5. Sound Engine, Pattern & Playback State Variables (`$2000–$200A`)

All synthesis state and user-tunable parameters reside in an 11-byte block immediately preceding the main UI screen memory at `$2000–$200A`:

| Address | Symbol | Default (Init `$2540`) | Demo Mode (`$26AE`) | Role & Usage |
| :---: | --- | :---: | :---: | --- |
| **`$2000`** | `ENV_STEP_CNT` | Transient | Transient | **Envelope loop counter:** Initialized to `$08` at the start of every instrument trigger routine and decremented (`8, 7, 6, 5, 4, 3, 2, 1, 0` → `$FF` exits) across **9 sub-frame steps**. Directly added to base `AUDC` values to create linear volume decay envelopes. |
| **`$2001`** | `SWEEP_AUDF_ACC` | Transient | Transient | **Pitch sweep accumulator:** Initialized at instrument trigger (`$2005` for Snare, `$4A` for Bass Drum, `$1F` for Tom 1, `$2E` for Tom 2, `$38` for Tom 3) and incremented each loop iteration (`+$02` for Snare, `+$12` for Bass Drum, `+$04` for Toms 1–3) before writing `AUDF2 ($D202)`. |
| **`$2002`** | `TEMPO_DELAY_HI` | **`$07`** | **`$08`** | **Sub-frame step duration / Tempo divisor:** Controls outer loop iterations in `$271E` (`CPX $2002`). Each increment of `$2002` adds `1,805` CPU cycles (`~1.018 ms` PAL) to each of the 9 steps of every instrument (`+9.16 ms` per beat). Modified in Play Mode via Left/Right arrow keys (`CH = $06` decrements, `CH = $07` increments). Saved as Byte 0 of `.DRM` files. |
| **`$2003`** | `LAST_REC_KEY` | Uninit | Uninit | Stores the last recorded keycode in `$2A18`. |
| **`$2004`** | `CIO_CHAR_BUF` | Uninit | Uninit | 1-byte buffer for `K:` keyboard character read via `CIOV` during filename input (`$2C2F`). |
| **`$2005`** | `SNARE_TONE_BASE` | **`$16`** | **`$18`** | **Snare Tone (CH2 initial frequency divider):** Loaded into `$2001` at Snare trigger (`$2595`), then incremented by `+$02` per step (`AUDF2 = $2005 + 2*(9 - $2000)`). Modified in Play Mode via Up/Down arrow keys (`CH = $0E` decrements down to `$01`; `CH = $0F` increments up to `$FF`). Saved as Byte 2 of `.DRM` files. |
| **`$2006`** | `SNARE_PITCH_AUDF1` | **`$01`** | **`$01`** | **Snare Pitch (CH1 noise clock divider):** Written directly to `AUDF1 ($D200)` during Snare playback (`$2585`, `$25A4`). Modified in Play Mode via `Ctrl+Up` / `Ctrl+Down` (`CH = $8E` decrements down to `$00`; `CH = $8F` increments up to `$FF`). Note: the UI screen labels `↑↓ TUNES SNARE PITCH` and `^↑^↓ TUNES SNARE TONE` are swapped relative to the acoustic effect (`$2005` tunes the CH2 pure-tone sweep, while `$2006` tunes the CH1 noise clock). Saved as Byte 1 of `.DRM` files. |
| **`$2007`** | `FNAME_CHAR_IDX` | `$00` | `$00` | Character index (`0..8`) while typing an 8-character filename in `$2C4E`. |
| **`$2008`** | *(Unused)* | `$00` | `$00` | Unused padding byte. |
| **`$2009`** | `HAS_RECORDED_FLAG` | **`$00`** | `$00` | Set to `$01` by `$2A18` as soon as at least one event is recorded. Checked when pressing `ESC` (`$2A30`): if `$2009 == 0`, `ESC` restarts Record Mode instead of entering Play Mode on an empty buffer. |
| **`$200A`** | `DEMO_MODE_FLAG` | **`$00`** | **`$01`** | Pattern source selector read by `$2A01`: `$00` selects the User Pattern Buffer (`$CC/$CD = $333C`), `$01` selects the built-in Demo Pattern (`$CC/$CD = $2E5D`). |

---

## 6. Hardware Register & OS Routine References

### 6.1 Hardware Registers Accessed

| Address | Register | Chip | Access Type | Instruction Sites | Purpose in Rhytmizer |
| :---: | --- | :---: | :---: | --- | --- |
| **`$D200`** | `AUDF1` | POKEY | Write (`STA`) | `$2588`, `$25A7`, `$26FA`, `$2744`, `$27C4`, `$2826`, `$2877`, `$28E3`, `$2948`, `$29AD` | Channel 1 frequency divider (drives 17-bit poly noise clock for all 9 instruments). |
| **`$D201`** | `AUDC1` | POKEY | Write (`STA`) | `$2582`, `$25A1`, `$25CE`, `$26EC`, `$2703`, `$273F`, `$2760`, `$276E`, `$2791`, `$27B6`, `$27CD`, `$27E9`, `$280C`, `$281E`, `$283D`, `$285D`, `$286F`, `$288E`, `$2897`, `$28AC`, `$28B7`, `$28BB`, `$28FF`, `$2911`, `$2964`, `$2976`, `$29C9`, `$29DB` | Channel 1 distortion & volume control (`$1B` DAC transient, `$80–$88` 17-bit poly noise envelope, `$00` mute). |
| **`$D202`** | `AUDF2` | POKEY | Write (`STA`) | `$25B3`, `$270D`, `$277A`, `$27D7`, `$282B`, `$287C`, `$291D`, `$2982`, `$29E7` | Channel 2 frequency divider (metallic overtone `$08`, wood block `$14`, claps `$1E`, bass drum step `$5C/$6E`, or pitch sweep `$2001`). |
| **`$D203`** | `AUDC2` | POKEY | Write (`STA`) | `$257D`, `$258D`, `$25BC`, `$25D1`, `$26EF`, `$2708`, `$273A`, `$2749`, `$2763`, `$277F`, `$2794`, `$27B9`, `$27D2`, `$27EC`, `$280F`, `$2840`, `$2860`, `$2872`, `$2891`, `$289A`, `$28AF`, `$28BE`, `$28DE`, `$28E8`, `$2902`, `$2926`, `$2943`, `$294D`, `$2967`, `$298B`, `$29A8`, `$29B2`, `$29CC`, `$29F0` | Channel 2 distortion & volume control (`$1F` DAC transient, `$A1–$AC` pure tone envelope, `$83–$85` poly17 wood block, `$00` mute). |
| **`$D208`** | `AUDCTL` | POKEY | Write (`STA`) | `$2545`, `$2578`, `$26DA`, `$2735`, `$27A4`, `$27FA`, `$284B`, `$28C1`, `$28D9`, `$293E`, `$29A3` | Audio control register: set to **`$00`** (64 kHz base clock) for HH Closed, HH Accent, Wood Block, Claps, and Skip a Beat; set to **`$01`** (15 kHz base clock) for Snare, Bass Drum, and Toms 1–3. |
| **`$D20F`** | `SKCTL` | POKEY | Write (`STA`) | `$254A` | Initialized once to **`$03`** (enable keyboard scan and debounce). |
| **`$D5EB`** | `CCTL` area | Cart | Write (`STA`) | **`$2821`** (`8D EB D5`) | **Confirmed Original Bug in `8>CLAPS`:** At `$2821`, right after `STA $D201` (`AUDC1`), the code executes `STA $D5EB` instead of `STA $D203` (`AUDC2`) before writing `AUDF2 = $1E` at `$282B`. Because `$D5EB` is unmapped cartridge control space, Channel 2 remains muted (`AUDC2 = $00`) during Claps. |

> [!NOTE]
> **Unused POKEY & ANTIC Registers:**
> - **POKEY Channels 3 and 4 (`$D204–$D207`)** and **`STIMER` (`$D209`)** are **never accessed** anywhere in `rhytmizer.xex`.
> - **ANTIC registers (`$D400–$D40E`, including `WSYNC` `$D40A` and `VCOUNT` `$D40B`)** are **never accessed directly**; Display List updates use OS VBI shadow registers `SDLSTL`/`SDLSTH` (`$0230/$0231`).

### 6.2 Operating System Routines & Vectors Used

| Address | Symbol | Call Sites | Purpose |
| :---: | --- | --- | --- |
| **`$E456`** | `CIOV` | `$2BCE`, `$2BE3`, `$2C04`, `$2C2B`, `$2C4A` | Central I/O Vector: used on IOCB #1 (`X = $10`) to open/read/write/close pattern files (`D:xxxxxxxx.DRM`) and read keyboard characters from `K:` during filename entry. |
| **`$E465`** | `SIOINV` | `$2540` | Serial I/O Initialization Vector: called once at startup (`$2540: JSR $E465`) to initialize POKEY/SIO state before setting `AUDCTL = $00` and `SKCTL = $03`. |

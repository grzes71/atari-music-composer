; ==========================================================================
; RHYTMIZER (1986, (c) MUNSIE) - COMPLETE ANNOTATED 6502 DISASSEMBLY
; Source binary: rhytmizer.xex (6,333 bytes, SHA-256: d22206b9...c772)
; Target: Atari 8-bit (MOS 6502 + POKEY + ANTIC)
; Generated via static & dynamic py65 reverse-engineering analysis
; ==========================================================================

; ==========================================================================
; STAGE 1 BOOTLOADER / RELOCATOR ($4300..$432A, Segment 1)
; Copies 25 pages ($1900 bytes) from $2A80..$437F down to $0700..$1FFF,
; clears CASINI/DOSINI, calls Stage 2 unpacker at $0706.
; ==========================================================================
    $4300: A0 00     LDY #$00        
    $4302: A2 19     LDX #$19        
    $4304: B9 80 2A  LDA $2a80,Y     
    $4307: 99 00 07  STA $0700,Y      ; STAGE2_DESC_COUNT
    $430A: C8        INY             
    $430B: D0 F7     BNE $4304       
    $430D: EE 06 43  INC $4306       
    $4310: EE 09 43  INC $4309       
    $4313: CA        DEX             
    $4314: D0 EE     BNE $4304       
    $4316: A9 00     LDA #$00        
    $4318: 85 02     STA $02          ; CASINI
    $431A: 85 0C     STA $0c          ; DOSINI
    $431C: A9 00     LDA #$00        
    $431E: 85 03     STA $03          ; CASINI+1
    $4320: 85 0D     STA $0d          ; DOSINI+1
    $4322: 20 06 07  JSR $0706        ; STAGE2_UNPACK_ENTRY
    $4325: 20 80 18  JSR $1880       
    $4328: 6C 0A 00  JMP ($000a)      ; DOSVEC

; Stage 2 Header ($0700..$0705): descriptor count = $11 (17 descriptors)
STAGE2_DESC_COUNT:
    $0700: 11 31 00 07 80 18  ; .byte $11, $31, $00, $07, $80, $18
STAGE2_UNPACK_ENTRY:
    $0706: A2 FF     LDX #$ff        
    $0708: A9 FF     LDA #$ff        
    $070A: 8D E2 02  STA $02e2        ; INITAD
    $070D: A9 06     LDA #$06        
    $070F: 8D E3 02  STA $02e3        ; INITAD+1
    $0712: A9 60     LDA #$60        
    $0714: 8D FF 06  STA $06ff        ; STUB_RTS_OR_IO_STATUS
    $0717: A9 9F     LDA #$9f        
    $0719: 85 80     STA $80          ; ZP_DESC_PTR
    $071B: A9 07     LDA #$07        
    $071D: 85 81     STA $81          ; ZP_DESC_PTR+1
    $071F: E8        INX             
    $0720: EC 00 07  CPX $0700        ; STAGE2_DESC_COUNT
    $0723: D0 1B     BNE $0740       
    $0725: A9 00     LDA #$00        
    $0727: 8D 44 02  STA $0244        ; COLDST
    $072A: A9 03     LDA #$03        
    $072C: 85 09     STA $09          ; BOOT?
    $072E: A9 FF     LDA #$ff        
    $0730: 85 02     STA $02          ; CASINI
    $0732: 85 0C     STA $0c          ; DOSINI
    $0734: A9 06     LDA #$06        
    $0736: 85 03     STA $03          ; CASINI+1
    $0738: 85 0D     STA $0d          ; DOSINI+1
    $073A: 20 00 B8  JSR $b800        ; TITLE_INIT_SUB
    $073D: 4C 40 25  JMP $2540        ; APP_MAIN_ENTRY
    $0740: A0 00     LDY #$00        
    $0742: B1 80     LDA ($80),Y      ; ZP_DESC_PTR
    $0744: 99 82 00  STA $0082,Y      ; ZP_COPY_LEN
    $0747: C8        INY             
    $0748: C0 06     CPY #$06        
    $074A: 90 F6     BCC $0742       
    $074C: A0 00     LDY #$00        
    $074E: B1 86     LDA ($86),Y      ; ZP_SRC_PTR
    $0750: 91 84     STA ($84),Y      ; ZP_DST_PTR
    $0752: A9 00     LDA #$00        
    $0754: 91 86     STA ($86),Y      ; ZP_SRC_PTR
    $0756: A5 86     LDA $86          ; ZP_SRC_PTR
    $0758: 38        SEC             
    $0759: E9 01     SBC #$01        
    $075B: 85 86     STA $86          ; ZP_SRC_PTR
    $075D: A5 87     LDA $87          ; ZP_SRC_PTR+1
    $075F: E9 00     SBC #$00        
    $0761: 85 87     STA $87          ; ZP_SRC_PTR+1
    $0763: A5 84     LDA $84          ; ZP_DST_PTR
    $0765: 38        SEC             
    $0766: E9 01     SBC #$01        
    $0768: 85 84     STA $84          ; ZP_DST_PTR
    $076A: A5 85     LDA $85          ; ZP_DST_PTR+1
    $076C: E9 00     SBC #$00        
    $076E: 85 85     STA $85          ; ZP_DST_PTR+1
    $0770: A5 82     LDA $82          ; ZP_COPY_LEN
    $0772: 38        SEC             
    $0773: E9 01     SBC #$01        
    $0775: 85 82     STA $82          ; ZP_COPY_LEN
    $0777: A5 83     LDA $83          ; ZP_COPY_LEN+1
    $0779: E9 00     SBC #$00        
    $077B: 85 83     STA $83          ; ZP_COPY_LEN+1
    $077D: A5 82     LDA $82          ; ZP_COPY_LEN
    $077F: C9 00     CMP #$00        
    $0781: D0 C9     BNE $074c       
    $0783: A5 83     LDA $83          ; ZP_COPY_LEN+1
    $0785: C9 00     CMP #$00        
    $0787: D0 C3     BNE $074c       
    $0789: A5 80     LDA $80          ; ZP_DESC_PTR
    $078B: 18        CLC             
    $078C: 69 06     ADC #$06        
    $078E: 85 80     STA $80          ; ZP_DESC_PTR
    $0790: A5 81     LDA $81          ; ZP_DESC_PTR+1
    $0792: 69 00     ADC #$00        
    $0794: 85 81     STA $81          ; ZP_DESC_PTR+1
    $0796: 4C 1F 07  JMP $071f       

; Stage 2 Block-Copy Descriptor Table ($079F..$0804, 17 x 6-byte entries: len, dst_end, src_end)
    $0799: 31 17 31 24 36 1F  ; pre-table metadata
STAGE2_DESC_TABLE:
    $079F: 02 00 E1 02 34 1F  ; Desc  0: len=$0002, dst=$02E0..$02E1, src=$1F33..$1F34
    $07A5: 02 00 E3 02 36 1F  ; Desc  1: len=$0002, dst=$02E2..$02E3, src=$1F35..$1F36
    $07AB: F0 03 EF BB 32 1F  ; Desc  2: len=$03F0, dst=$B800..$BBEF, src=$1B43..$1F32
    $07B1: 31 13 3B 33 35 1B  ; Desc  3: len=$1331, dst=$200B..$333B, src=$0805..$1B35
    $07B7: 01 00 20 20 36 1B  ; Desc  4: len=$0001, dst=$2020..$2020, src=$1B36..$1B36
    $07BD: 01 00 20 20 37 1B  ; Desc  5: len=$0001, dst=$2020..$2020, src=$1B37..$1B37
    $07C3: 01 00 20 20 38 1B  ; Desc  6: len=$0001, dst=$2020..$2020, src=$1B38..$1B38
    $07C9: 01 00 20 20 39 1B  ; Desc  7: len=$0001, dst=$2020..$2020, src=$1B39..$1B39
    $07CF: 01 00 20 20 3A 1B  ; Desc  8: len=$0001, dst=$2020..$2020, src=$1B3A..$1B3A
    $07D5: 01 00 20 20 3B 1B  ; Desc  9: len=$0001, dst=$2020..$2020, src=$1B3B..$1B3B
    $07DB: 01 00 20 20 3C 1B  ; Desc 10: len=$0001, dst=$2020..$2020, src=$1B3C..$1B3C
    $07E1: 01 00 20 20 3D 1B  ; Desc 11: len=$0001, dst=$2020..$2020, src=$1B3D..$1B3D
    $07E7: 01 00 20 20 3E 1B  ; Desc 12: len=$0001, dst=$2020..$2020, src=$1B3E..$1B3E
    $07ED: 01 00 20 20 3F 1B  ; Desc 13: len=$0001, dst=$2020..$2020, src=$1B3F..$1B3F
    $07F3: 01 00 20 20 40 1B  ; Desc 14: len=$0001, dst=$2020..$2020, src=$1B40..$1B40
    $07F9: 01 00 20 20 41 1B  ; Desc 15: len=$0001, dst=$2020..$2020, src=$1B41..$1B41
    $07FF: 01 00 20 20 42 1B  ; Desc 16: len=$0001, dst=$2020..$2020, src=$1B42..$1B42

; ==========================================================================
; TITLE SCREEN INITIALIZATION & DISPLAY LIST ($B800..$B82F)
; Sets SDLSTL/H ($0230/$0231) to $B810, COLOR2 ($02C6) to $90.
; ==========================================================================
TITLE_INIT_SUB:
    $B800: A9 10     LDA #$10        
    $B802: 8D 30 02  STA $0230        ; SDLSTL
    $B805: A9 B8     LDA #$b8        
    $B807: 8D 31 02  STA $0231        ; SDLSTH
    $B80A: A9 90     LDA #$90        
    $B80C: 8D C6 02  STA $02c6        ; COLOR2
    $B80F: 60        RTS             
TITLE_DLIST:
    $B810: 70 70 70 42 30 B8 02 02 02 02 02 02 02 02 02 02 02 02 02 02 02 02 02 02 02 02 02 02 02 41 10 B8  ; ANTIC Mode 2 Display List for $B830..$BBEF

; ==========================================================================
; MAIN UI DISPLAY LIST ($24F2..$253F)
; 24 x Mode 2 lines with individual LMS pointers ($42 lo hi), JVB $24F2
; ==========================================================================
MAIN_DLIST:
    $24F2: 70 70 70 42 0B 20 42 33 20 42 5B 20 42 83 20 42
    $2502: AB 20 42 D3 20 42 FB 20 42 23 21 42 4B 21 42 73
    $2512: 21 42 9B 21 42 C3 21 42 EB 21 42 13 22 42 3B 22
    $2522: 42 63 22 42 8B 22 42 B3 22 42 DB 22 42 CB 23 42
    $2532: 2B 23 42 53 23 42 7B 23 42 A3 23 41 F2 24

; ==========================================================================
; MAIN APPLICATION ENTRY & INITIALIZATION ($2540..$2570)
; Calls SIOINV ($E465), resets POKEY (AUDCTL=$00, SKCTL=$03), sets colors,
; points SDLSTL/H to $24F2, initializes Tempo ($2002=$07), Snare Tone
; ($2005=$16), Snare Pitch ($2006=$01), and enters Record Mode ($25D8).
; ==========================================================================
APP_MAIN_ENTRY:
    $2540: 20 65 E4  JSR $e465        ; SIOINV
    $2543: A9 00     LDA #$00        
    $2545: 8D 08 D2  STA $d208        ; AUDCTL
    $2548: A9 03     LDA #$03        
    $254A: 8D 0F D2  STA $d20f        ; SKCTL
    $254D: A9 00     LDA #$00        
    $254F: 8D C8 02  STA $02c8        ; COLOR4
    $2552: 8D C6 02  STA $02c6        ; COLOR2
    $2555: A9 24     LDA #$24        
    $2557: 8D 31 02  STA $0231        ; SDLSTH
    $255A: A9 F2     LDA #$f2        
    $255C: 8D 30 02  STA $0230        ; SDLSTL
    $255F: A9 07     LDA #$07        
    $2561: 8D 02 20  STA $2002        ; TEMPO_DELAY_HI
    $2564: A9 16     LDA #$16        
    $2566: 8D 05 20  STA $2005        ; SNARE_TONE_BASE
    $2569: A9 01     LDA #$01        
    $256B: 8D 06 20  STA $2006        ; SNARE_PITCH_AUDF1
    $256E: 4C D8 25  JMP $25d8        ; ENTER_RECORD_MODE

; ==========================================================================
; INSTRUMENT 3: SNARE ($2571..$25D7) - Key '3' (CH=$1A)
; Channels: CH1 (17-bit poly noise, pitch=$2006) + CH2 (pure tone sweep from $2005+2)
; AUDCTL=$01 (15 kHz base clock). Preceded by 24-cycle DAC pop ($1F/$1B).
; ==========================================================================
TRIG_SNARE:
    $2571: A9 54     LDA #$54        
    $2573: 8D 86 20  STA $2086        ; SCR_IND_SNARE
    $2576: A9 01     LDA #$01        
    $2578: 8D 08 D2  STA $d208        ; AUDCTL
    $257B: A9 1F     LDA #$1f        
    $257D: 8D 03 D2  STA $d203        ; AUDC2
    $2580: A9 1B     LDA #$1b        
    $2582: 8D 01 D2  STA $d201        ; AUDC1
    $2585: AD 06 20  LDA $2006        ; SNARE_PITCH_AUDF1
    $2588: 8D 00 D2  STA $d200        ; AUDF1
    $258B: A9 00     LDA #$00        
    $258D: 8D 03 D2  STA $d203        ; AUDC2
    $2590: A9 08     LDA #$08        
    $2592: 8D 00 20  STA $2000        ; ENV_STEP_CNT
    $2595: AD 05 20  LDA $2005        ; SNARE_TONE_BASE
    $2598: 8D 01 20  STA $2001        ; SWEEP_AUDF_ACC
    $259B: 18        CLC             
    $259C: A9 80     LDA #$80        
    $259E: 6D 00 20  ADC $2000        ; ENV_STEP_CNT
    $25A1: 8D 01 D2  STA $d201        ; AUDC1
    $25A4: AD 06 20  LDA $2006        ; SNARE_PITCH_AUDF1
    $25A7: 8D 00 D2  STA $d200        ; AUDF1
    $25AA: 18        CLC             
    $25AB: AD 01 20  LDA $2001        ; SWEEP_AUDF_ACC
    $25AE: 69 02     ADC #$02        
    $25B0: 8D 01 20  STA $2001        ; SWEEP_AUDF_ACC
    $25B3: 8D 02 D2  STA $d202        ; AUDF2
    $25B6: 18        CLC             
    $25B7: A9 A1     LDA #$a1        
    $25B9: 6D 00 20  ADC $2000        ; ENV_STEP_CNT
    $25BC: 8D 03 D2  STA $d203        ; AUDC2
    $25BF: 20 1E 27  JSR $271e        ; DELAY_TEMPO_STEP
    $25C2: CE 00 20  DEC $2000        ; ENV_STEP_CNT
    $25C5: AD 00 20  LDA $2000        ; ENV_STEP_CNT
    $25C8: C9 FF     CMP #$ff        
    $25CA: D0 CF     BNE $259b       
    $25CC: A9 00     LDA #$00        
    $25CE: 8D 01 D2  STA $d201        ; AUDC1
    $25D1: 8D 03 D2  STA $d203        ; AUDC2
    $25D4: 8D 86 20  STA $2086        ; SCR_IND_SNARE
    $25D7: 60        RTS             

; ==========================================================================
; RECORD MODE ENTRY & KEYBOARD DISPATCH LOOP ($25D8..$26CD)
; Polls OS keyboard shadow CH ($02FC) and dispatches instrument triggers,
; ESC to Play Mode ($1C), ^L Load Pattern ($80), or D Demo Mode ($3A).
; ==========================================================================
ENTER_RECORD_MODE:
    $25D8: A9 CB     LDA #$cb        
    $25DA: 8D 2F 25  STA $252f        ; DLIST_LMS_MODE_LO
    $25DD: A9 23     LDA #$23        
    $25DF: 8D 30 25  STA $2530        ; DLIST_LMS_MODE_HI
    $25E2: A9 00     LDA #$00        
    $25E4: 8D 09 20  STA $2009        ; HAS_RECORDED_FLAG
    $25E7: 8D 0A 20  STA $200a        ; DEMO_MODE_FLAG
    $25EA: 20 67 2B  JSR $2b67        ; RESET_STEP_COUNTER_UI
    $25ED: 20 01 2A  JSR $2a01        ; RESET_PAT_PTR
RECORD_KEY_LOOP:
    $25F0: A9 FF     LDA #$ff        
    $25F2: 8D FC 02  STA $02fc        ; CH
    $25F5: AD FC 02  LDA $02fc        ; CH
    $25F8: C9 FF     CMP #$ff        
    $25FA: F0 F9     BEQ $25f5       
    $25FC: C9 21     CMP #$21        
    $25FE: D0 0C     BNE $260c       
    $2600: 20 18 2A  JSR $2a18        ; RECORD_STORE_EVENT
    $2603: 20 79 2B  JSR $2b79        ; INC_STEP_COUNTER_UI
    $2606: 20 2E 27  JSR $272e        ; TRIG_BASS_DRUM
    $2609: 4C F0 25  JMP $25f0        ; RECORD_KEY_LOOP
    $260C: C9 1F     CMP #$1f        
    $260E: D0 0C     BNE $261c       
    $2610: 20 18 2A  JSR $2a18        ; RECORD_STORE_EVENT
    $2613: 20 79 2B  JSR $2b79        ; INC_STEP_COUNTER_UI
    $2616: 20 CE 26  JSR $26ce        ; TRIG_HH_CLOSED
    $2619: 4C F0 25  JMP $25f0        ; RECORD_KEY_LOOP
    $261C: C9 1A     CMP #$1a        
    $261E: D0 0C     BNE $262c       
    $2620: 20 18 2A  JSR $2a18        ; RECORD_STORE_EVENT
    $2623: 20 79 2B  JSR $2b79        ; INC_STEP_COUNTER_UI
    $2626: 20 71 25  JSR $2571        ; TRIG_SNARE
    $2629: 4C F0 25  JMP $25f0        ; RECORD_KEY_LOOP
    $262C: C9 1E     CMP #$1e        
    $262E: D0 0C     BNE $263c       
    $2630: 20 18 2A  JSR $2a18        ; RECORD_STORE_EVENT
    $2633: 20 79 2B  JSR $2b79        ; INC_STEP_COUNTER_UI
    $2636: 20 98 27  JSR $2798        ; TRIG_HH_ACCENT
    $2639: 4C F0 25  JMP $25f0        ; RECORD_KEY_LOOP
    $263C: C9 35     CMP #$35        
    $263E: D0 0C     BNE $264c       
    $2640: 20 18 2A  JSR $2a18        ; RECORD_STORE_EVENT
    $2643: 20 79 2B  JSR $2b79        ; INC_STEP_COUNTER_UI
    $2646: 20 F3 27  JSR $27f3        ; TRIG_CLAPS
    $2649: 4C F0 25  JMP $25f0        ; RECORD_KEY_LOOP
    $264C: C9 1C     CMP #$1c        
    $264E: D0 03     BNE $2653       
    $2650: 4C 30 2A  JMP $2a30        ; HANDLE_ESC_TO_PLAY
    $2653: C9 07     CMP #$07        
    $2655: D0 0C     BNE $2663       
    $2657: 20 18 2A  JSR $2a18        ; RECORD_STORE_EVENT
    $265A: 20 79 2B  JSR $2b79        ; INC_STEP_COUNTER_UI
    $265D: 20 95 28  JSR $2895        ; TRIG_SKIP_A_BEAT
    $2660: 4C F0 25  JMP $25f0        ; RECORD_KEY_LOOP
    $2663: C9 18     CMP #$18        
    $2665: D0 0C     BNE $2673       
    $2667: 20 18 2A  JSR $2a18        ; RECORD_STORE_EVENT
    $266A: 20 79 2B  JSR $2b79        ; INC_STEP_COUNTER_UI
    $266D: 20 D2 28  JSR $28d2        ; TRIG_TOM_1
    $2670: 4C F0 25  JMP $25f0        ; RECORD_KEY_LOOP
    $2673: C9 1D     CMP #$1d        
    $2675: D0 0C     BNE $2683       
    $2677: 20 18 2A  JSR $2a18        ; RECORD_STORE_EVENT
    $267A: 20 79 2B  JSR $2b79        ; INC_STEP_COUNTER_UI
    $267D: 20 37 29  JSR $2937        ; TRIG_TOM_2
    $2680: 4C F0 25  JMP $25f0        ; RECORD_KEY_LOOP
    $2683: C9 1B     CMP #$1b        
    $2685: D0 0C     BNE $2693       
    $2687: 20 18 2A  JSR $2a18        ; RECORD_STORE_EVENT
    $268A: 20 79 2B  JSR $2b79        ; INC_STEP_COUNTER_UI
    $268D: 20 9C 29  JSR $299c        ; TRIG_TOM_3
    $2690: 4C F0 25  JMP $25f0        ; RECORD_KEY_LOOP
    $2693: C9 33     CMP #$33        
    $2695: D0 0C     BNE $26a3       
    $2697: 20 18 2A  JSR $2a18        ; RECORD_STORE_EVENT
    $269A: 20 79 2B  JSR $2b79        ; INC_STEP_COUNTER_UI
    $269D: 20 44 28  JSR $2844        ; TRIG_WOOD_BLOCK
    $26A0: 4C F0 25  JMP $25f0        ; RECORD_KEY_LOOP
    $26A3: C9 80     CMP #$80        
    $26A5: D0 03     BNE $26aa       
    $26A7: 4C CA 2D  JMP $2dca        ; LOAD_PATTERN_CMD
    $26AA: C9 3A     CMP #$3a        
    $26AC: D0 1D     BNE $26cb       
    $26AE: A9 01     LDA #$01        
    $26B0: 8D 0A 20  STA $200a        ; DEMO_MODE_FLAG
    $26B3: 20 01 2A  JSR $2a01        ; RESET_PAT_PTR
    $26B6: A9 08     LDA #$08        
    $26B8: 8D 02 20  STA $2002        ; TEMPO_DELAY_HI
    $26BB: A9 01     LDA #$01        
    $26BD: 8D 06 20  STA $2006        ; SNARE_PITCH_AUDF1
    $26C0: A9 18     LDA #$18        
    $26C2: 8D 05 20  STA $2005        ; SNARE_TONE_BASE
    $26C5: 20 67 2B  JSR $2b67        ; RESET_STEP_COUNTER_UI
    $26C8: 4C 3F 2A  JMP $2a3f        ; ENTER_PLAY_MODE
    $26CB: 4C F0 25  JMP $25f0        ; RECORD_KEY_LOOP

; ==========================================================================
; INSTRUMENT 1: HH CLOSED ($26CE..$271D) - Key '1' (CH=$1F)
; Channels: CH1 (17-bit poly noise, AUDF1=$00, vol 4->2) + CH2 (pure tone AUDF2=$08, AUDC2=$A1)
; AUDCTL=$00 (64 kHz base clock). Active 3 steps ($2000=8..6), silent 6 steps ($2000=5..0).
; ==========================================================================
TRIG_HH_CLOSED:
    $26CE: A9 54     LDA #$54        
    $26D0: 8D 36 20  STA $2036        ; SCR_IND_HH_CLOSED
    $26D3: A9 08     LDA #$08        
    $26D5: 8D 00 20  STA $2000        ; ENV_STEP_CNT
    $26D8: A9 00     LDA #$00        
    $26DA: 8D 08 D2  STA $d208        ; AUDCTL
    $26DD: A9 00     LDA #$00        
    $26DF: 8D 01 20  STA $2001        ; SWEEP_AUDF_ACC
    $26E2: 18        CLC             
    $26E3: AD 00 20  LDA $2000        ; ENV_STEP_CNT
    $26E6: C9 06     CMP #$06        
    $26E8: 10 0E     BPL $26f8       
    $26EA: A9 00     LDA #$00        
    $26EC: 8D 01 D2  STA $d201        ; AUDC1
    $26EF: 8D 03 D2  STA $d203        ; AUDC2
    $26F2: 8D 36 20  STA $2036        ; SCR_IND_HH_CLOSED
    $26F5: 4C 10 27  JMP $2710       
    $26F8: A9 00     LDA #$00        
    $26FA: 8D 00 D2  STA $d200        ; AUDF1
    $26FD: 18        CLC             
    $26FE: A9 7C     LDA #$7c        
    $2700: 6D 00 20  ADC $2000        ; ENV_STEP_CNT
    $2703: 8D 01 D2  STA $d201        ; AUDC1
    $2706: A9 A1     LDA #$a1        
    $2708: 8D 03 D2  STA $d203        ; AUDC2
    $270B: A9 08     LDA #$08        
    $270D: 8D 02 D2  STA $d202        ; AUDF2
    $2710: 20 1E 27  JSR $271e        ; DELAY_TEMPO_STEP
    $2713: CE 00 20  DEC $2000        ; ENV_STEP_CNT
    $2716: AD 00 20  LDA $2000        ; ENV_STEP_CNT
    $2719: C9 FF     CMP #$ff        
    $271B: D0 C5     BNE $26e2       
    $271D: 60        RTS             

; ==========================================================================
; SHARED SUB-FRAME TEMPO DELAY LOOP ($271E..$272D)
; Busy-waits 256 * $2002 inner Y-loops: Cycles = 11 + 1805 * $2002.
; At default Record tempo ($2002=$07): 12,646 cycles (~7.131 ms PAL).
; ==========================================================================
DELAY_TEMPO_STEP:
    $271E: A2 00     LDX #$00        
    $2720: A0 00     LDY #$00        
    $2722: C8        INY             
    $2723: C0 00     CPY #$00        
    $2725: D0 FB     BNE $2722       
    $2727: E8        INX             
    $2728: EC 02 20  CPX $2002        ; TEMPO_DELAY_HI
    $272B: D0 F5     BNE $2722       
    $272D: 60        RTS             

; ==========================================================================
; INSTRUMENT 4: BASS DRUM ($272E..$2797) - Key 'SPACE' (CH=$21)
; Channels: CH1 (noise AUDF1=$02, AUDC1=$85) + CH2 (pure tone AUDF2=$5C->$6E, AUDC2=$AC)
; AUDCTL=$01 (15 kHz base clock). Preceded by 22-cycle DAC pop ($1F/$1B). Active 2 steps.
; ==========================================================================
TRIG_BASS_DRUM:
    $272E: A9 54     LDA #$54        
    $2730: 8D AE 20  STA $20ae        ; SCR_IND_BASS_DRUM
    $2733: A9 01     LDA #$01        
    $2735: 8D 08 D2  STA $d208        ; AUDCTL
    $2738: A9 1F     LDA #$1f        
    $273A: 8D 03 D2  STA $d203        ; AUDC2
    $273D: A9 1B     LDA #$1b        
    $273F: 8D 01 D2  STA $d201        ; AUDC1
    $2742: A9 02     LDA #$02        
    $2744: 8D 00 D2  STA $d200        ; AUDF1
    $2747: A9 00     LDA #$00        
    $2749: 8D 03 D2  STA $d203        ; AUDC2
    $274C: A9 08     LDA #$08        
    $274E: 8D 00 20  STA $2000        ; ENV_STEP_CNT
    $2751: A9 4A     LDA #$4a        
    $2753: 8D 01 20  STA $2001        ; SWEEP_AUDF_ACC
    $2756: 18        CLC             
    $2757: AD 00 20  LDA $2000        ; ENV_STEP_CNT
    $275A: C9 07     CMP #$07        
    $275C: 10 0E     BPL $276c       
    $275E: A9 00     LDA #$00        
    $2760: 8D 01 D2  STA $d201        ; AUDC1
    $2763: 8D 03 D2  STA $d203        ; AUDC2
    $2766: 8D AE 20  STA $20ae        ; SCR_IND_BASS_DRUM
    $2769: 4C 82 27  JMP $2782       
    $276C: A9 85     LDA #$85        
    $276E: 8D 01 D2  STA $d201        ; AUDC1
    $2771: 18        CLC             
    $2772: AD 01 20  LDA $2001        ; SWEEP_AUDF_ACC
    $2775: 69 12     ADC #$12        
    $2777: 8D 01 20  STA $2001        ; SWEEP_AUDF_ACC
    $277A: 8D 02 D2  STA $d202        ; AUDF2
    $277D: A9 AC     LDA #$ac        
    $277F: 8D 03 D2  STA $d203        ; AUDC2
    $2782: 20 1E 27  JSR $271e        ; DELAY_TEMPO_STEP
    $2785: CE 00 20  DEC $2000        ; ENV_STEP_CNT
    $2788: AD 00 20  LDA $2000        ; ENV_STEP_CNT
    $278B: C9 FF     CMP #$ff        
    $278D: D0 C7     BNE $2756       
    $278F: A9 00     LDA #$00        
    $2791: 8D 01 D2  STA $d201        ; AUDC1
    $2794: 8D 03 D2  STA $d203        ; AUDC2
    $2797: 60        RTS             

; ==========================================================================
; INSTRUMENT 2: HH ACCENT ($2798..$27F2) - Key '2' (CH=$1E)
; Channels: CH1 (17-bit poly noise, AUDF1=$00, vol 8->1) + CH2 (pure tone AUDF2=$08, AUDC2=$A1)
; AUDCTL=$00 (64 kHz base clock). Active 8 steps ($2000=8..1), silent 1 step ($2000=0).
; ==========================================================================
TRIG_HH_ACCENT:
    $2798: A9 54     LDA #$54        
    $279A: 8D 5E 20  STA $205e        ; SCR_IND_HH_ACCENT
    $279D: A9 08     LDA #$08        
    $279F: 8D 00 20  STA $2000        ; ENV_STEP_CNT
    $27A2: A9 00     LDA #$00        
    $27A4: 8D 08 D2  STA $d208        ; AUDCTL
    $27A7: A9 00     LDA #$00        
    $27A9: 8D 01 20  STA $2001        ; SWEEP_AUDF_ACC
    $27AC: 18        CLC             
    $27AD: AD 00 20  LDA $2000        ; ENV_STEP_CNT
    $27B0: C9 01     CMP #$01        
    $27B2: 10 0E     BPL $27c2       
    $27B4: A9 00     LDA #$00        
    $27B6: 8D 01 D2  STA $d201        ; AUDC1
    $27B9: 8D 03 D2  STA $d203        ; AUDC2
    $27BC: 8D 5E 20  STA $205e        ; SCR_IND_HH_ACCENT
    $27BF: 4C DA 27  JMP $27da       
    $27C2: A9 00     LDA #$00        
    $27C4: 8D 00 D2  STA $d200        ; AUDF1
    $27C7: 18        CLC             
    $27C8: A9 80     LDA #$80        
    $27CA: 6D 00 20  ADC $2000        ; ENV_STEP_CNT
    $27CD: 8D 01 D2  STA $d201        ; AUDC1
    $27D0: A9 A1     LDA #$a1        
    $27D2: 8D 03 D2  STA $d203        ; AUDC2
    $27D5: A9 08     LDA #$08        
    $27D7: 8D 02 D2  STA $d202        ; AUDF2
    $27DA: 20 1E 27  JSR $271e        ; DELAY_TEMPO_STEP
    $27DD: CE 00 20  DEC $2000        ; ENV_STEP_CNT
    $27E0: AD 00 20  LDA $2000        ; ENV_STEP_CNT
    $27E3: C9 FF     CMP #$ff        
    $27E5: D0 C5     BNE $27ac       
    $27E7: A9 00     LDA #$00        
    $27E9: 8D 01 D2  STA $d201        ; AUDC1
    $27EC: 8D 03 D2  STA $d203        ; AUDC2
    $27EF: 8D 5E 20  STA $205e        ; SCR_IND_HH_ACCENT
    $27F2: 60        RTS             

; ==========================================================================
; INSTRUMENT 9: CLAPS ($27F3..$2843) - Key '8' (CH=$35)
; Channels: CH1 (17-bit poly noise, AUDF1=$12, vol 8->1). AUDCTL=$00 (64 kHz).
; BUG at $2821: STA $D5EB writes to cartridge space $D5EB instead of $D203 (AUDC2),
; leaving CH2 silent even though AUDF2=$1E is written at $282B.
; ==========================================================================
TRIG_CLAPS:
    $27F3: A9 54     LDA #$54        
    $27F5: 8D 76 21  STA $2176        ; SCR_IND_CLAPS
    $27F8: A9 00     LDA #$00        
    $27FA: 8D 08 D2  STA $d208        ; AUDCTL
    $27FD: A9 08     LDA #$08        
    $27FF: 8D 00 20  STA $2000        ; ENV_STEP_CNT
    $2802: 18        CLC             
    $2803: AD 00 20  LDA $2000        ; ENV_STEP_CNT
    $2806: C9 01     CMP #$01        
    $2808: 10 0E     BPL $2818       
    $280A: A9 00     LDA #$00        
    $280C: 8D 01 D2  STA $d201        ; AUDC1
    $280F: 8D 03 D2  STA $d203        ; AUDC2
    $2812: 8D 76 21  STA $2176        ; SCR_IND_CLAPS
    $2815: 4C 2E 28  JMP $282e       
    $2818: 18        CLC             
    $2819: A9 80     LDA #$80        
    $281B: 6D 00 20  ADC $2000        ; ENV_STEP_CNT
    $281E: 8D 01 D2  STA $d201        ; AUDC1
    $2821: 8D EB D5  STA $d5eb        ; BUG_CORRUPTED_AUDC2_D5EB
    $2824: A9 12     LDA #$12        
    $2826: 8D 00 D2  STA $d200        ; AUDF1
    $2829: A9 1E     LDA #$1e        
    $282B: 8D 02 D2  STA $d202        ; AUDF2
    $282E: 20 1E 27  JSR $271e        ; DELAY_TEMPO_STEP
    $2831: CE 00 20  DEC $2000        ; ENV_STEP_CNT
    $2834: AD 00 20  LDA $2000        ; ENV_STEP_CNT
    $2837: C9 FF     CMP #$ff        
    $2839: D0 C7     BNE $2802       
    $283B: A9 00     LDA #$00        
    $283D: 8D 01 D2  STA $d201        ; AUDC1
    $2840: 8D 03 D2  STA $d203        ; AUDC2
    $2843: 60        RTS             

; ==========================================================================
; INSTRUMENT 8: WOOD BLOCK ($2844..$2894) - Key '7' (CH=$33)
; Channels: CH1 (AUDF1=$07) + CH2 (AUDF2=$14), both driven with 17-bit poly noise
; AUDC1=AUDC2=$85->$84->$83 under AUDCTL=$00 (64 kHz). Active 3 steps, silent 6 steps.
; ==========================================================================
TRIG_WOOD_BLOCK:
    $2844: A9 54     LDA #$54        
    $2846: 8D 4E 21  STA $214e        ; SCR_IND_WOOD_BLOCK
    $2849: A9 00     LDA #$00        
    $284B: 8D 08 D2  STA $d208        ; AUDCTL
    $284E: A9 08     LDA #$08        
    $2850: 8D 00 20  STA $2000        ; ENV_STEP_CNT
    $2853: 18        CLC             
    $2854: AD 00 20  LDA $2000        ; ENV_STEP_CNT
    $2857: C9 06     CMP #$06        
    $2859: 10 0E     BPL $2869       
    $285B: A9 00     LDA #$00        
    $285D: 8D 01 D2  STA $d201        ; AUDC1
    $2860: 8D 03 D2  STA $d203        ; AUDC2
    $2863: 8D 4E 21  STA $214e        ; SCR_IND_WOOD_BLOCK
    $2866: 4C 7F 28  JMP $287f       
    $2869: 18        CLC             
    $286A: A9 7D     LDA #$7d        
    $286C: 6D 00 20  ADC $2000        ; ENV_STEP_CNT
    $286F: 8D 01 D2  STA $d201        ; AUDC1
    $2872: 8D 03 D2  STA $d203        ; AUDC2
    $2875: A9 07     LDA #$07        
    $2877: 8D 00 D2  STA $d200        ; AUDF1
    $287A: A9 14     LDA #$14        
    $287C: 8D 02 D2  STA $d202        ; AUDF2
    $287F: 20 1E 27  JSR $271e        ; DELAY_TEMPO_STEP
    $2882: CE 00 20  DEC $2000        ; ENV_STEP_CNT
    $2885: AD 00 20  LDA $2000        ; ENV_STEP_CNT
    $2888: C9 FF     CMP #$ff        
    $288A: D0 C7     BNE $2853       
    $288C: A9 00     LDA #$00        
    $288E: 8D 01 D2  STA $d201        ; AUDC1
    $2891: 8D 03 D2  STA $d203        ; AUDC2
    $2894: 60        RTS             

; ==========================================================================
; REST / SILENCE PSEUDO-INSTRUMENT: SKIP A BEAT ($2895..$28D1) - Key '*' (CH=$07)
; Mutes AUDC1=$00, AUDC2=$00, AUDCTL=$00 across all 9 delay steps.
; ==========================================================================
TRIG_SKIP_A_BEAT:
    $2895: A9 00     LDA #$00        
    $2897: 8D 01 D2  STA $d201        ; AUDC1
    $289A: 8D 03 D2  STA $d203        ; AUDC2
    $289D: A9 08     LDA #$08        
    $289F: 8D 00 20  STA $2000        ; ENV_STEP_CNT
    $28A2: 18        CLC             
    $28A3: AD 00 20  LDA $2000        ; ENV_STEP_CNT
    $28A6: C9 06     CMP #$06        
    $28A8: 10 0B     BPL $28b5       
    $28AA: A9 00     LDA #$00        
    $28AC: 8D 01 D2  STA $d201        ; AUDC1
    $28AF: 8D 03 D2  STA $d203        ; AUDC2
    $28B2: 4C C4 28  JMP $28c4       
    $28B5: A9 00     LDA #$00        
    $28B7: 8D 01 D2  STA $d201        ; AUDC1
    $28BA: 18        CLC             
    $28BB: 8D 01 D2  STA $d201        ; AUDC1
    $28BE: 8D 03 D2  STA $d203        ; AUDC2
    $28C1: 8D 08 D2  STA $d208        ; AUDCTL
    $28C4: 20 1E 27  JSR $271e        ; DELAY_TEMPO_STEP
    $28C7: CE 00 20  DEC $2000        ; ENV_STEP_CNT
    $28CA: AD 00 20  LDA $2000        ; ENV_STEP_CNT
    $28CD: C9 FF     CMP #$ff        
    $28CF: D0 D1     BNE $28a2       
    $28D1: 60        RTS             

; ==========================================================================
; INSTRUMENT 5: TOM 1 ($28D2..$2936) - Key '4' (CH=$18)
; High Tom. AUDCTL=$01 (15 kHz). 14-cycle CH2 DAC pop ($1F), then 5 active steps ($2000=8..4):
; CH1 noise AUDF1=$01 (vol 7->3), CH2 pure tone sweep AUDF2=$23..$33 (+4/step, vol 11->7).
; ==========================================================================
TRIG_TOM_1:
    $28D2: A9 54     LDA #$54        
    $28D4: 8D D6 20  STA $20d6        ; SCR_IND_TOM_1
    $28D7: A9 01     LDA #$01        
    $28D9: 8D 08 D2  STA $d208        ; AUDCTL
    $28DC: A9 1F     LDA #$1f        
    $28DE: 8D 03 D2  STA $d203        ; AUDC2
    $28E1: A9 01     LDA #$01        
    $28E3: 8D 00 D2  STA $d200        ; AUDF1
    $28E6: A9 00     LDA #$00        
    $28E8: 8D 03 D2  STA $d203        ; AUDC2
    $28EB: A9 08     LDA #$08        
    $28ED: 8D 00 20  STA $2000        ; ENV_STEP_CNT
    $28F0: A9 1F     LDA #$1f        
    $28F2: 8D 01 20  STA $2001        ; SWEEP_AUDF_ACC
    $28F5: 18        CLC             
    $28F6: AD 00 20  LDA $2000        ; ENV_STEP_CNT
    $28F9: C9 04     CMP #$04        
    $28FB: 10 0E     BPL $290b       
    $28FD: A9 00     LDA #$00        
    $28FF: 8D 01 D2  STA $d201        ; AUDC1
    $2902: 8D 03 D2  STA $d203        ; AUDC2
    $2905: 8D D6 20  STA $20d6        ; SCR_IND_TOM_1
    $2908: 4C 29 29  JMP $2929       
    $290B: 18        CLC             
    $290C: A9 7F     LDA #$7f        
    $290E: 6D 00 20  ADC $2000        ; ENV_STEP_CNT
    $2911: 8D 01 D2  STA $d201        ; AUDC1
    $2914: 18        CLC             
    $2915: AD 01 20  LDA $2001        ; SWEEP_AUDF_ACC
    $2918: 69 04     ADC #$04        
    $291A: 8D 01 20  STA $2001        ; SWEEP_AUDF_ACC
    $291D: 8D 02 D2  STA $d202        ; AUDF2
    $2920: 18        CLC             
    $2921: A9 A3     LDA #$a3        
    $2923: 6D 00 20  ADC $2000        ; ENV_STEP_CNT
    $2926: 8D 03 D2  STA $d203        ; AUDC2
    $2929: 20 1E 27  JSR $271e        ; DELAY_TEMPO_STEP
    $292C: CE 00 20  DEC $2000        ; ENV_STEP_CNT
    $292F: AD 00 20  LDA $2000        ; ENV_STEP_CNT
    $2932: C9 FF     CMP #$ff        
    $2934: D0 BF     BNE $28f5       
    $2936: 60        RTS             

; ==========================================================================
; INSTRUMENT 6: TOM 2 ($2937..$299B) - Key '5' (CH=$1D)
; Mid Tom. AUDCTL=$01 (15 kHz). 14-cycle CH2 DAC pop ($1F), then 6 active steps ($2000=8..3):
; CH1 noise AUDF1=$01 (vol 7->2), CH2 pure tone sweep AUDF2=$32..$46 (+4/step, vol 11->6).
; ==========================================================================
TRIG_TOM_2:
    $2937: A9 54     LDA #$54        
    $2939: 8D FE 20  STA $20fe        ; SCR_IND_TOM_2
    $293C: A9 01     LDA #$01        
    $293E: 8D 08 D2  STA $d208        ; AUDCTL
    $2941: A9 1F     LDA #$1f        
    $2943: 8D 03 D2  STA $d203        ; AUDC2
    $2946: A9 01     LDA #$01        
    $2948: 8D 00 D2  STA $d200        ; AUDF1
    $294B: A9 00     LDA #$00        
    $294D: 8D 03 D2  STA $d203        ; AUDC2
    $2950: A9 08     LDA #$08        
    $2952: 8D 00 20  STA $2000        ; ENV_STEP_CNT
    $2955: A9 2E     LDA #$2e        
    $2957: 8D 01 20  STA $2001        ; SWEEP_AUDF_ACC
    $295A: 18        CLC             
    $295B: AD 00 20  LDA $2000        ; ENV_STEP_CNT
    $295E: C9 03     CMP #$03        
    $2960: 10 0E     BPL $2970       
    $2962: A9 00     LDA #$00        
    $2964: 8D 01 D2  STA $d201        ; AUDC1
    $2967: 8D 03 D2  STA $d203        ; AUDC2
    $296A: 8D FE 20  STA $20fe        ; SCR_IND_TOM_2
    $296D: 4C 8E 29  JMP $298e       
    $2970: 18        CLC             
    $2971: A9 7F     LDA #$7f        
    $2973: 6D 00 20  ADC $2000        ; ENV_STEP_CNT
    $2976: 8D 01 D2  STA $d201        ; AUDC1
    $2979: 18        CLC             
    $297A: AD 01 20  LDA $2001        ; SWEEP_AUDF_ACC
    $297D: 69 04     ADC #$04        
    $297F: 8D 01 20  STA $2001        ; SWEEP_AUDF_ACC
    $2982: 8D 02 D2  STA $d202        ; AUDF2
    $2985: 18        CLC             
    $2986: A9 A3     LDA #$a3        
    $2988: 6D 00 20  ADC $2000        ; ENV_STEP_CNT
    $298B: 8D 03 D2  STA $d203        ; AUDC2
    $298E: 20 1E 27  JSR $271e        ; DELAY_TEMPO_STEP
    $2991: CE 00 20  DEC $2000        ; ENV_STEP_CNT
    $2994: AD 00 20  LDA $2000        ; ENV_STEP_CNT
    $2997: C9 FF     CMP #$ff        
    $2999: D0 BF     BNE $295a       
    $299B: 60        RTS             

; ==========================================================================
; INSTRUMENT 7: TOM 3 ($299C..$2A00) - Key '6' (CH=$1B)
; Low Tom. AUDCTL=$01 (15 kHz). 14-cycle CH2 DAC pop ($1F), then 7 active steps ($2000=8..2):
; CH1 noise AUDF1=$01 (vol 7->1), CH2 pure tone sweep AUDF2=$3C..$54 (+4/step, vol 11->5).
; ==========================================================================
TRIG_TOM_3:
    $299C: A9 54     LDA #$54        
    $299E: 8D 26 21  STA $2126        ; SCR_IND_TOM_3
    $29A1: A9 01     LDA #$01        
    $29A3: 8D 08 D2  STA $d208        ; AUDCTL
    $29A6: A9 1F     LDA #$1f        
    $29A8: 8D 03 D2  STA $d203        ; AUDC2
    $29AB: A9 01     LDA #$01        
    $29AD: 8D 00 D2  STA $d200        ; AUDF1
    $29B0: A9 00     LDA #$00        
    $29B2: 8D 03 D2  STA $d203        ; AUDC2
    $29B5: A9 08     LDA #$08        
    $29B7: 8D 00 20  STA $2000        ; ENV_STEP_CNT
    $29BA: A9 38     LDA #$38        
    $29BC: 8D 01 20  STA $2001        ; SWEEP_AUDF_ACC
    $29BF: 18        CLC             
    $29C0: AD 00 20  LDA $2000        ; ENV_STEP_CNT
    $29C3: C9 02     CMP #$02        
    $29C5: 10 0E     BPL $29d5       
    $29C7: A9 00     LDA #$00        
    $29C9: 8D 01 D2  STA $d201        ; AUDC1
    $29CC: 8D 03 D2  STA $d203        ; AUDC2
    $29CF: 8D 26 21  STA $2126        ; SCR_IND_TOM_3
    $29D2: 4C F3 29  JMP $29f3       
    $29D5: 18        CLC             
    $29D6: A9 7F     LDA #$7f        
    $29D8: 6D 00 20  ADC $2000        ; ENV_STEP_CNT
    $29DB: 8D 01 D2  STA $d201        ; AUDC1
    $29DE: 18        CLC             
    $29DF: AD 01 20  LDA $2001        ; SWEEP_AUDF_ACC
    $29E2: 69 04     ADC #$04        
    $29E4: 8D 01 20  STA $2001        ; SWEEP_AUDF_ACC
    $29E7: 8D 02 D2  STA $d202        ; AUDF2
    $29EA: 18        CLC             
    $29EB: A9 A3     LDA #$a3        
    $29ED: 6D 00 20  ADC $2000        ; ENV_STEP_CNT
    $29F0: 8D 03 D2  STA $d203        ; AUDC2
    $29F3: 20 1E 27  JSR $271e        ; DELAY_TEMPO_STEP
    $29F6: CE 00 20  DEC $2000        ; ENV_STEP_CNT
    $29F9: AD 00 20  LDA $2000        ; ENV_STEP_CNT
    $29FC: C9 FF     CMP #$ff        
    $29FE: D0 BF     BNE $29bf       
    $2A00: 60        RTS             

; ==========================================================================
; PATTERN POINTER & SEQUENCER PLAYBACK ENGINE ($2A01..$2B66)
; Manages pattern pointer ($CC/$CD: $2E5D for Demo, $333C for User Record/Play),
; event recording ($2A18), Play Mode step dispatch ($2A58), real-time Tempo/Snare
; tuning hotkeys, Pause ('S', $2B55), and ^S Save Pattern ($2B2D -> $2CD1).
; ==========================================================================
RESET_PAT_PTR:
    $2A01: AD 0A 20  LDA $200a        ; DEMO_MODE_FLAG
    $2A04: F0 09     BEQ $2a0f       
    $2A06: A9 5D     LDA #$5d        
    $2A08: 85 CC     STA $cc          ; ZP_PAT_PTR
    $2A0A: A9 2E     LDA #$2e        
    $2A0C: 85 CD     STA $cd          ; ZP_PAT_PTR+1
    $2A0E: 60        RTS             
    $2A0F: A9 3C     LDA #$3c        
    $2A11: 85 CC     STA $cc          ; ZP_PAT_PTR
    $2A13: A9 33     LDA #$33        
    $2A15: 85 CD     STA $cd          ; ZP_PAT_PTR+1
    $2A17: 60        RTS             
RECORD_STORE_EVENT:
    $2A18: 8D 03 20  STA $2003        ; LAST_REC_KEY
    $2A1B: A0 00     LDY #$00        
    $2A1D: 91 CC     STA ($cc),Y      ; ZP_PAT_PTR
    $2A1F: 18        CLC             
    $2A20: A5 CC     LDA $cc          ; ZP_PAT_PTR
    $2A22: 69 01     ADC #$01        
    $2A24: 85 CC     STA $cc          ; ZP_PAT_PTR
    $2A26: 90 02     BCC $2a2a       
    $2A28: E6 CD     INC $cd          ; ZP_PAT_PTR+1
    $2A2A: A9 01     LDA #$01        
    $2A2C: 8D 09 20  STA $2009        ; HAS_RECORDED_FLAG
    $2A2F: 60        RTS             
HANDLE_ESC_TO_PLAY:
    $2A30: AD 09 20  LDA $2009        ; HAS_RECORDED_FLAG
    $2A33: C9 01     CMP #$01        
    $2A35: F0 03     BEQ $2a3a       
    $2A37: 4C D8 25  JMP $25d8        ; ENTER_RECORD_MODE
    $2A3A: A9 64     LDA #$64        
    $2A3C: 20 18 2A  JSR $2a18        ; RECORD_STORE_EVENT
ENTER_PLAY_MODE:
    $2A3F: 20 01 2A  JSR $2a01        ; RESET_PAT_PTR
    $2A42: 20 67 2B  JSR $2b67        ; RESET_STEP_COUNTER_UI
    $2A45: A9 23     LDA #$23        
    $2A47: 8D 30 25  STA $2530        ; DLIST_LMS_MODE_HI
    $2A4A: A9 F3     LDA #$f3        
    $2A4C: 8D 2F 25  STA $252f        ; DLIST_LMS_MODE_LO
    $2A4F: A0 00     LDY #$00        
    $2A51: A2 00     LDX #$00        
    $2A53: A9 FF     LDA #$ff        
    $2A55: 8D FC 02  STA $02fc        ; CH
PLAY_STEP_LOOP:
    $2A58: A0 00     LDY #$00        
    $2A5A: B1 CC     LDA ($cc),Y      ; ZP_PAT_PTR
    $2A5C: C9 21     CMP #$21        
    $2A5E: D0 06     BNE $2a66       
    $2A60: 20 2E 27  JSR $272e        ; TRIG_BASS_DRUM
    $2A63: 4C C9 2A  JMP $2ac9       
    $2A66: C9 1F     CMP #$1f        
    $2A68: D0 06     BNE $2a70       
    $2A6A: 20 CE 26  JSR $26ce        ; TRIG_HH_CLOSED
    $2A6D: 4C C9 2A  JMP $2ac9       
    $2A70: C9 1A     CMP #$1a        
    $2A72: D0 06     BNE $2a7a       
    $2A74: 20 71 25  JSR $2571        ; TRIG_SNARE
    $2A77: 4C C9 2A  JMP $2ac9       
    $2A7A: C9 1E     CMP #$1e        
    $2A7C: D0 06     BNE $2a84       
    $2A7E: 20 98 27  JSR $2798        ; TRIG_HH_ACCENT
    $2A81: 4C C9 2A  JMP $2ac9       
    $2A84: C9 35     CMP #$35        
    $2A86: D0 06     BNE $2a8e       
    $2A88: 20 F3 27  JSR $27f3        ; TRIG_CLAPS
    $2A8B: 4C C9 2A  JMP $2ac9       
    $2A8E: C9 07     CMP #$07        
    $2A90: D0 06     BNE $2a98       
    $2A92: 20 95 28  JSR $2895        ; TRIG_SKIP_A_BEAT
    $2A95: 4C C9 2A  JMP $2ac9       
    $2A98: C9 18     CMP #$18        
    $2A9A: D0 06     BNE $2aa2       
    $2A9C: 20 D2 28  JSR $28d2        ; TRIG_TOM_1
    $2A9F: 4C C9 2A  JMP $2ac9       
    $2AA2: C9 1D     CMP #$1d        
    $2AA4: D0 06     BNE $2aac       
    $2AA6: 20 37 29  JSR $2937        ; TRIG_TOM_2
    $2AA9: 4C C9 2A  JMP $2ac9       
    $2AAC: C9 1B     CMP #$1b        
    $2AAE: D0 06     BNE $2ab6       
    $2AB0: 20 9C 29  JSR $299c        ; TRIG_TOM_3
    $2AB3: 4C C9 2A  JMP $2ac9       
    $2AB6: C9 33     CMP #$33        
    $2AB8: D0 06     BNE $2ac0       
    $2ABA: 20 44 28  JSR $2844        ; TRIG_WOOD_BLOCK
    $2ABD: 4C C9 2A  JMP $2ac9       
    $2AC0: 20 01 2A  JSR $2a01        ; RESET_PAT_PTR
    $2AC3: 20 67 2B  JSR $2b67        ; RESET_STEP_COUNTER_UI
    $2AC6: 4C 58 2A  JMP $2a58        ; PLAY_STEP_LOOP
    $2AC9: 20 79 2B  JSR $2b79        ; INC_STEP_COUNTER_UI
    $2ACC: 18        CLC             
    $2ACD: A5 CC     LDA $cc          ; ZP_PAT_PTR
    $2ACF: 69 01     ADC #$01        
    $2AD1: 85 CC     STA $cc          ; ZP_PAT_PTR
    $2AD3: 90 02     BCC $2ad7       
    $2AD5: E6 CD     INC $cd          ; ZP_PAT_PTR+1
    $2AD7: A9 00     LDA #$00        
    $2AD9: 85 4D     STA $4d          ; ATRACT
    $2ADB: AD FC 02  LDA $02fc        ; CH
    $2ADE: C9 FF     CMP #$ff        
    $2AE0: D0 03     BNE $2ae5       
    $2AE2: 4C 58 2A  JMP $2a58        ; PLAY_STEP_LOOP
    $2AE5: C9 1C     CMP #$1c        
    $2AE7: D0 03     BNE $2aec       
    $2AE9: 4C D8 25  JMP $25d8        ; ENTER_RECORD_MODE
    $2AEC: C9 06     CMP #$06        
    $2AEE: D0 0B     BNE $2afb       
    $2AF0: CE 02 20  DEC $2002        ; TEMPO_DELAY_HI
    $2AF3: A9 FF     LDA #$ff        
    $2AF5: 8D FC 02  STA $02fc        ; CH
    $2AF8: 4C 58 2A  JMP $2a58        ; PLAY_STEP_LOOP
    $2AFB: C9 07     CMP #$07        
    $2AFD: D0 0B     BNE $2b0a       
    $2AFF: EE 02 20  INC $2002        ; TEMPO_DELAY_HI
    $2B02: A9 FF     LDA #$ff        
    $2B04: 8D FC 02  STA $02fc        ; CH
    $2B07: 4C 58 2A  JMP $2a58        ; PLAY_STEP_LOOP
    $2B0A: C9 3E     CMP #$3e        
    $2B0C: D0 0B     BNE $2b19       
    $2B0E: 20 01 2A  JSR $2a01        ; RESET_PAT_PTR
    $2B11: A9 FF     LDA #$ff        
    $2B13: 8D FC 02  STA $02fc        ; CH
    $2B16: 4C 55 2B  JMP $2b55        ; PLAY_PAUSE_LOOP
    $2B19: C9 0E     CMP #$0e        
    $2B1B: D0 06     BNE $2b23       
    $2B1D: 20 94 2B  JSR $2b94        ; DEC_SNARE_TONE
    $2B20: 4C 58 2A  JMP $2a58        ; PLAY_STEP_LOOP
    $2B23: C9 0F     CMP #$0f        
    $2B25: D0 06     BNE $2b2d       
    $2B27: 20 A5 2B  JSR $2ba5        ; INC_SNARE_TONE
    $2B2A: 4C 58 2A  JMP $2a58        ; PLAY_STEP_LOOP
    $2B2D: C9 BE     CMP #$be        
    $2B2F: D0 03     BNE $2b34       
    $2B31: 4C D1 2C  JMP $2cd1        ; SAVE_PATTERN_CMD
    $2B34: C9 8E     CMP #$8e        
    $2B36: D0 0B     BNE $2b43       
    $2B38: 20 47 2E  JSR $2e47        ; DEC_SNARE_PITCH
    $2B3B: A9 FF     LDA #$ff        
    $2B3D: 8D FC 02  STA $02fc        ; CH
    $2B40: 4C 58 2A  JMP $2a58        ; PLAY_STEP_LOOP
    $2B43: C9 8F     CMP #$8f        
    $2B45: D0 0B     BNE $2b52       
    $2B47: 20 52 2E  JSR $2e52        ; INC_SNARE_PITCH
    $2B4A: A9 FF     LDA #$ff        
    $2B4C: 8D FC 02  STA $02fc        ; CH
    $2B4F: 4C 58 2A  JMP $2a58        ; PLAY_STEP_LOOP
    $2B52: 4C 58 2A  JMP $2a58        ; PLAY_STEP_LOOP
PLAY_PAUSE_LOOP:
    $2B55: AD FC 02  LDA $02fc        ; CH
    $2B58: C9 3E     CMP #$3e        
    $2B5A: D0 F9     BNE $2b55       
    $2B5C: A9 FF     LDA #$ff        
    $2B5E: 8D FC 02  STA $02fc        ; CH
    $2B61: 20 67 2B  JSR $2b67        ; RESET_STEP_COUNTER_UI
    $2B64: 4C 58 2A  JMP $2a58        ; PLAY_STEP_LOOP

; ==========================================================================
; UI STEP COUNTER & SNARE TONE TUNING HELPERS ($2B67..$2BB5)
; Updates 5-digit screen-code step counter at $22EB..$22EF and adjusts $2005.
; ==========================================================================
RESET_STEP_COUNTER_UI:
    $2B67: A9 90     LDA #$90        
    $2B69: 8D EB 22  STA $22eb        ; SCR_STEP_DIGIT_0
    $2B6C: 8D EC 22  STA $22ec        ; SCR_STEP_DIGIT_1
    $2B6F: 8D ED 22  STA $22ed        ; SCR_STEP_DIGIT_2
    $2B72: 8D EE 22  STA $22ee        ; SCR_STEP_DIGIT_3
    $2B75: 8D EF 22  STA $22ef        ; SCR_STEP_DIGIT_4
    $2B78: 60        RTS             
INC_STEP_COUNTER_UI:
    $2B79: A2 05     LDX #$05        
    $2B7B: 18        CLC             
    $2B7C: BD EA 22  LDA $22ea,X     
    $2B7F: 69 01     ADC #$01        
    $2B81: C9 9A     CMP #$9a        
    $2B83: D0 0B     BNE $2b90       
    $2B85: A9 90     LDA #$90        
    $2B87: 9D EA 22  STA $22ea,X     
    $2B8A: CA        DEX             
    $2B8B: E0 00     CPX #$00        
    $2B8D: D0 EC     BNE $2b7b       
    $2B8F: 60        RTS             
    $2B90: 9D EA 22  STA $22ea,X     
    $2B93: 60        RTS             
DEC_SNARE_TONE:
    $2B94: A9 FF     LDA #$ff        
    $2B96: 8D FC 02  STA $02fc        ; CH
    $2B99: AD 05 20  LDA $2005        ; SNARE_TONE_BASE
    $2B9C: C9 01     CMP #$01        
    $2B9E: D0 01     BNE $2ba1       
    $2BA0: 60        RTS             
    $2BA1: CE 05 20  DEC $2005        ; SNARE_TONE_BASE
    $2BA4: 60        RTS             
INC_SNARE_TONE:
    $2BA5: A9 FF     LDA #$ff        
    $2BA7: 8D FC 02  STA $02fc        ; CH
    $2BAA: AD 05 20  LDA $2005        ; SNARE_TONE_BASE
    $2BAD: C9 FF     CMP #$ff        
    $2BAF: D0 01     BNE $2bb2       
    $2BB1: 60        RTS             
    $2BB2: EE 05 20  INC $2005        ; SNARE_TONE_BASE
    $2BB5: 60        RTS             

; ==========================================================================
; CIO DISK & KEYBOARD I/O ROUTINES ($2BB6..$2E46)
; Handles loading/saving 'D:xxxxxxxx.DRM' pattern files via CIOV ($E456).
; File header stores 3 parameters ($2002 Tempo, $2006 Snare Pitch, $2005 Snare Tone)
; followed by pattern event bytes terminated by $64.
; ==========================================================================
CIO_OPEN_READ_DRM:
    $2BB6: A2 10     LDX #$10        
    $2BB8: A9 04     LDA #$04        
    $2BBA: 9D 4A 03  STA $034a,X      ; ICAX1
    $2BBD: A2 10     LDX #$10        
    $2BBF: A9 03     LDA #$03        
    $2BC1: 9D 42 03  STA $0342,X      ; ICCOM
    $2BC4: A9 24     LDA #$24        
    $2BC6: 9D 45 03  STA $0345,X      ; ICBAH
    $2BC9: A9 BB     LDA #$bb        
    $2BCB: 9D 44 03  STA $0344,X      ; ICBAL
    $2BCE: 20 56 E4  JSR $e456        ; CIOV
    $2BD1: 60        RTS             
CIO_OPEN_WRITE_DRM:
    $2BD2: A2 10     LDX #$10        
    $2BD4: A9 08     LDA #$08        
    $2BD6: 9D 4A 03  STA $034a,X      ; ICAX1
    $2BD9: 4C BD 2B  JMP $2bbd       
CIO_CLOSE_CH1:
    $2BDC: A2 10     LDX #$10        
    $2BDE: A9 0C     LDA #$0c        
    $2BE0: 9D 42 03  STA $0342,X      ; ICCOM
    $2BE3: 20 56 E4  JSR $e456        ; CIOV
    $2BE6: 60        RTS             
CIO_PUT_BYTE_CH1:
    $2BE7: A2 10     LDX #$10        
    $2BE9: A9 0B     LDA #$0b        
    $2BEB: 9D 42 03  STA $0342,X      ; ICCOM
    $2BEE: A2 10     LDX #$10        
    $2BF0: A5 CC     LDA $cc          ; ZP_PAT_PTR
    $2BF2: 9D 44 03  STA $0344,X      ; ICBAL
    $2BF5: A5 CD     LDA $cd          ; ZP_PAT_PTR+1
    $2BF7: 9D 45 03  STA $0345,X      ; ICBAH
    $2BFA: A9 01     LDA #$01        
    $2BFC: 9D 48 03  STA $0348,X      ; ICBLL
    $2BFF: A9 00     LDA #$00        
    $2C01: 9D 49 03  STA $0349,X      ; ICBLH
    $2C04: 20 56 E4  JSR $e456        ; CIOV
    $2C07: 60        RTS             
CIO_GET_BYTE_CH1:
    $2C08: A2 10     LDX #$10        
    $2C0A: A9 07     LDA #$07        
    $2C0C: 9D 42 03  STA $0342,X      ; ICCOM
    $2C0F: 4C EE 2B  JMP $2bee       
DEV_K_STR:
    $2C12: 4B        ???             
    $2C13: 3A        ???             
    $2C14: 9B        ???             
CIO_OPEN_KEYBOARD:
    $2C15: A2 10     LDX #$10        
    $2C17: A9 03     LDA #$03        
    $2C19: 9D 42 03  STA $0342,X      ; ICCOM
    $2C1C: A9 2C     LDA #$2c        
    $2C1E: 9D 45 03  STA $0345,X      ; ICBAH
    $2C21: A9 12     LDA #$12        
    $2C23: 9D 44 03  STA $0344,X      ; ICBAL
    $2C26: A9 04     LDA #$04        
    $2C28: 9D 4A 03  STA $034a,X      ; ICAX1
    $2C2B: 20 56 E4  JSR $e456        ; CIOV
    $2C2E: 60        RTS             
CIO_GET_KEY_CHAR:
    $2C2F: A2 10     LDX #$10        
    $2C31: A9 07     LDA #$07        
    $2C33: 9D 42 03  STA $0342,X      ; ICCOM
    $2C36: A9 04     LDA #$04        
    $2C38: 9D 44 03  STA $0344,X      ; ICBAL
    $2C3B: A9 20     LDA #$20        
    $2C3D: 9D 45 03  STA $0345,X      ; ICBAH
    $2C40: A9 01     LDA #$01        
    $2C42: 9D 48 03  STA $0348,X      ; ICBLL
    $2C45: A9 00     LDA #$00        
    $2C47: 9D 49 03  STA $0349,X      ; ICBLH
    $2C4A: 20 56 E4  JSR $e456        ; CIOV
    $2C4D: 60        RTS             
PROMPT_FILENAME:
    $2C4E: A9 FF     LDA #$ff        
    $2C50: 8D FC 02  STA $02fc        ; CH
    $2C53: 20 BB 2D  JSR $2dbb        ; DELAY_65536_LOOPS
    $2C56: 20 BB 2D  JSR $2dbb        ; DELAY_65536_LOOPS
    $2C59: 20 BB 2D  JSR $2dbb        ; DELAY_65536_LOOPS
    $2C5C: 20 BB 2D  JSR $2dbb        ; DELAY_65536_LOOPS
    $2C5F: A9 00     LDA #$00        
    $2C61: 8D 07 20  STA $2007        ; FNAME_CHAR_IDX
    $2C64: A9 20     LDA #$20        
    $2C66: 8D BD 24  STA $24bd        ; FNAME_CHARS_8
    $2C69: 8D BE 24  STA $24be       
    $2C6C: 8D BF 24  STA $24bf       
    $2C6F: 8D C0 24  STA $24c0       
    $2C72: 8D C1 24  STA $24c1       
    $2C75: 8D C2 24  STA $24c2       
    $2C78: 8D C3 24  STA $24c3       
    $2C7B: 8D C4 24  STA $24c4       
    $2C7E: 20 15 2C  JSR $2c15        ; CIO_OPEN_KEYBOARD
    $2C81: AC 07 20  LDY $2007        ; FNAME_CHAR_IDX
    $2C84: A9 4E     LDA #$4e        
    $2C86: 99 7E 23  STA $237e,Y      ; SCR_FNAME_FIELD
    $2C89: 20 2F 2C  JSR $2c2f        ; CIO_GET_KEY_CHAR
    $2C8C: 20 71 25  JSR $2571        ; TRIG_SNARE
    $2C8F: A9 FF     LDA #$ff        
    $2C91: 8D FC 02  STA $02fc        ; CH
    $2C94: AD 04 20  LDA $2004        ; CIO_CHAR_BUF
    $2C97: C9 9B     CMP #$9b        
    $2C99: D0 03     BNE $2c9e       
    $2C9B: 4C CD 2C  JMP $2ccd       
    $2C9E: 18        CLC             
    $2C9F: AD 04 20  LDA $2004        ; CIO_CHAR_BUF
    $2CA2: C9 20     CMP #$20        
    $2CA4: 10 03     BPL $2ca9       
    $2CA6: 4C 81 2C  JMP $2c81       
    $2CA9: 18        CLC             
    $2CAA: AD 04 20  LDA $2004        ; CIO_CHAR_BUF
    $2CAD: C9 5B     CMP #$5b        
    $2CAF: 30 03     BMI $2cb4       
    $2CB1: 4C 81 2C  JMP $2c81       
    $2CB4: AC 07 20  LDY $2007        ; FNAME_CHAR_IDX
    $2CB7: 38        SEC             
    $2CB8: AD 04 20  LDA $2004        ; CIO_CHAR_BUF
    $2CBB: 99 BD 24  STA $24bd,Y      ; FNAME_CHARS_8
    $2CBE: E9 20     SBC #$20        
    $2CC0: 99 7E 23  STA $237e,Y      ; SCR_FNAME_FIELD
    $2CC3: EE 07 20  INC $2007        ; FNAME_CHAR_IDX
    $2CC6: AD 07 20  LDA $2007        ; FNAME_CHAR_IDX
    $2CC9: C9 08     CMP #$08        
    $2CCB: D0 B4     BNE $2c81       
    $2CCD: 20 DC 2B  JSR $2bdc        ; CIO_CLOSE_CH1
    $2CD0: 60        RTS             
SAVE_PATTERN_CMD:
    $2CD1: A9 43     LDA #$43        
    $2CD3: 8D 35 25  STA $2535        ; DLIST_LMS_PROMPT_LO
    $2CD6: A9 24     LDA #$24        
    $2CD8: 8D 36 25  STA $2536        ; DLIST_LMS_PROMPT_HI
    $2CDB: 20 4E 2C  JSR $2c4e        ; PROMPT_FILENAME
    $2CDE: 20 D2 2B  JSR $2bd2        ; CIO_OPEN_WRITE_DRM
    $2CE1: AD 53 03  LDA $0353        ; ICSTA_CH1
    $2CE4: 8D FF 06  STA $06ff        ; STUB_RTS_OR_IO_STATUS
    $2CE7: C9 01     CMP #$01        
    $2CE9: F0 06     BEQ $2cf1       
    $2CEB: 20 6A 2D  JSR $2d6a        ; HANDLE_DISK_ERROR
    $2CEE: 4C 58 2A  JMP $2a58        ; PLAY_STEP_LOOP
    $2CF1: 20 01 2A  JSR $2a01        ; RESET_PAT_PTR
    $2CF4: A0 00     LDY #$00        
    $2CF6: B1 CC     LDA ($cc),Y      ; ZP_PAT_PTR
    $2CF8: 8D 00 06  STA $0600        ; TMP_FIRST_PAT_BYTE
    $2CFB: AD 02 20  LDA $2002        ; TEMPO_DELAY_HI
    $2CFE: 91 CC     STA ($cc),Y      ; ZP_PAT_PTR
    $2D00: 20 E7 2B  JSR $2be7        ; CIO_PUT_BYTE_CH1
    $2D03: A0 00     LDY #$00        
    $2D05: AD 06 20  LDA $2006        ; SNARE_PITCH_AUDF1
    $2D08: 91 CC     STA ($cc),Y      ; ZP_PAT_PTR
    $2D0A: 20 E7 2B  JSR $2be7        ; CIO_PUT_BYTE_CH1
    $2D0D: A0 00     LDY #$00        
    $2D0F: AD 05 20  LDA $2005        ; SNARE_TONE_BASE
    $2D12: 91 CC     STA ($cc),Y      ; ZP_PAT_PTR
    $2D14: 20 E7 2B  JSR $2be7        ; CIO_PUT_BYTE_CH1
    $2D17: A0 00     LDY #$00        
    $2D19: AD 00 06  LDA $0600        ; TMP_FIRST_PAT_BYTE
    $2D1C: 91 CC     STA ($cc),Y      ; ZP_PAT_PTR
    $2D1E: 20 E7 2B  JSR $2be7        ; CIO_PUT_BYTE_CH1
    $2D21: AD 53 03  LDA $0353        ; ICSTA_CH1
    $2D24: 8D FF 06  STA $06ff        ; STUB_RTS_OR_IO_STATUS
    $2D27: C9 01     CMP #$01        
    $2D29: F0 06     BEQ $2d31       
    $2D2B: 20 6A 2D  JSR $2d6a        ; HANDLE_DISK_ERROR
    $2D2E: 4C 58 2A  JMP $2a58        ; PLAY_STEP_LOOP
    $2D31: A0 00     LDY #$00        
    $2D33: B1 CC     LDA ($cc),Y      ; ZP_PAT_PTR
    $2D35: C9 64     CMP #$64        
    $2D37: D0 23     BNE $2d5c       
    $2D39: 20 DC 2B  JSR $2bdc        ; CIO_CLOSE_CH1
    $2D3C: 20 01 2A  JSR $2a01        ; RESET_PAT_PTR
    $2D3F: A9 CA     LDA #$ca        
    $2D41: 8D 35 25  STA $2535        ; DLIST_LMS_PROMPT_LO
    $2D44: A9 24     LDA #$24        
    $2D46: 8D 36 25  STA $2536        ; DLIST_LMS_PROMPT_HI
    $2D49: A0 00     LDY #$00        
    $2D4B: 98        TYA             
    $2D4C: 99 7E 23  STA $237e,Y      ; SCR_FNAME_FIELD
    $2D4F: C8        INY             
    $2D50: C0 09     CPY #$09        
    $2D52: D0 F8     BNE $2d4c       
    $2D54: A9 FF     LDA #$ff        
    $2D56: 8D FC 02  STA $02fc        ; CH
    $2D59: 4C 58 2A  JMP $2a58        ; PLAY_STEP_LOOP
    $2D5C: 18        CLC             
    $2D5D: A5 CC     LDA $cc          ; ZP_PAT_PTR
    $2D5F: 69 01     ADC #$01        
    $2D61: 85 CC     STA $cc          ; ZP_PAT_PTR
    $2D63: 90 02     BCC $2d67       
    $2D65: E6 CD     INC $cd          ; ZP_PAT_PTR+1
    $2D67: 4C 1E 2D  JMP $2d1e       
HANDLE_DISK_ERROR:
    $2D6A: 20 01 2A  JSR $2a01        ; RESET_PAT_PTR
    $2D6D: A0 00     LDY #$00        
    $2D6F: 98        TYA             
    $2D70: 99 7E 23  STA $237e,Y      ; SCR_FNAME_FIELD
    $2D73: C8        INY             
    $2D74: C0 09     CPY #$09        
    $2D76: D0 F8     BNE $2d70       
    $2D78: A9 FF     LDA #$ff        
    $2D7A: 8D FC 02  STA $02fc        ; CH
    $2D7D: AD FF 06  LDA $06ff        ; STUB_RTS_OR_IO_STATUS
    $2D80: C9 AA     CMP #$aa        
    $2D82: D0 0D     BNE $2d91       
    $2D84: A9 93     LDA #$93        
    $2D86: 8D 35 25  STA $2535        ; DLIST_LMS_PROMPT_LO
    $2D89: A9 24     LDA #$24        
    $2D8B: 8D 36 25  STA $2536        ; DLIST_LMS_PROMPT_HI
    $2D8E: 4C 9B 2D  JMP $2d9b       
    $2D91: A9 6B     LDA #$6b        
    $2D93: 8D 35 25  STA $2535        ; DLIST_LMS_PROMPT_LO
    $2D96: A9 24     LDA #$24        
    $2D98: 8D 36 25  STA $2536        ; DLIST_LMS_PROMPT_HI
    $2D9B: 20 BB 2D  JSR $2dbb        ; DELAY_65536_LOOPS
    $2D9E: 20 BB 2D  JSR $2dbb        ; DELAY_65536_LOOPS
    $2DA1: 20 BB 2D  JSR $2dbb        ; DELAY_65536_LOOPS
    $2DA4: 20 BB 2D  JSR $2dbb        ; DELAY_65536_LOOPS
    $2DA7: 20 BB 2D  JSR $2dbb        ; DELAY_65536_LOOPS
    $2DAA: 20 BB 2D  JSR $2dbb        ; DELAY_65536_LOOPS
    $2DAD: 20 DC 2B  JSR $2bdc        ; CIO_CLOSE_CH1
    $2DB0: A9 CA     LDA #$ca        
    $2DB2: 8D 35 25  STA $2535        ; DLIST_LMS_PROMPT_LO
    $2DB5: A9 24     LDA #$24        
    $2DB7: 8D 36 25  STA $2536        ; DLIST_LMS_PROMPT_HI
    $2DBA: 60        RTS             
DELAY_65536_LOOPS:
    $2DBB: A0 00     LDY #$00        
    $2DBD: A2 00     LDX #$00        
    $2DBF: E8        INX             
    $2DC0: E0 00     CPX #$00        
    $2DC2: D0 FB     BNE $2dbf       
    $2DC4: C8        INY             
    $2DC5: C0 00     CPY #$00        
    $2DC7: D0 F6     BNE $2dbf       
    $2DC9: 60        RTS             
LOAD_PATTERN_CMD:
    $2DCA: A9 1B     LDA #$1b        
    $2DCC: 8D 35 25  STA $2535        ; DLIST_LMS_PROMPT_LO
    $2DCF: A9 24     LDA #$24        
    $2DD1: 8D 36 25  STA $2536        ; DLIST_LMS_PROMPT_HI
    $2DD4: 20 4E 2C  JSR $2c4e        ; PROMPT_FILENAME
    $2DD7: 20 B6 2B  JSR $2bb6        ; CIO_OPEN_READ_DRM
    $2DDA: AD 53 03  LDA $0353        ; ICSTA_CH1
    $2DDD: 8D FF 06  STA $06ff        ; STUB_RTS_OR_IO_STATUS
    $2DE0: C9 01     CMP #$01        
    $2DE2: F0 06     BEQ $2dea       
    $2DE4: 20 6A 2D  JSR $2d6a        ; HANDLE_DISK_ERROR
    $2DE7: 4C D8 25  JMP $25d8        ; ENTER_RECORD_MODE
    $2DEA: 20 08 2C  JSR $2c08        ; CIO_GET_BYTE_CH1
    $2DED: A0 00     LDY #$00        
    $2DEF: B1 CC     LDA ($cc),Y      ; ZP_PAT_PTR
    $2DF1: 8D 02 20  STA $2002        ; TEMPO_DELAY_HI
    $2DF4: 20 08 2C  JSR $2c08        ; CIO_GET_BYTE_CH1
    $2DF7: A0 00     LDY #$00        
    $2DF9: B1 CC     LDA ($cc),Y      ; ZP_PAT_PTR
    $2DFB: 8D 06 20  STA $2006        ; SNARE_PITCH_AUDF1
    $2DFE: 20 08 2C  JSR $2c08        ; CIO_GET_BYTE_CH1
    $2E01: A0 00     LDY #$00        
    $2E03: B1 CC     LDA ($cc),Y      ; ZP_PAT_PTR
    $2E05: 8D 05 20  STA $2005        ; SNARE_TONE_BASE
    $2E08: 20 01 2A  JSR $2a01        ; RESET_PAT_PTR
    $2E0B: 20 08 2C  JSR $2c08        ; CIO_GET_BYTE_CH1
    $2E0E: A0 00     LDY #$00        
    $2E10: B1 CC     LDA ($cc),Y      ; ZP_PAT_PTR
    $2E12: C9 64     CMP #$64        
    $2E14: D0 23     BNE $2e39       
    $2E16: 20 DC 2B  JSR $2bdc        ; CIO_CLOSE_CH1
    $2E19: 20 01 2A  JSR $2a01        ; RESET_PAT_PTR
    $2E1C: A9 CA     LDA #$ca        
    $2E1E: 8D 35 25  STA $2535        ; DLIST_LMS_PROMPT_LO
    $2E21: A9 24     LDA #$24        
    $2E23: 8D 36 25  STA $2536        ; DLIST_LMS_PROMPT_HI
    $2E26: A0 00     LDY #$00        
    $2E28: 98        TYA             
    $2E29: 99 7E 23  STA $237e,Y      ; SCR_FNAME_FIELD
    $2E2C: C8        INY             
    $2E2D: C0 09     CPY #$09        
    $2E2F: D0 F8     BNE $2e29       
    $2E31: A9 FF     LDA #$ff        
    $2E33: 8D FC 02  STA $02fc        ; CH
    $2E36: 4C 3F 2A  JMP $2a3f        ; ENTER_PLAY_MODE
    $2E39: 18        CLC             
    $2E3A: A5 CC     LDA $cc          ; ZP_PAT_PTR
    $2E3C: 69 01     ADC #$01        
    $2E3E: 85 CC     STA $cc          ; ZP_PAT_PTR
    $2E40: 90 02     BCC $2e44       
    $2E42: E6 CD     INC $cd          ; ZP_PAT_PTR+1
    $2E44: 4C 0B 2E  JMP $2e0b       

; ==========================================================================
; SNARE PITCH TUNING HELPERS ($2E47..$2E5C)
; Adjusts $2006 (AUDF1 divider for Snare noise channel) via Ctrl+Up/Down.
; ==========================================================================
DEC_SNARE_PITCH:
    $2E47: AD 06 20  LDA $2006        ; SNARE_PITCH_AUDF1
    $2E4A: C9 00     CMP #$00        
    $2E4C: F0 03     BEQ $2e51       
    $2E4E: CE 06 20  DEC $2006        ; SNARE_PITCH_AUDF1
    $2E51: 60        RTS             
INC_SNARE_PITCH:
    $2E52: AD 06 20  LDA $2006        ; SNARE_PITCH_AUDF1
    $2E55: C9 FF     CMP #$ff        
    $2E57: F0 F8     BEQ $2e51       
    $2E59: EE 06 20  INC $2006        ; SNARE_PITCH_AUDF1
    $2E5C: 60        RTS             

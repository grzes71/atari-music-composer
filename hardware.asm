; =============================================================================
; Atari 8-bit Hardware Equates (POKEY, ANTIC, GTIA, PIA)
; Compatible with MADS Macro Assembler
; =============================================================================

; --- POKEY Registers ($D200 - $D20F) ---
AUDF1       equ $D200   ; Audio Channel 1 Frequency
AUDC1       equ $D201   ; Audio Channel 1 Control / Volume
AUDF2       equ $D202   ; Audio Channel 2 Frequency
AUDC2       equ $D203   ; Audio Channel 2 Control / Volume
AUDF3       equ $D204   ; Audio Channel 3 Frequency
AUDC3       equ $D205   ; Audio Channel 3 Control / Volume
AUDF4       equ $D206   ; Audio Channel 4 Frequency
AUDC4       equ $D207   ; Audio Channel 4 Control / Volume
AUDCTL      equ $D208   ; Audio Control
STIMER      equ $D209   ; Start Timers
SKRES       equ $D20A   ; Reset Serial Port Status
POTGO       equ $D20B   ; Start Potentiometer Scan
SERDAT      equ $D20D   ; Serial Port Data In/Out
SERCTL      equ $D20D   ; Serial Port Control
IRQEN       equ $D20E   ; IRQ Interrupt Enable
IRQST       equ $D20E   ; IRQ Interrupt Status
SKCTL       equ $D20F   ; Serial Port Control

; --- AUDCTL Bits ---
AUDCTL_15KHZ        equ $01  ; 15 kHz main clock instead of 64 kHz
AUDCTL_CH2_FILTER   equ $02  ; High-pass filter Ch 2 clocked by Ch 4
AUDCTL_CH1_FILTER   equ $04  ; High-pass filter Ch 1 clocked by Ch 3
AUDCTL_JOIN_3_4     equ $08  ; Join Ch 3 and 4 into 16-bit channel
AUDCTL_JOIN_1_2     equ $10  ; Join Ch 1 and 2 into 16-bit channel
AUDCTL_CH3_179MHZ   equ $20  ; Clock Ch 3 with 1.79 MHz
AUDCTL_CH1_179MHZ   equ $40  ; Clock Ch 1 with 1.79 MHz
AUDCTL_9BIT_POLY    equ $80  ; 9-bit poly instead of 17-bit poly

; --- AUDC Distortion Modes (Bits 7..5) ---
DIST_5BIT_POLY_1    equ $00  ; 5-bit poly noise / white noise
DIST_5BIT_POLY_2    equ $40  ; 5-bit poly noise
DIST_PURE_TONE      equ $A0  ; Pure sine/square tone
DIST_4BIT_POLY      equ $C0  ; 4-bit poly bass / buzzing tone
DIST_17BIT_POLY     equ $80  ; 17-bit poly noise

; --- ANTIC Registers ($D400 - $D40F) ---
DMACTL      equ $D400   ; Direct Memory Access Control
CHACTL      equ $D401   ; Character Control
DLISTL      equ $D402   ; Display List Pointer Low
DLISTH      equ $D403   ; Display List Pointer High
HSCROL      equ $D404   ; Horizontal Scroll
VSCROL      equ $D405   ; Vertical Scroll
PMBASE      equ $D407   ; Player-Missile Base Address
CHBASE      equ $D409   ; Character Set Base Address
WSYNC       equ $D40A   ; Wait for Horizontal Sync
VCOUNT      equ $D40B   ; Vertical Scanline Counter
NMIEN       equ $D40E   ; NMI Interrupt Enable
NMIST       equ $D40F   ; NMI Interrupt Status

; --- GTIA Registers ($D000 - $D01F) ---
HPOSP0      equ $D000   ; Player 0 Horizontal Position
HPOSP1      equ $D001   ; Player 1 Horizontal Position
HPOSP2      equ $D002   ; Player 2 Horizontal Position
HPOSP3      equ $D003   ; Player 3 Horizontal Position
COLPM0      equ $D012   ; Color Player/Missile 0
COLPM1      equ $D013   ; Color Player/Missile 1
COLPM2      equ $D014   ; Color Player/Missile 2
COLPM3      equ $D015   ; Color Player/Missile 3
COLPF0      equ $D016   ; Color Playfield 0
COLPF1      equ $D017   ; Color Playfield 1
COLPF2      equ $D018   ; Color Playfield 2
COLPF3      equ $D019   ; Color Playfield 3
COLBK       equ $D01A   ; Color Background
PRIOR       equ $D01B   ; Priority Selection
GRACTL      equ $D01D   ; Graphic Control
CONSOL      equ $D01F   ; Console Keys (Start, Select, Option)

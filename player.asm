; =============================================================================
; Relocatable 4-Channel POKEY Music Player for Atari 8-bit (MOS 6502)
; Compatible with MADS Macro Assembler
;
; Public API:
;   music_init        - X=song_lo, Y=song_hi: Initialize song & silence POKEY
;   music_play        - Start playback
;   music_stop        - Stop playback & silence POKEY
;   music_update      - Advance frame (call once per 50 Hz VBLANK)
;   music_is_playing  - Return A=1 if playing, A=0 if stopped
; =============================================================================

; --- Zero Page Configuration ---
    .ifndef PLAYER_ZP_BASE
PLAYER_ZP_BASE  = $80
    .endif

; --- Song Data Format ---
; The music data carries a version byte immediately before its instrument table.
; Version 1 (this player) writes 6-byte instrument records. Version 0 -- what every song
; exported before this existed is -- had no version byte and 5-byte records, and its first
; instrument byte was always a generator (a multiple of $20), so a version-0 song can never
; present $01 in that position and can never be mistaken for version 1.
SONG_FORMAT_VERSION = 1

; Modulation descriptors: instrument record byte 6
MOD_NONE            = 0     ; the channel holds one divider for the whole note
MOD_OCTAVE_PULSE    = 1     ; C1: N / N//2 alternating once per frame (see apply_modulation)

zp_ch1_ptr      = PLAYER_ZP_BASE + 0   ; 2 bytes: pointer to Ch 1 track data
zp_ch2_ptr      = PLAYER_ZP_BASE + 2   ; 2 bytes: pointer to Ch 2 track data
zp_ch3_ptr      = PLAYER_ZP_BASE + 4   ; 2 bytes: pointer to Ch 3 track data
zp_ch4_ptr      = PLAYER_ZP_BASE + 6   ; 2 bytes: pointer to Ch 4 track data
zp_tmp_ptr      = PLAYER_ZP_BASE + 8   ; 2 bytes: temporary pointer for headers/sequences

; --- Hardware Equates (if not included by caller) ---
AUDF1_REG       equ $D200
AUDC1_REG       equ $D201
AUDF2_REG       equ $D202
AUDC2_REG       equ $D203
AUDF3_REG       equ $D204
AUDC3_REG       equ $D205
AUDF4_REG       equ $D206
AUDC4_REG       equ $D207
AUDCTL_REG      equ $D208

; =============================================================================
; music_init
; Input: X = Song data address low byte
;        Y = Song data address high byte
; =============================================================================
.proc music_init
    stx song_ptr_lo
    sty song_ptr_hi
    stx zp_tmp_ptr
    sty zp_tmp_ptr + 1

    ; 1. Read Song Header
    ldy #0
    lda (zp_tmp_ptr),y          ; frames_per_tick
    sta tempo_divider
    sta tick_counter

    iny
    lda (zp_tmp_ptr),y          ; audctl_mode
    sta audctl_mode

    iny
    lda (zp_tmp_ptr),y          ; instruments_ptr low
    sta inst_ptr_lo
    iny
    lda (zp_tmp_ptr),y          ; instruments_ptr high
    sta inst_ptr_hi

    iny
    lda (zp_tmp_ptr),y          ; sequence_ptr low
    sta seq_ptr_lo
    iny
    lda (zp_tmp_ptr),y          ; sequence_ptr high
    sta seq_ptr_hi

    ; 2. Read the format version, then the Instruments Table (4 channels x 6 bytes)
    lda inst_ptr_lo
    sta zp_tmp_ptr
    lda inst_ptr_hi
    sta zp_tmp_ptr + 1

    ldy #0
    lda (zp_tmp_ptr),y          ; format version
    cmp #SONG_FORMAT_VERSION
    beq @format_ok

    ; The song data is a layout this player does not know. Reading it as version 1 would
    ; play a misread instrument table, so refuse: stay stopped, silence POKEY, and leave
    ; format_ok at 0 so a later music_play cannot override the refusal.
    lda #0
    sta format_ok
    sta music_playing
    jsr silence_pokey
    rts

@format_ok:
    lda #1
    sta format_ok
    iny                         ; Y = 1, the first instrument byte

    lda #0
    sta any_mod
    ldx #0
load_inst_loop:
    lda (zp_tmp_ptr),y          ; distortion
    sta ch_dist,x
    iny
    lda (zp_tmp_ptr),y          ; attack frames
    sta ch_att,x
    iny
    lda (zp_tmp_ptr),y          ; decay frames
    sta ch_dec,x
    iny
    lda (zp_tmp_ptr),y          ; sustain vol
    sta ch_sus,x
    iny
    lda (zp_tmp_ptr),y          ; release frames
    sta ch_rel,x
    iny
    lda (zp_tmp_ptr),y          ; modulation descriptor
    sta ch_mod,x
    ora any_mod                 ; one byte the frame loop tests instead of four
    sta any_mod
    lda #1
    sta ch_mod_phase,x          ; a note starts on its nominal divider
    iny
    inx
    cpx #4
    bne load_inst_loop

    ; 3. Reset Sequence and State
    lda #0
    sta seq_step_idx
    sta music_playing

    ; Force immediate note loading on all channels
    lda #0
    sta ch_dur + 0
    sta ch_dur + 1
    sta ch_dur + 2
    sta ch_dur + 3

    sta ch_env_phase + 0
    sta ch_env_phase + 1
    sta ch_env_phase + 2
    sta ch_env_phase + 3

    sta ch_cur_vol + 0
    sta ch_cur_vol + 1
    sta ch_cur_vol + 2
    sta ch_cur_vol + 3

    sta ch_sus_lvl + 0
    sta ch_sus_lvl + 1
    sta ch_sus_lvl + 2
    sta ch_sus_lvl + 3

    sta ch_mute_mask + 0
    sta ch_mute_mask + 1
    sta ch_mute_mask + 2
    sta ch_mute_mask + 3

    ; Load first pattern
    jsr load_pattern_ptrs

    ; 4. Silence POKEY
    jsr silence_pokey
    rts
.endp

; =============================================================================
; music_play
; Starts song playback
; =============================================================================
.proc music_play
    lda format_ok               ; refuse to start a song whose layout was not accepted
    beq @refused
    lda #1
    sta music_playing
    sta tick_counter            ; Trigger immediate row update on frame 1
@refused:
    rts
.endp

; =============================================================================
; music_stop
; Stops playback and silences all channels
; =============================================================================
.proc music_stop
    lda #0
    sta music_playing
    jsr silence_pokey
    rts
.endp

; =============================================================================
; music_is_playing
; Returns A = 1 if playing, A = 0 if stopped
; =============================================================================
.proc music_is_playing
    lda music_playing
    rts
.endp

; =============================================================================
; music_update
; Frame update routine. Call exactly once per 50 Hz VBLANK frame.
; =============================================================================
.proc music_update
    lda music_playing
    bne @do_update
    rts

@do_update:
    ; 1. Decrement tick counter
    dec tick_counter
    bne @skip_row_advance

    ; Row advanced: reload tick counter
    lda tempo_divider
    sta tick_counter

    ; Advance row on each channel (0..3)
    ldx #0
advance_channel_loop:
    lda ch_dur,x
    beq @load_next_note
    dec ch_dur,x
    bne @channel_row_done

@load_next_note:
    jsr fetch_channel_note

@channel_row_done:
    inx
    cpx #4
    bne advance_channel_loop

@skip_row_advance:
    ; 2. Update envelopes for all channels
    jsr update_envelopes

    ; 3. Per-frame divider modulation (one test when no channel asked for one)
    jsr apply_modulation

    ; 4. Output to POKEY registers
    jsr write_pokey_registers
    rts
.endp

; =============================================================================
; fetch_channel_note
; Fetches next 3-byte note event for channel X from zp_ch[x]_ptr
; If $FF encountered, advances sequence and reloads pattern pointers
; =============================================================================
.proc fetch_channel_note
    ; Set up zp_tmp_ptr pointing to zp_ch[x]_ptr
    txa
    asl                         ; X * 2
    tay
    lda zp_ch1_ptr,y
    sta zp_tmp_ptr
    lda zp_ch1_ptr + 1,y
    sta zp_tmp_ptr + 1

    ldy #0
    lda (zp_tmp_ptr),y          ; Read AUDF or $FF
    cmp #$FF
    bne @got_note

    ; End of track encountered!
    ; If channel 0 reached end, advance whole song sequence
    cpx #0
    bne @early_end_track

    ; Channel 0 reached end of track: Advance sequence step
    txa
    pha                         ; Preserve channel index X
    clc
    lda seq_step_idx
    adc #2
    sta seq_step_idx
    jsr load_pattern_ptrs
    pla
    tax                         ; Restore channel index X

@reload_track_ptr:
    ; Re-fetch pointer for this channel after sequence advance
    txa
    asl
    tay
    lda zp_ch1_ptr,y
    sta zp_tmp_ptr
    lda zp_ch1_ptr + 1,y
    sta zp_tmp_ptr + 1

    ldy #0
    lda (zp_tmp_ptr),y
    jmp @got_note

@early_end_track:
    ; Channel X reached $FF before sequence advance: hold silence until pattern ends
    lda #0
    sta ch_audf,x
    sta ch_audf_base,x
    sta ch_peak_vol,x
    sta ch_cur_vol,x
    sta ch_env_phase,x
    lda #1
    sta ch_dur,x
    rts

@got_note:
    sta ch_audf,x               ; Store AUDF
    sta ch_audf_base,x          ; and keep N: apply_modulation derives N//2 from it
    iny

    lda (zp_tmp_ptr),y          ; Read duration
    sta ch_dur,x
    iny

    lda (zp_tmp_ptr),y          ; Read volume
    sta ch_peak_vol,x
    iny

    ; Advance pointer past this 3-byte event
    tya
    clc
    adc zp_tmp_ptr
    pha
    lda #0
    adc zp_tmp_ptr + 1
    tay                         ; high byte in Y
    pla                         ; low byte in A

    ; Store updated pointer back to zp_ch[x]_ptr
    cpx #0
    bne @check_ch1
    sta zp_ch1_ptr
    sty zp_ch1_ptr + 1
    jmp @setup_envelope
@check_ch1:
    cpx #1
    bne @check_ch2
    sta zp_ch2_ptr
    sty zp_ch2_ptr + 1
    jmp @setup_envelope
@check_ch2:
    cpx #2
    bne @check_ch3
    sta zp_ch3_ptr
    sty zp_ch3_ptr + 1
    jmp @setup_envelope
@check_ch3:
    sta zp_ch4_ptr
    sty zp_ch4_ptr + 1

@setup_envelope:
    lda #1
    sta ch_mod_phase,x          ; the note's first frame carries its nominal divider
    ; Check if note is Rest (AUDF == 0 or peak_vol == 0)
    lda ch_audf,x
    beq @is_rest
    lda ch_peak_vol,x
    beq @is_rest

    ; Clamp effective sustain target to note peak volume (min(ch_sus, ch_peak_vol))
    lda ch_sus,x
    cmp ch_peak_vol,x
    bcc @keep_sus
    lda ch_peak_vol,x
@keep_sus:
    sta ch_sus_lvl,x

    ; Trigger new note: Attack phase
    lda #1
    sta ch_env_phase,x
    lda #0
    sta ch_env_frame,x
    sta ch_cur_vol,x
    rts

@is_rest:
    lda #0
    sta ch_env_phase,x
    sta ch_cur_vol,x
    rts
.endp

; =============================================================================
; load_pattern_ptrs
; Loads pattern track pointers for current seq_step_idx into zp_ch1..zp_ch4
; =============================================================================
.proc load_pattern_ptrs
    ; zp_tmp_ptr = seq_ptr + seq_step_idx
    clc
    lda seq_ptr_lo
    adc seq_step_idx
    sta zp_tmp_ptr
    lda seq_ptr_hi
    adc #0
    sta zp_tmp_ptr + 1

    ldy #0
    lda (zp_tmp_ptr),y
    tax
    iny
    lda (zp_tmp_ptr),y
    tay

    ; Check for $FFFF end of sequence marker
    cpx #$FF
    bne @valid_pat
    cpy #$FF
    bne @valid_pat

    ; End of song: Loop back to step 0
    lda #0
    sta seq_step_idx
    jmp load_pattern_ptrs

@valid_pat:
    ; X, Y contains address of pattern track list (pat_X_tracks)
    stx zp_tmp_ptr
    sty zp_tmp_ptr + 1

    ; Read 4 track pointers (8 bytes) into zp_ch1_ptr .. zp_ch4_ptr
    ldy #0
    lda (zp_tmp_ptr),y
    sta zp_ch1_ptr
    iny
    lda (zp_tmp_ptr),y
    sta zp_ch1_ptr + 1

    iny
    lda (zp_tmp_ptr),y
    sta zp_ch2_ptr
    iny
    lda (zp_tmp_ptr),y
    sta zp_ch2_ptr + 1

    iny
    lda (zp_tmp_ptr),y
    sta zp_ch3_ptr
    iny
    lda (zp_tmp_ptr),y
    sta zp_ch3_ptr + 1

    iny
    lda (zp_tmp_ptr),y
    sta zp_ch4_ptr
    iny
    lda (zp_tmp_ptr),y
    sta zp_ch4_ptr + 1
    rts
.endp

; =============================================================================
; scale_env_step
; Computes floor((ch_env_frame,x * Y) / A) for 1 <= ch_env_frame,x < A <= 255
; and 0 <= Y <= 15. Uses zp_tmp_ptr (+0: denom, +1: quotient); preserves X.
; =============================================================================
.proc scale_env_step
    sta zp_tmp_ptr              ; denom
    lda #0
    sta zp_tmp_ptr + 1          ; quotient = 0
    cpy #0
    beq @done
@loop:
    clc
    adc ch_env_frame,x          ; A = (rem + num) & $FF, C = 9-bit carry
    bcs @sub_denom              ; sum >= 256 > denom; C=1 guaranteed
    cmp zp_tmp_ptr
    bcc @next_iter              ; sum < denom -> keep remainder
@sub_denom:
    sbc zp_tmp_ptr              ; C=1 guaranteed; A = sum - denom
    inc zp_tmp_ptr + 1          ; quotient++
@next_iter:
    dey
    bne @loop
@done:
    lda zp_tmp_ptr + 1
    rts
.endp

; =============================================================================
; update_envelopes
; Computes per-frame ADSR volume for all 4 channels
; =============================================================================
.proc update_envelopes
    ldx #0
@env_loop:
    lda ch_env_phase,x
    beq @phase_idle
    cmp #1
    beq @phase_attack
    cmp #2
    beq @phase_decay
    cmp #3
    beq @phase_sustain
    jmp @phase_release

@phase_idle:
    lda #0
    sta ch_cur_vol,x
    jmp @next_channel

@phase_attack:
    lda ch_att,x
    beq @attack_instant
    inc ch_env_frame,x
    lda ch_env_frame,x
    cmp ch_att,x
    bcc @attack_ramp

@attack_instant:
    ; Attack finished -> Decay phase
    lda #2
    sta ch_env_phase,x
    lda #0
    sta ch_env_frame,x
    lda ch_peak_vol,x
    sta ch_cur_vol,x
    jmp @next_channel

@attack_ramp:
    ; Linear multi-step ramp: max(1, (ch_env_frame,x * ch_peak_vol,x) // ch_att,x)
    ldy ch_peak_vol,x
    lda ch_att,x
    jsr scale_env_step
    cmp #0
    bne @store_att
    lda #1
@store_att:
    sta ch_cur_vol,x
    jmp @next_channel

@phase_decay:
    lda ch_dec,x
    beq @decay_to_sustain
    inc ch_env_frame,x
    lda ch_env_frame,x
    cmp ch_dec,x
    bcc @decay_ramp

@decay_to_sustain:
    ; Decay finished -> enter Sustain on this frame
    lda #3
    sta ch_env_phase,x
    jmp @phase_sustain

@decay_ramp:
    ; Linear multi-step decay: peak - ((ch_env_frame,x * (peak - sus)) // ch_dec,x)
    lda ch_peak_vol,x
    sec
    sbc ch_sus_lvl,x
    tay
    lda ch_dec,x
    jsr scale_env_step
    sta zp_tmp_ptr
    lda ch_peak_vol,x
    sec
    sbc zp_tmp_ptr
    sta ch_cur_vol,x
    jmp @next_channel

@phase_sustain:
    lda ch_sus_lvl,x
    sta ch_cur_vol,x
    ; Enter release when remaining VBI frames <= ch_rel,x:
    ; frames_remaining = (ch_dur,x - 1) * tempo_divider + tick_counter
    lda ch_rel,x
    beq @sustain_keep           ; release == 0 -> sustain until end of note
    cmp ch_dur,x
    bcc @sustain_keep           ; ch_rel < ch_dur <= frames_remaining -> keep sustain
    ldy ch_dur,x
    beq @enter_release          ; defensive guard if ch_dur == 0
    dey                         ; Y = ch_dur,x - 1
    lda tick_counter            ; A = tick_counter (1..tempo_divider)
    cpy #0
    beq @check_rel_frames
@rem_frames_loop:
    clc
    adc tempo_divider
    bcs @sustain_keep           ; >= 256 frames remaining > ch_rel,x
    dey
    bne @rem_frames_loop
@check_rel_frames:
    cmp ch_rel,x
    beq @enter_release
    bcs @sustain_keep           ; frames_remaining > ch_rel,x -> keep sustain
@enter_release:
    lda #4
    sta ch_env_phase,x
    jmp @phase_release
@sustain_keep:
    jmp @next_channel

@phase_release:
    ; Release phase: fade volume towards 0
    lda ch_cur_vol,x
    beq @release_done
    sec
    sbc #1
    sta ch_cur_vol,x
@release_done:

@next_channel:
    inx
    cpx #4
    beq @env_all_done
    jmp @env_loop
@env_all_done:
    rts
.endp

; =============================================================================
; apply_modulation
; Per-frame divider modulation, called from music_update between update_envelopes and
; write_pokey_registers -- so it changes ch_audf and the existing register write publishes it.
;
; For every channel whose instrument record asked for MOD_OCTAVE_PULSE, alternate ch_audf
; between the note's nominal divider N (ch_audf_base) and N // 2, once per 50 Hz frame,
; restarting at every note onset. ``lsr`` on an 8-bit value is exactly ``N // 2``, so this
; cannot disagree with the WAV renderer's ``pokey_hw.octave_pulse_divider``.
;
; A frame the channel is not sounding keeps the note's nominal divider, which is what
; Experiment 28's apply_c1 does -- it never writes a register the baseline did not write.
; The phase advances once per call whether or not the frame is sounding, so the alternation
; stays in step with the frame offsets the renderer uses.
; =============================================================================
.proc apply_modulation
    lda any_mod
    beq @done                   ; an ordinary song pays one load and one branch per frame
    ldx #0
@loop:
    lda ch_mod,x
    cmp #MOD_OCTAVE_PULSE       ; anything else is not a descriptor this version defines
    bne @next_channel
    lda ch_mod_phase,x
    eor #1
    sta ch_mod_phase,x          ; Z reflects the toggled phase (sta does not change flags)
    beq @nominal
    lda ch_cur_vol,x
    beq @nominal                ; silent frame -> the note's nominal divider
    lda ch_audf_base,x          ; sounding, phase 1 -> N // 2
    lsr
    sta ch_audf,x
    jmp @next_channel
@nominal:
    lda ch_audf_base,x
    sta ch_audf,x
@next_channel:
    inx
    cpx #4
    bne @loop
@done:
    rts
.endp

; =============================================================================
; write_pokey_registers
; Writes AUDF1..4, AUDC1..4, and AUDCTL to POKEY hardware registers
; Supports both 8-bit mode and 16-bit bass pairing
; =============================================================================
.proc write_pokey_registers
    lda audctl_mode
    sta AUDCTL_REG

    ; Check 16-bit bass mode (bit 4: AUDCTL_JOIN_1_2_16BIT)
    and #$10
    bne @write_16bit

    ; --- Standard 8-bit Mode (All 4 channels independent) ---
    ; Channel 1 (Bass)
    lda ch_audf + 0
    sta AUDF1_REG
    lda #0
    ldy ch_mute_mask + 0
    bne @mute_ch1
    lda ch_cur_vol + 0
    beq @mute_ch1
    ora ch_dist + 0
@mute_ch1:
    sta AUDC1_REG

    ; Channel 2 (Counter / Harmony)
    lda ch_audf + 1
    sta AUDF2_REG
    lda #0
    ldy ch_mute_mask + 1
    bne @mute_ch2
    lda ch_cur_vol + 1
    beq @mute_ch2
    ora ch_dist + 1
@mute_ch2:
    sta AUDC2_REG
    jmp @write_ch3_ch4

@write_16bit:
    ; --- 16-bit Bass Mode (Channels 1 & 2 joined) ---
    ; Ch 1 = AUDF low divider, AUDC muted
    lda ch_audf + 0
    sta AUDF1_REG
    lda #0
    sta AUDC1_REG

    ; Ch 2 = AUDF high divider, AUDC active volume
    lda ch_audf + 1
    sta AUDF2_REG
    lda #0
    ldy ch_mute_mask + 0
    bne @mute_ch2_16
    ldy ch_mute_mask + 1
    bne @mute_ch2_16
    lda ch_cur_vol + 1
    beq @mute_ch2_16
    ora ch_dist + 1
@mute_ch2_16:
    sta AUDC2_REG

@write_ch3_ch4:
    ; Channel 3 (Lead Melody)
    lda ch_audf + 2
    sta AUDF3_REG
    lda #0
    ldy ch_mute_mask + 2
    bne @mute_ch3
    lda ch_cur_vol + 2
    beq @mute_ch3
    ora ch_dist + 2
@mute_ch3:
    sta AUDC3_REG

    ; Channel 4 (Rhythm / Percussion / Ornament)
    lda ch_audf + 3
    sta AUDF4_REG
    lda #0
    ldy ch_mute_mask + 3
    bne @mute_ch4
    lda ch_cur_vol + 3
    beq @mute_ch4
    ora ch_dist + 3
@mute_ch4:
    sta AUDC4_REG
    rts
.endp

; =============================================================================
; silence_pokey
; Sets all audio channels to volume 0 and zeroes AUDF registers
; =============================================================================
.proc silence_pokey
    lda #0
    sta AUDCTL_REG
    sta AUDC1_REG
    sta AUDC2_REG
    sta AUDC3_REG
    sta AUDC4_REG
    sta AUDF1_REG
    sta AUDF2_REG
    sta AUDF3_REG
    sta AUDF4_REG
    rts
.endp

; =============================================================================
; Player Runtime Variables (Relocatable BSS / Data area)
; =============================================================================
music_playing   .byte 0
tempo_divider   .byte 4
tick_counter    .byte 1
audctl_mode     .byte 0
seq_step_idx    .byte 0

song_ptr_lo     .byte 0
song_ptr_hi     .byte 0
inst_ptr_lo     .byte 0
inst_ptr_hi     .byte 0
seq_ptr_lo      .byte 0
seq_ptr_hi      .byte 0

; Per-channel state arrays (4 channels: 0..3)
ch_audf         .byte 0, 0, 0, 0
ch_dur          .byte 0, 0, 0, 0
ch_peak_vol     .byte 0, 0, 0, 0
ch_cur_vol      .byte 0, 0, 0, 0
ch_sus_lvl      .byte 0, 0, 0, 0
ch_env_phase    .byte 0, 0, 0, 0
ch_env_frame    .byte 0, 0, 0, 0

ch_dist         .byte $C0, $A0, $A0, $00
ch_att          .byte 0, 1, 1, 0
ch_dec          .byte 4, 3, 4, 3
ch_sus          .byte 10, 9, 12, 8
ch_rel          .byte 2, 2, 3, 2
ch_mute_mask    .byte 0, 0, 0, 0

; Per-channel modulation state (song data format version 1)
ch_mod          .byte 0, 0, 0, 0    ; descriptor from the instrument table (0 = none)
ch_mod_phase    .byte 0, 0, 0, 0    ; toggles once per frame: 0 = nominal, 1 = N//2
ch_audf_base    .byte 0, 0, 0, 0    ; the note's nominal divider N
any_mod         .byte 0             ; OR of ch_mod, so an ordinary song skips the loop
format_ok       .byte 0             ; 1 once music_init accepted the song's format version

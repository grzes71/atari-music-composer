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
SONG_FORMAT_VERSION_V2 = 2
MAX_V2_INSTRUMENTS = 32
MAX_V2_OPCODE = 1
OPCODE_PROGRAM_CHANGE = 1
MAX_V2_PARSE_COMMANDS = 8

; Macro flags in macro step byte +1
MACRO_FLAG_AUDF_FIXED   = $01
MACRO_FLAG_USE_DIST     = $02
MACRO_FLAG_USE_VOL      = $04

; Modulation descriptors: instrument record byte 6 (v1) / inst_flags (v2)
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

    ; 2. Read the format version, then dispatch to v1 or v2 instrument initialization
    lda inst_ptr_lo
    sta zp_tmp_ptr
    lda inst_ptr_hi
    sta zp_tmp_ptr + 1

    ldy #0
    lda (zp_tmp_ptr),y          ; format version
    cmp #SONG_FORMAT_VERSION
    beq @format_v1
    cmp #SONG_FORMAT_VERSION_V2
    beq @format_v2

@bad_format:
    ; Unknown or unsupported format version: stay stopped and silence POKEY.
    lda #0
    sta format_ok
    sta is_v2
    sta music_playing
    jsr silence_pokey
    rts

@format_v1:
    lda #0
    sta is_v2
    sta any_mod
    lda #1
    sta format_ok
    iny                         ; Y = 1, the first v1 instrument byte

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
    lda #$FF
    sta ch_macro_off,x          ; v1 has no v2 macros
    lda #0
    sta ch_p_dur,x
    lda #1
    sta ch_mod_phase,x          ; a note starts on its nominal divider
    iny
    inx
    cpx #4
    bne load_inst_loop
    jmp @init_reset_state

@format_v2:
    ldy #1
    lda (zp_tmp_ptr),y          ; instrument_count (1..32)
    beq @bad_format
    cmp #(MAX_V2_INSTRUMENTS + 1)
    bcs @bad_format
    sta inst_count

    ; Validate and load initial_ch_inst[0..3] at +2..+5
    ldx #0
@load_init_ch_inst:
    iny
    lda (zp_tmp_ptr),y
    cmp inst_count
    bcs @bad_format
    sta ch_inst,x
    inx
    cpx #4
    bne @load_init_ch_inst

    ; +6..+7: macros_ptr
    iny
    lda (zp_tmp_ptr),y
    sta macros_ptr_lo
    iny
    lda (zp_tmp_ptr),y
    sta macros_ptr_hi

    ; SoA base = instruments_ptr + 8
    clc
    lda inst_ptr_lo
    adc #8
    sta inst_soa_lo
    lda inst_ptr_hi
    adc #0
    sta inst_soa_hi

    lda #1
    sta is_v2
    sta format_ok
    sta any_mod

    ldx #0
@load_v2_ch_loop:
    lda ch_inst,x
    tay
    jsr load_v2_inst_ch
    lda #1
    sta ch_mod_phase,x
    inx
    cpx #4
    bne @load_v2_ch_loop

@init_reset_state:
    ; 3. Reset Sequence and State
    lda #0
    sta seq_step_idx
    sta music_playing

    ; Force immediate note loading on all channels and reset runtime state
    ldx #3
@clr_ch_loop:
    sta ch_dur,x
    sta ch_env_phase,x
    sta ch_cur_vol,x
    sta ch_sus_lvl,x
    sta ch_mute_mask,x
    sta ch_macro_active,x
    sta ch_pitch_rem,x
    sta ch_pitch_delta,x
    sta ch_out_vol,x
    lda ch_dist,x
    sta ch_out_dist,x
    lda #0
    dex
    bpl @clr_ch_loop

    ; Load first pattern
    jsr load_pattern_ptrs

    ; 4. Silence POKEY
    jsr silence_pokey
    rts
.endp

; =============================================================================
; load_v2_inst_ch
; Loads all 10 SoA bytes for instrument Y into channel X (0..3). Preserves X.
; Timing: ~440 cycles (10 iterations x ~43 cycles). Clobbers: A, zp_tmp_ptr.
; =============================================================================
.proc load_v2_inst_ch
    stx tmp_ch_x                ; 4 cy
    lda inst_soa_lo             ; 4 cy
    sta zp_tmp_ptr              ; 3 cy
    lda inst_soa_hi             ; 4 cy
    sta zp_tmp_ptr + 1          ; 3 cy
    lda #0                      ; 2 cy
    sta tmp_soa_row             ; 4 cy
@row_loop:
    lda (zp_tmp_ptr),y          ; 5+ cy
    sta ch_dist,x               ; 5 cy: stride-4 SoA targets ch_dist..ch_p_step
    inc tmp_soa_row             ; 6 cy
    lda tmp_soa_row             ; 4 cy
    cmp #10                     ; 2 cy
    beq @done                   ; 2/3 cy
    inx                         ; 2 cy
    inx                         ; 2 cy
    inx                         ; 2 cy
    inx                         ; 2 cy
    clc                         ; 2 cy
    lda zp_tmp_ptr              ; 3 cy
    adc inst_count              ; 4 cy
    sta zp_tmp_ptr              ; 3 cy
    bcc @row_loop               ; 2/3 cy
    inc zp_tmp_ptr + 1          ; 5 cy
    jmp @row_loop               ; 3 cy
@done:
    ldx tmp_ch_x                ; 4 cy
    rts                         ; 6 cy
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
; advance_ch_ptr_a
; Adds A bytes to zp_ch[x]_ptr (X = 0..3). Preserves X.
; =============================================================================
.proc advance_ch_ptr_a
    sta tmp_ptr_adv             ; 4 cy
    txa                         ; 2 cy
    asl                         ; 2 cy
    tay                         ; 2 cy
    clc                         ; 2 cy
    lda zp_ch1_ptr,y            ; 4 cy
    adc tmp_ptr_adv             ; 4 cy
    sta zp_ch1_ptr,y            ; 5 cy
    bcc @done                   ; 2/3 cy
    clc                         ; 2 cy
    lda zp_ch1_ptr + 1,y        ; 4 cy
    adc #1                      ; 2 cy
    sta zp_ch1_ptr + 1,y        ; 5 cy
@done:
    rts                         ; 6 cy
.endp

; =============================================================================
; fetch_channel_note
; Fetches next note/rest event (3 B) or v2 command (4 B, 0 ticks) for channel X.
; If $FF encountered, advances sequence and reloads pattern pointers safely.
; =============================================================================
.proc fetch_channel_note
    lda #(MAX_V2_PARSE_COMMANDS + 1) ; 2 cy: allow max 8 commands before note/rest
    sta cmd_guard               ; 4 cy

@load_ptr_and_parse:
    txa                         ; 2 cy
    asl                         ; 2 cy: X * 2
    tay                         ; 2 cy
    lda zp_ch1_ptr,y            ; 4 cy
    sta zp_tmp_ptr              ; 3 cy
    lda zp_ch1_ptr + 1,y        ; 4 cy
    sta zp_tmp_ptr + 1          ; 3 cy

@parse_event:
    ldy #0                      ; 2 cy
    lda (zp_tmp_ptr),y          ; 5 cy: Read AUDF, $FF, or command prefix $00
    cmp #$FF                    ; 2 cy
    beq @handle_end_track       ; 2/3 cy

    ldy is_v2                   ; 4 cy
    bne @v2_check_event         ; 2/3 cy: v1 parser treats all non-$FF as 3-byte event
    jmp @got_note
@v2_check_event:
    cmp #0                      ; 2 cy
    beq @check_cmd_byte1        ; 2/3 cy
    jmp @got_note
@check_cmd_byte1:
    ldy #1                      ; 2 cy
    lda (zp_tmp_ptr),y          ; 5 cy: Read duration / command sub-byte
    beq @handle_v2_cmd          ; 2/3 cy: [0, 0, OPCODE, PARAM]
    ldy #0                      ; 2 cy
    lda #0                      ; 2 cy: Normal rest [0, dur>0, vol]
    jmp @got_note               ; 3 cy

@handle_v2_cmd:
    dec cmd_guard               ; 6 cy
    beq @early_end_track        ; 2/3 cy: Exceeded 8 consecutive commands -> silence safely
    ldy #2                      ; 2 cy
    lda (zp_tmp_ptr),y          ; 5 cy: OPCODE
    cmp #OPCODE_PROGRAM_CHANGE  ; 2 cy: Only $01 supported in v2 Iter 1
    bne @early_end_track        ; 2/3 cy: Unknown opcode -> mute channel safely
    ldy #3                      ; 2 cy
    lda (zp_tmp_ptr),y          ; 5 cy: PARAM (inst_id)
    cmp inst_count              ; 4 cy
    bcs @early_end_track        ; 2/3 cy: Out-of-bounds inst_id -> mute channel safely

    ; Execute PROGRAM_CHANGE with 0 tick cost and clear previous behavior state
    sta ch_inst,x               ; 5 cy
    pha                         ; 3 cy
    lda #0                      ; 2 cy
    sta ch_macro_active,x       ; 5 cy
    sta ch_pitch_rem,x          ; 5 cy
    sta ch_pitch_delta,x        ; 5 cy
    sta ch_env_phase,x          ; 5 cy
    sta ch_cur_vol,x            ; 5 cy
    lda #1                      ; 2 cy
    sta ch_mod_phase,x          ; 5 cy
    lda #4                      ; 2 cy
    jsr advance_ch_ptr_a        ; Advance past 4-byte command
    pla                         ; 4 cy
    tay                         ; 2 cy: Y = new inst_id
    jsr load_v2_inst_ch         ; Load SoA fields into channel X (~440 cy)
    jmp @load_ptr_and_parse     ; Continue parsing in same call (0 ticks consumed)

@handle_end_track:
    cpx #0
    bne @early_end_track

    ; Channel 0 reached end of track: Advance sequence step
    txa
    pha
    clc
    lda seq_step_idx
    adc #2
    sta seq_step_idx
    jsr load_pattern_ptrs
    pla
    tax

@reload_track_ptr:
    ; Reset 8-cmd guard and parse from start of new pattern (supports PROGRAM_CHANGE at pat start!)
    lda #(MAX_V2_PARSE_COMMANDS + 1)
    sta cmd_guard
    jmp @load_ptr_and_parse

@early_end_track:
    ; Channel X reached $FF early or hit a stream guard: hold silence safely
    lda #0
    sta ch_audf,x
    sta ch_audf_base,x
    sta ch_peak_vol,x
    sta ch_cur_vol,x
    sta ch_env_phase,x
    sta ch_macro_active,x
    sta ch_pitch_rem,x
    sta ch_pitch_delta,x
    lda #1
    sta ch_dur,x
    rts

@got_note:
    ldy #0
    lda (zp_tmp_ptr),y          ; Read AUDF
    sta ch_audf,x               ; Store AUDF
    sta ch_audf_base,x          ; and keep N
    iny

    lda (zp_tmp_ptr),y          ; Read duration
    sta ch_dur,x
    iny

    lda (zp_tmp_ptr),y          ; Read volume
    sta ch_peak_vol,x

    lda #3                      ; Advance pointer past 3-byte event
    jsr advance_ch_ptr_a

@setup_envelope:
    lda #1
    sta ch_mod_phase,x          ; the note's first frame carries its nominal divider
    lda #0
    sta ch_macro_active,x       ; Clear prior note's transient/pitch state
    sta ch_pitch_rem,x
    sta ch_pitch_delta,x

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

    ; v2 per-note behavior initialization (pitch envelope & transient macro)
    lda is_v2
    beq @note_init_done

    lda ch_p_dur,x
    beq @no_note_pitch
    sta ch_pitch_rem,x
    lda ch_p_start,x
    sta ch_pitch_delta,x
@no_note_pitch:

    lda ch_macro_off,x
    cmp #$FF
    beq @note_init_done
    tay
    lda macros_ptr_lo
    sta zp_tmp_ptr
    lda macros_ptr_hi
    sta zp_tmp_ptr + 1
    lda (zp_tmp_ptr),y
    sta ch_macro_lo,x
    iny
    lda (zp_tmp_ptr),y
    sta ch_macro_hi,x
    ora ch_macro_lo,x
    beq @note_init_done         ; guard against null macro pointer ($0000)

    lda ch_macro_lo,x
    sta zp_tmp_ptr
    lda ch_macro_hi,x
    sta zp_tmp_ptr + 1
    ldy #0
    lda (zp_tmp_ptr),y          ; step 0 frames_per_step ($00 = end)
    beq @note_init_done
    sta ch_macro_cnt,x
    lda #0
    sta ch_macro_step,x
    lda #1
    sta ch_macro_active,x

@note_init_done:
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
; =============================================================================
; add_signed_clamp
; Input:  A = unsigned byte (0..255), tmp_delta = signed two's complement offset
; Output: A = clamp_0_255(A + signed tmp_delta). Preserves X; clobbers Y.
; Timing: 12..16 cycles.
; =============================================================================
.proc add_signed_clamp
    ldy tmp_delta               ; 4 cy: N = sign of delta
    bpl @pos_off                ; 2/3 cy
    clc                         ; 2 cy
    adc tmp_delta               ; 4 cy: C=1 => sum >= 0; C=0 => underflow < 0
    bcs @ok                     ; 2/3 cy
    lda #$00                    ; 2 cy
    rts                         ; 6 cy
@pos_off:
    clc                         ; 2 cy
    adc tmp_delta               ; 4 cy: C=1 => overflow >= 256
    bcc @ok                     ; 2/3 cy
    lda #$FF                    ; 2 cy
@ok:
    rts                         ; 6 cy
.endp

.proc apply_modulation
    ; Mirror base dist/vol -> ch_out_dist/ch_out_vol for unified POKEY write path
    ldx #3
@copy_out_defaults:
    lda ch_dist,x
    sta ch_out_dist,x
    lda ch_cur_vol,x
    sta ch_out_vol,x
    dex
    bpl @copy_out_defaults

    lda any_mod
    bne @run_mod
    rts                         ; fast exit for v1 songs with no modulation
@run_mod:
    ldx #0
@loop:
    lda ch_mod,x
    and #MOD_OCTAVE_PULSE       ; check C1 octave pulse bit
    beq @c1_nominal
    lda ch_mod_phase,x
    eor #1
    sta ch_mod_phase,x          ; Z reflects the toggled phase
    beq @c1_nominal
    lda ch_cur_vol,x
    beq @c1_nominal             ; silent frame -> nominal divider
    lda ch_audf_base,x          ; sounding, phase 1 -> N // 2
    lsr
    sta ch_audf,x
    jmp @check_v2_behaviors
@c1_nominal:
    lda ch_audf_base,x
    sta ch_audf,x

@check_v2_behaviors:
    lda is_v2
    bne @do_v2_behaviors
    jmp @next_channel

@do_v2_behaviors:
    ; Skip behaviors on idle/rest channel
    lda ch_env_phase,x
    bne @ch_active_v2
    lda ch_macro_active,x
    bne @ch_active_v2
    jmp @next_channel

@ch_active_v2:
    ; 1. Pitch Envelope (if active)
    lda ch_pitch_rem,x
    beq @after_pitch

    lda ch_pitch_delta,x
    sta tmp_delta
    lda ch_audf,x
    jsr add_signed_clamp
    sta ch_audf,x

    dec ch_pitch_rem,x
    beq @pitch_expired
    clc
    lda ch_pitch_delta,x
    adc ch_p_step,x
    bvc @store_pitch_d
    ldy ch_p_step,x
    bpl @clamp_p_pos
    lda #$80
    jmp @store_pitch_d
@clamp_p_pos:
    lda #$7F
@store_pitch_d:
    sta ch_pitch_delta,x
    jmp @after_pitch
@pitch_expired:
    lda #0
    sta ch_pitch_delta,x

@after_pitch:
    ; 2. Transient Macro Engine (if active)
    lda ch_macro_active,x
    bne @run_macro
    jmp @next_channel

@run_macro:
    lda ch_macro_lo,x
    sta zp_tmp_ptr
    lda ch_macro_hi,x
    sta zp_tmp_ptr + 1
    ldy ch_macro_step,x
    iny                         ; +1: flags
    lda (zp_tmp_ptr),y
    sta tmp_m_flags
    iny                         ; +2: audc_val
    lda (zp_tmp_ptr),y
    sta tmp_m_audc
    iny                         ; +3: audf_val
    lda (zp_tmp_ptr),y
    sta tmp_m_audf

    ; Optional distortion override
    lda tmp_m_flags
    and #MACRO_FLAG_USE_DIST
    beq @skip_m_dist
    lda tmp_m_audc
    and #$E0
    sta ch_out_dist,x
@skip_m_dist:

    ; Optional volume override
    lda tmp_m_flags
    and #MACRO_FLAG_USE_VOL
    beq @skip_m_vol
    lda tmp_m_audc
    and #$0F
    sta ch_out_vol,x
@skip_m_vol:

    ; AUDF: fixed value or signed offset
    lda tmp_m_flags
    and #MACRO_FLAG_AUDF_FIXED
    beq @m_audf_offset
    lda tmp_m_audf
    sta ch_audf,x
    jmp @advance_macro
@m_audf_offset:
    lda tmp_m_audf
    sta tmp_delta
    lda ch_audf,x
    jsr add_signed_clamp
    sta ch_audf,x

@advance_macro:
    dec ch_macro_cnt,x
    bne @next_channel
    lda ch_macro_step,x
    clc
    adc #4
    sta ch_macro_step,x
    tay
    lda (zp_tmp_ptr),y          ; next step frames_per_step ($00 = end)
    beq @macro_finished
    sta ch_macro_cnt,x
    jmp @next_channel
@macro_finished:
    lda #0
    sta ch_macro_active,x

@next_channel:
    inx
    cpx #4
    beq @done
    jmp @loop
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
    lda ch_out_vol + 0
    beq @mute_ch1
    ora ch_out_dist + 0
@mute_ch1:
    sta AUDC1_REG

    ; Channel 2 (Counter / Harmony)
    lda ch_audf + 1
    sta AUDF2_REG
    lda #0
    ldy ch_mute_mask + 1
    bne @mute_ch2
    lda ch_out_vol + 1
    beq @mute_ch2
    ora ch_out_dist + 1
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
    lda ch_out_vol + 1
    beq @mute_ch2_16
    ora ch_out_dist + 1
@mute_ch2_16:
    sta AUDC2_REG

@write_ch3_ch4:
    ; Channel 3 (Lead Melody)
    lda ch_audf + 2
    sta AUDF3_REG
    lda #0
    ldy ch_mute_mask + 2
    bne @mute_ch3
    lda ch_out_vol + 2
    beq @mute_ch3
    ora ch_out_dist + 2
@mute_ch3:
    sta AUDC3_REG

    ; Channel 4 (Rhythm / Percussion / Ornament)
    lda ch_audf + 3
    sta AUDF4_REG
    lda #0
    ldy ch_mute_mask + 3
    bne @mute_ch4
    lda ch_out_vol + 3
    beq @mute_ch4
    ora ch_out_dist + 3
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

; Contiguous 10 SoA channel instrument slots (stride = 4 bytes between consecutive tables!)
; load_v2_inst_ch indexes ch_dist,x stepping X by +4 across these exact 10 arrays.
ch_dist         .byte $C0, $A0, $A0, $00
ch_att          .byte 0, 1, 1, 0
ch_dec          .byte 4, 3, 4, 3
ch_sus          .byte 10, 9, 12, 8
ch_rel          .byte 2, 2, 3, 2
ch_mod          .byte 0, 0, 0, 0    ; v1 modulation / v2 inst_flags
ch_macro_off    .byte $FF, $FF, $FF, $FF ; v2 macro directory offset ($FF = none)
ch_p_start      .byte 0, 0, 0, 0    ; v2 pitch envelope start delta (signed)
ch_p_dur        .byte 0, 0, 0, 0    ; v2 pitch envelope duration frames (0..15)
ch_p_step       .byte 0, 0, 0, 0    ; v2 pitch envelope per-frame step delta (signed)

ch_mute_mask    .byte 0, 0, 0, 0
ch_mod_phase    .byte 0, 0, 0, 0    ; toggles once per frame: 0 = nominal, 1 = N//2
ch_audf_base    .byte 0, 0, 0, 0    ; the note's nominal divider N
any_mod         .byte 0             ; OR of ch_mod (or 1 in v2)
format_ok       .byte 0             ; 1 once music_init accepted the song's format version

; v2 Runtime Header & Channel Behavior State
is_v2           .byte 0             ; 0 = format v1, 1 = format v2
inst_count      .byte 0             ; number of instruments in v2 song (1..32)
inst_soa_lo     .byte 0             ; base pointer to SoA table 0 (instruments_ptr + 8)
inst_soa_hi     .byte 0
macros_ptr_lo   .byte 0             ; pointer to v2 macro directory
macros_ptr_hi   .byte 0
ch_inst         .byte 0, 0, 0, 0    ; active instrument index per channel (0..31)
ch_out_dist     .byte 0, 0, 0, 0    ; effective distortion for POKEY write
ch_out_vol      .byte 0, 0, 0, 0    ; effective volume for POKEY write
ch_macro_active .byte 0, 0, 0, 0    ; 1 while transient macro is active on note
ch_macro_lo     .byte 0, 0, 0, 0    ; current macro step table base lo
ch_macro_hi     .byte 0, 0, 0, 0    ; current macro step table base hi
ch_macro_step   .byte 0, 0, 0, 0    ; byte offset in current macro (0, 4, 8, ...)
ch_macro_cnt    .byte 0, 0, 0, 0    ; frames remaining in current macro step
ch_pitch_rem    .byte 0, 0, 0, 0    ; frames remaining in pitch envelope
ch_pitch_delta  .byte 0, 0, 0, 0    ; current signed pitch AUDF delta

; Scratch scalar temporaries in BSS (zero extra ZP bytes used!)
cmd_guard       .byte 0
tmp_ch_x        .byte 0
tmp_soa_row     .byte 0
tmp_ptr_adv     .byte 0
tmp_delta       .byte 0
tmp_m_flags     .byte 0
tmp_m_audc      .byte 0
tmp_m_audf      .byte 0

"""High-level Client and Pipeline Facade for AI Music Composition."""

from __future__ import annotations

import json
import logging
from pathlib import Path
import subprocess
from typing import Any, Dict, Optional, Union

logger = logging.getLogger(__name__)


from atari_music.ai.composition import (
    compile_composition_to_pokey_ir,
    interpret_composition_to_music_ir,
)
from atari_music.ai.providers import (
    AICompositionProvider,
    CompositionRequest,
    get_ai_provider,
)
from atari_music.ai.schema import (
    AICompositionDoc,
    AICompositionGenerationError,
    CompositionAttempt,
    MusicCompositionError,
)
from atari_music.ai.validation import validate_composition, validate_composition_report
from atari_music.api import MusicGenerationMetadata, MusicGenerationResult
from atari_music.composer_v4 import ComposerV4QualityReport
from atari_music.ir import calculate_ir_binary_size, compile_ir_to_pokey_frames
from atari_music.mads_exporter import export_mads_asm


def load_composition_json(source: Union[str, Path, Dict[str, Any]]) -> AICompositionDoc:
    """Load and validate an AI Composition JSON document from file, string, or dict.
    
    Parameters
    ----------
    source : Union[str, Path, Dict[str, Any]]
        File path, raw JSON string, or parsed dictionary.
        
    Returns
    -------
    AICompositionDoc
        Fully validated composition document.
    """
    if isinstance(source, Path):
        content = source.read_text(encoding="utf-8")
        data = json.loads(content)
    elif isinstance(source, str):
        # Check if source is a file path
        p = Path(source)
        if len(source) < 512 and p.exists() and p.is_file():
            content = p.read_text(encoding="utf-8")
            data = json.loads(content)
        else:
            data = json.loads(source)
    elif isinstance(source, dict):
        data = source
    else:
        raise MusicCompositionError(f"Unsupported source type: {type(source).__name__}")

    return validate_composition(data)


def generate_music_from_composition(
    composition: Union[AICompositionDoc, Dict[str, Any], str, Path],
) -> MusicGenerationResult:
    """Execute the complete translation pipeline: AI Composition -> Music IR -> POKEY IR -> Result.
    
    Parameters
    ----------
    composition : Union[AICompositionDoc, Dict[str, Any], str, Path]
        The composition document to process.
        
    Returns
    -------
    MusicGenerationResult
        Standard result object containing Music IR, POKEY IR, and export methods (render_wav, save_json).
    """
    if not isinstance(composition, AICompositionDoc):
        doc = load_composition_json(composition)
    else:
        doc = composition

    # 1. Translate to Symbolic Music IR
    music_song = interpret_composition_to_music_ir(doc)

    # 2. Compile to POKEY IR
    pokey_song = compile_composition_to_pokey_ir(doc, music_song)

    # 3. Calculate metrics
    mem_size = calculate_ir_binary_size(pokey_song)
    frames = compile_ir_to_pokey_frames(pokey_song)
    duration_s = float(len(frames)) / 50.0

    metadata = MusicGenerationMetadata(
        profile=doc.intent.style if doc.intent and doc.intent.style else "ai_composition",
        seed=0,
        tempo=pokey_song.tempo_bpm,
        key=pokey_song.key,
        mode=pokey_song.mode,
        duration=duration_s,
        channels_used=doc.hardware.channels,
        form=" ".join(doc.sequence),
        memory_size_bytes=mem_size,
        pattern_count=len(pokey_song.patterns),
        sequence_length=len(pokey_song.sequence),
        frames_per_tick=pokey_song.frames_per_tick,
        uses_16bit_bass=pokey_song.uses_16bit_bass,
    )

    quality = ComposerV4QualityReport(
        profile_name=metadata.profile,
        memory_size=mem_size,
        under_budget=(mem_size <= 2048),
        channels_used=metadata.channels_used,
        active_channels_audio=metadata.channels_used,
        duration=duration_s,
        tempo=metadata.tempo,
        form=metadata.form,
        pitch_range=24,
        repetition=0.5,
        novelty=0.5,
        melodic_density=0.5,
        rhythmic_density=0.5,
        harmonic_complexity=0.5,
        pattern_count=len(pokey_song.patterns),
        attempts_needed=1,
    )

    return MusicGenerationResult(
        music_ir=music_song,
        pokey_ir=pokey_song,
        metadata=metadata,
        quality_report=quality,
    )


def generate_music_from_json(json_source: Union[str, Path, Dict[str, Any]]) -> MusicGenerationResult:
    """Convenience alias for generate_music_from_composition."""
    return generate_music_from_composition(json_source)


def generate_composition_with_retry(
    request: CompositionRequest,
    provider: AICompositionProvider,
    max_retries: int = 3,
) -> AICompositionDoc:
    """Generate and validate an AI composition using an iterative repair loop with feedback.
    
    Attempts up to 1 + max_retries generations (default: 1 initial + 3 retries = max 4 attempts).
    If validation fails, the structured validation report is formatted into feedback
    and sent back to the provider along with the previous invalid composition.
    
    Parameters
    ----------
    request : CompositionRequest
        High-level musical request parameters.
    provider : AICompositionProvider
        AI provider backend to query (Mock or OpenAI).
    max_retries : int, default=3
        Maximum retry attempts after initial failure. Must be >= 0.
        
    Returns
    -------
    AICompositionDoc
        Fully validated composition document.
        
    Raises
    ------
    AICompositionGenerationError
        If validation errors cannot be resolved after max_retries retries.
    """
    max_attempts = 1 + max(0, max_retries)
    history: list[CompositionAttempt] = []
    feedback: Optional[str] = None
    previous_composition: Optional[Dict[str, Any]] = None

    for attempt_idx in range(1, max_attempts + 1):
        logger.debug(
            "Composition Repair Loop: starting attempt %d/%d (max_retries=%d)",
            attempt_idx,
            max_attempts,
            max_retries,
        )

        # 1. Ask provider for composition (with feedback/context if retrying)
        raw_dict = provider.generate_composition(
            request,
            feedback=feedback,
            previous_composition=previous_composition,
        )
        p_name = getattr(provider, "provider_name", type(provider).__name__)
        raw_keys = list(raw_dict.keys()) if isinstance(raw_dict, dict) else []
        logger.debug(
            "Received raw composition payload from provider '%s' (attempt %d, top-level keys: %s)",
            p_name,
            attempt_idx,
            raw_keys,
        )

        # 2. Run full 3-Tier validation report
        report = validate_composition_report(raw_dict)
        attempt_record = CompositionAttempt(
            attempt_number=attempt_idx,
            composition=raw_dict,
            report=report,
        )
        history.append(attempt_record)

        # 3. Check validity
        if report.valid:
            logger.debug(
                "Composition validation PASSED on attempt %d (0 issues). Proceeding with validated composition.",
                attempt_idx,
            )
            return validate_composition(raw_dict)

        # Log detailed validation failure
        issues_summary = [f"[{i.category.upper()}] {i.code}: {i.message}" for i in report.issues]
        logger.debug(
            "Composition validation FAILED on attempt %d with %d issue(s): %s",
            attempt_idx,
            len(report.issues),
            "; ".join(issues_summary),
        )

        # 4. Prepare structured feedback for next attempt
        feedback = report.format_feedback()
        previous_composition = raw_dict

        if attempt_idx < max_attempts:
            logger.debug(
                "Composition Repair Loop: scheduling retry attempt %d with formatted feedback (length: %d chars)",
                attempt_idx + 1,
                len(feedback or ""),
            )

    # All attempts exhausted
    last_report = history[-1].report if history else None
    retries_used = len(history) - 1
    issue_codes = ", ".join(iss.code for iss in (last_report.issues if last_report else []))
    msg = (
        f"AI composition generation failed after {len(history)} attempts "
        f"({retries_used} retries exhausted). Last validation issues: [{issue_codes}]"
    )
    logger.debug(
        "Composition Repair Loop exhausted all %d attempts (%d retries). Last issues: [%s]",
        len(history),
        retries_used,
        issue_codes,
    )
    raise AICompositionGenerationError(
        message=msg,
        attempts_count=len(history),
        last_composition=previous_composition,
        last_report=last_report,
        history=history,
    )


def request_ai_composition(
    request: CompositionRequest,
    provider: Optional[Union[AICompositionProvider, str]] = None,
    provider_name: Optional[str] = None,
    model: Optional[str] = None,
    api_key: Optional[str] = None,
    max_retries: int = 3,
    env_path: Optional[Union[str, Path]] = None,
) -> AICompositionDoc:
    """Request an AI-generated composition, validate it with automatic retry loop, and return the validated document.
    
    Parameters
    ----------
    request : CompositionRequest
        Musical style, mood, tempo, duration, and constraints.
    provider : Optional[Union[AICompositionProvider, str]]
        Specific provider backend instance or name ("mock", "openai").
    provider_name : Optional[str]
        Provider name alias ("mock", "openai").
    model : Optional[str]
        Model name override (e.g. "gpt-4o-mini").
    api_key : Optional[str]
        API key override.
    max_retries : int, default=3
        Maximum retry attempts on validation error (1 initial + max_retries retries).
    env_path : Optional[Union[str, Path]]
        Path to custom .env configuration file.
        
    Returns
    -------
    AICompositionDoc
        Validated composition document.
    """
    p_name = provider if isinstance(provider, str) else provider_name
    p_inst = provider if hasattr(provider, "generate_composition") else None
    active_provider = p_inst or get_ai_provider(p_name, model=model, api_key=api_key, env_path=env_path)
    return generate_composition_with_retry(request, active_provider, max_retries=max_retries)



def build_xex_from_composition(
    composition: Union[AICompositionDoc, Dict[str, Any], str, Path],
    output_path: Union[str, Path] = "output.xex",
    player_address: Union[str, int] = "$4000",
    music_address: Optional[Union[str, int]] = None,
    zp_base: int = 0x80,
    mads_bin: Optional[Union[str, Path]] = None,
    player_asm: Optional[Union[str, Path]] = None,
    **kwargs: Any,
) -> Path:
    """Compile an AI composition directly into an executable Atari XEX file via MADS.
    
    Parameters
    ----------
    composition : Union[AICompositionDoc, Dict[str, Any], str, Path]
        The composition document or path.
    output_path : Union[str, Path]
        Target .xex file path.
    player_address : Union[str, int], default="$4000"
        Installation memory address for player and harness.
    music_address : Optional[Union[str, int]]
        Optional separate address for song data (split-relocation).
    zp_base : int, default=0x80
        Zero page base address ($80..$F0).
    mads_bin : Optional[Union[str, Path]]
        Optional path to mads assembler executable.
    player_asm : Optional[Union[str, Path]]
        Optional explicit path to player.asm. If omitted, checks current working directory,
        repository root, and package directory.
    Returns
    -------
    Path
        Path to the generated .xex file.
    """
    if "output_xex" in kwargs and output_path == "output.xex":
        output_path = kwargs["output_xex"]
    if "mads_exe" in kwargs and mads_bin is None:
        mads_bin = kwargs["mads_exe"]
    if "player_asm" in kwargs and player_asm is None:
        player_asm = kwargs["player_asm"]

    if isinstance(player_address, int):
        player_addr_str = f"${player_address:04X}"
    else:
        player_addr_str = str(player_address)

    music_addr_str = None
    if music_address is not None:
        if isinstance(music_address, int):
            music_addr_str = f"${music_address:04X}"
        else:
            music_addr_str = str(music_address)
    res = generate_music_from_composition(composition)
    song_asm = export_mads_asm(res)

    out_p = Path(output_path)
    out_p.parent.mkdir(parents=True, exist_ok=True)

    # Locate player.asm (explicit -> cwd -> repo root -> package directory)
    if player_asm is not None:
        player_asm_path = Path(player_asm).resolve()
        if not player_asm_path.exists():
            raise FileNotFoundError(f"player.asm not found at: {player_asm}")
    else:
        cwd_player = Path.cwd() / "player.asm"
        root = Path(__file__).resolve().parent.parent.parent.parent
        root_player = root / "player.asm"
        pkg_player = root / "src" / "atari_music" / "asm" / "player.asm"

        if cwd_player.exists():
            player_asm_path = cwd_player
        elif root_player.exists():
            player_asm_path = root_player
        elif pkg_player.exists():
            player_asm_path = pkg_player
        else:
            raise FileNotFoundError(
                "player.asm not found in current folder, repository root, or package directory. "
                "Specify path via player_asm or place player.asm in the current directory."
            )

    # Locate MADS executable
    if mads_bin:
        mads_exe = Path(mads_bin)
    else:
        root = Path(__file__).resolve().parent.parent.parent.parent
        mads_exe = root / "tools" / "mads" / "mads.exe"

    if not mads_exe.exists():
        raise FileNotFoundError(f"MADS assembler not found at: {mads_exe}")

    # Helper to convert ASCII string to ANTIC Mode 2 screen codes
    def _ascii_to_antic(s: str) -> list[int]:
        res = []
        for c in s:
            v = ord(c)
            if 32 <= v <= 95:
                res.append(v - 32)
            elif 96 <= v <= 122:
                res.append(v)
            else:
                res.append(0)
        return res

    if not isinstance(composition, AICompositionDoc):
        comp_doc = load_composition_json(composition)
    else:
        comp_doc = composition

    title_str = (comp_doc.metadata.title or "POKEY Music")[:28]
    title_antic = _ascii_to_antic(title_str)
    tempo_antic = _ascii_to_antic(f"TEMPO:   {comp_doc.metadata.bpm} BPM")

    dur_sec = comp_doc.metadata.duration_seconds
    if dur_sec is None:
        from atari_music.ai.analysis import calculate_composition_duration
        dur_sec = calculate_composition_duration(comp_doc)

    tot_sec = int(round(dur_sec))
    tot_min_part = tot_sec // 60
    tot_sec_part = tot_sec % 60
    time_antic = _ascii_to_antic(f"TIME:    00:00 / {tot_min_part:02d}:{tot_sec_part:02d}")
    num_steps = len(comp_doc.sequence)
    step_antic = _ascii_to_antic(f"STEP:    00 / {num_steps:02d}")

    # Generate self-contained assembly source
    asm_lines = [
        f"PLAYER_ZP_BASE = ${zp_base:02x}",
        f"zp_scr_ptr     = PLAYER_ZP_BASE + 10",
        f"    org {player_addr_str}",
        "",
        "harness_start:",
        "    ; Initialize graphical screen UI if OS screen is active",
        "    lda $59",
        "    beq @no_init_screen",
        "    jsr init_screen_layout",
        "@no_init_screen:",
        "",
        "    cli",
        "    lda #$40",
        "    sta $D40E                   ; NMIEN",
        "    ldx #<song_data",
        "    ldy #>song_data",
        "    jsr music_init",
        "    jsr music_play",
        "",
        "main_loop:",
        "    lda $14",
        "@wait_vblank:",
        "    cmp $14",
        "    beq @wait_vblank",
        "    lda $02FC",
        "    cmp #$FF",
        "    beq @no_key",
        "    pha",
        "    lda #$FF",
        "    sta $02FC",
        "    pla",
        "    jsr music_is_playing",
        "    bne @do_stop",
        "    jsr music_play",
        "    jmp @no_key",
        "@do_stop:",
        "    jsr music_stop",
        "@no_key:",
        "    jsr music_update",
        "",
        "    ; Update graphical timer, pattern step, and VU visualizer",
        "    lda $59",
        "    beq @skip_ui",
        "    jsr update_screen_ui",
        "@skip_ui:",
        "    jmp main_loop",
        "",
        "; =============================================================================",
        "; Graphical Screen UI & Timer",
        "; =============================================================================",
        "init_screen_layout:",
        "    lda $58",
        "    sta zp_scr_ptr",
        "    lda $59",
        "    sta zp_scr_ptr + 1",
        "    lda #0",
        "    ldy #0",
        "@clr_p0:",
        "    sta (zp_scr_ptr),y",
        "    iny",
        "    bne @clr_p0",
        "    inc zp_scr_ptr + 1",
        "@clr_p1:",
        "    sta (zp_scr_ptr),y",
        "    iny",
        "    bne @clr_p1",
        "    inc zp_scr_ptr + 1",
        "@clr_p2:",
        "    sta (zp_scr_ptr),y",
        "    iny",
        "    cpy #208                    ; 256 + 256 + 208 = 720 bytes (18 text lines)",
        "    bne @clr_p2",
        "",
        "    ; Draw top border (row 0)",
        "    ldx #0",
        "    jsr get_row_ptr",
        "    ldy #0",
        "    lda #13                     ; '-' in ANTIC",
        "@draw_h0:",
        "    sta (zp_scr_ptr),y",
        "    iny",
        "    cpy #40",
        "    bne @draw_h0",
        "",
        "    ; Draw Header Text (row 1, col 8)",
        "    ldx #1",
        "    jsr get_row_ptr",
        "    ldy #8",
        "    ldx #0",
        "@pr_head:",
        "    lda header_text,x",
        "    cmp #$FF",
        "    beq @pr_head_done",
        "    sta (zp_scr_ptr),y",
        "    iny",
        "    inx",
        "    bne @pr_head",
        "@pr_head_done:",
        "",
        "    ; Draw Title (row 3, col 2)",
        "    ldx #3",
        "    jsr get_row_ptr",
        "    ldy #2",
        "    ldx #0",
        "@pr_tlabel:",
        "    lda lbl_title,x",
        "    cmp #$FF",
        "    beq @pr_tlabel_done",
        "    sta (zp_scr_ptr),y",
        "    iny",
        "    inx",
        "    bne @pr_tlabel",
        "@pr_tlabel_done:",
        "    ldx #0",
        "@pr_tstr:",
        "    lda song_title_str,x",
        "    cmp #$FF",
        "    beq @pr_tstr_done",
        "    sta (zp_scr_ptr),y",
        "    iny",
        "    inx",
        "    bne @pr_tstr",
        "@pr_tstr_done:",
        "",
        "    ; Draw Tempo (row 4, col 2)",
        "    ldx #4",
        "    jsr get_row_ptr",
        "    ldy #2",
        "    ldx #0",
        "@pr_tempo:",
        "    lda lbl_tempo,x",
        "    cmp #$FF",
        "    beq @pr_tempo_done",
        "    sta (zp_scr_ptr),y",
        "    iny",
        "    inx",
        "    bne @pr_tempo",
        "@pr_tempo_done:",
        "",
        "    ; Draw Status Label (row 6, col 2)",
        "    ldx #6",
        "    jsr get_row_ptr",
        "    ldy #2",
        "    ldx #0",
        "@pr_stat:",
        "    lda lbl_status,x",
        "    cmp #$FF",
        "    beq @pr_stat_done",
        "    sta (zp_scr_ptr),y",
        "    iny",
        "    inx",
        "    bne @pr_stat",
        "@pr_stat_done:",
        "",
        "    ; Draw Time Label (row 7, col 2)",
        "    ldx #7",
        "    jsr get_row_ptr",
        "    ldy #2",
        "    ldx #0",
        "@pr_time:",
        "    lda lbl_time,x",
        "    cmp #$FF",
        "    beq @pr_time_done",
        "    sta (zp_scr_ptr),y",
        "    iny",
        "    inx",
        "    bne @pr_time",
        "@pr_time_done:",
        "",
        "    ; Draw Step Label (row 8, col 2)",
        "    ldx #8",
        "    jsr get_row_ptr",
        "    ldy #2",
        "    ldx #0",
        "@pr_step:",
        "    lda lbl_step,x",
        "    cmp #$FF",
        "    beq @pr_step_done",
        "    sta (zp_scr_ptr),y",
        "    iny",
        "    inx",
        "    bne @pr_step",
        "@pr_step_done:",
        "",
        "    ; Draw Channel Visualizer Boxes (rows 10..13)",
        "    lda #0",
        "    sta ui_cur_ch",
        "@draw_ch_labels:",
        "    ldx ui_cur_ch",
        "    txa",
        "    clc",
        "    adc #10",
        "    tax",
        "    jsr get_row_ptr",
        "    ldy #2",
        "    lda #35             ; 'C'",
        "    sta (zp_scr_ptr),y",
        "    iny",
        "    lda #40             ; 'H'",
        "    sta (zp_scr_ptr),y",
        "    iny",
        "    lda ui_cur_ch",
        "    clc",
        "    adc #$11            ; '1' + ch",
        "    sta (zp_scr_ptr),y",
        "    iny",
        "    lda #26             ; ':'",
        "    sta (zp_scr_ptr),y",
        "    iny",
        "    lda #0              ; ' '",
        "    sta (zp_scr_ptr),y",
        "    iny",
        "    lda #59             ; '['",
        "    sta (zp_scr_ptr),y",
        "    iny",
        "    lda #13             ; '-'",
        "    ldy #8",
        "@pr_dashes:",
        "    sta (zp_scr_ptr),y",
        "    iny",
        "    cpy #24",
        "    bne @pr_dashes",
        "    lda #61             ; ']'",
        "    sta (zp_scr_ptr),y",
        "    inc ui_cur_ch",
        "    lda ui_cur_ch",
        "    cmp #4",
        "    bne @draw_ch_labels",
        "    lda #0",
        "    sta ui_cur_ch",
        "",
        "    ; Draw Footer (row 15, col 4)",
        "    ldx #15",
        "    jsr get_row_ptr",
        "    ldy #4",
        "    ldx #0",
        "@pr_foot:",
        "    lda lbl_footer,x",
        "    cmp #$FF",
        "    beq @pr_foot_done",
        "    sta (zp_scr_ptr),y",
        "    iny",
        "    inx",
        "    bne @pr_foot",
        "@pr_foot_done:",
        "    rts",
        "",
        "update_screen_ui:",
        "    ; 1. Update Timer frames/sec/min if music is playing",
        "    jsr music_is_playing",
        "    beq @draw_status_paused",
        "",
        "    inc ui_timer_frames",
        "    lda ui_timer_frames",
        "    cmp #50",
        "    bne @draw_status_playing",
        "    lda #0",
        "    sta ui_timer_frames",
        "    inc ui_timer_sec",
        "    lda ui_timer_sec",
        "    cmp #60",
        "    bne @draw_status_playing",
        "    lda #0",
        "    sta ui_timer_sec",
        "    inc ui_timer_min",
        "",
        "@draw_status_playing:",
        "    ldx #6",
        "    jsr get_row_ptr",
        "    ldy #11",
        "    ldx #0",
        "@pr_play_txt:",
        "    lda txt_playing,x",
        "    cmp #$FF",
        "    beq @done_status",
        "    sta (zp_scr_ptr),y",
        "    iny",
        "    inx",
        "    bne @pr_play_txt",
        "    jmp @done_status",
        "",
        "@draw_status_paused:",
        "    ldx #6",
        "    jsr get_row_ptr",
        "    ldy #11",
        "    ldx #0",
        "@pr_pause_txt:",
        "    lda txt_paused,x",
        "    cmp #$FF",
        "    beq @done_status",
        "    sta (zp_scr_ptr),y",
        "    iny",
        "    inx",
        "    bne @pr_pause_txt",
        "",
        "@done_status:",
        "    ; 2. Draw Elapsed Time MM:SS at row 7, col 11",
        "    ldx #7",
        "    jsr get_row_ptr",
        "    lda ui_timer_min",
        "    jsr convert_2digit",
        "    ldy #11",
        "    txa",
        "    sta (zp_scr_ptr),y",
        "    iny",
        "    lda ui_digit_lo",
        "    sta (zp_scr_ptr),y",
        "    iny",
        "    lda #26             ; ':'",
        "    sta (zp_scr_ptr),y",
        "    iny",
        "    lda ui_timer_sec",
        "    jsr convert_2digit",
        "    txa",
        "    sta (zp_scr_ptr),y",
        "    iny",
        "    lda ui_digit_lo",
        "    sta (zp_scr_ptr),y",
        "",
        "    ; 3. Draw Step Index at row 8, col 11",
        "    ldx #8",
        "    jsr get_row_ptr",
        "    lda seq_step_idx",
        "    lsr                 ; seq_step_idx / 2 = current pattern step",
        "    jsr convert_2digit",
        "    ldy #11",
        "    txa",
        "    sta (zp_scr_ptr),y",
        "    iny",
        "    lda ui_digit_lo",
        "    sta (zp_scr_ptr),y",
        "",
        "    ; 4. Draw VU meters (rows 10..13, cols 8..23)",
        "    lda #0",
        "    sta ui_cur_ch",
        "@vu_ch_loop:",
        "    lda ui_cur_ch",
        "    clc",
        "    adc #10",
        "    tax",
        "    jsr get_row_ptr     ; zp_scr_ptr = row 10 + channel",
        "",
        "    ldx ui_cur_ch",
        "    lda ch_cur_vol,x    ; Volume 0..15",
        "    sta ui_temp_vol     ; Save volume count",
        "",
        "    ldy #8              ; Screen col 8 (start of meter inside '[')",
        "@vu_bars_on:",
        "    lda ui_temp_vol",
        "    beq @vu_bars_off",
        "    lda #$80            ; Solid block (inverted space)",
        "    sta (zp_scr_ptr),y",
        "    iny",
        "    dec ui_temp_vol",
        "    cpy #24             ; Max 16 bars (cols 8..23)",
        "    bne @vu_bars_on",
        "    jmp @vu_ch_done",
        "",
        "@vu_bars_off:",
        "    cpy #24",
        "    beq @vu_ch_done",
        "    lda #13             ; '-' in ANTIC",
        "    sta (zp_scr_ptr),y",
        "    iny",
        "    jmp @vu_bars_off",
        "",
        "@vu_ch_done:",
        "    inc ui_cur_ch",
        "    lda ui_cur_ch",
        "    cmp #4",
        "    bne @vu_ch_loop",
        "    lda #0",
        "    sta ui_cur_ch",
        "    rts",
        "",
        "convert_2digit:",
        "    ldx #$10            ; '0' in ANTIC",
        "@div10:",
        "    cmp #10",
        "    bcc @done10",
        "    sec",
        "    sbc #10",
        "    inx",
        "    jmp @div10",
        "@done10:",
        "    clc",
        "    adc #$10            ; '0' + remainder",
        "    sta ui_digit_lo",
        "    rts",
        "",
        "get_row_ptr:",
        "    clc",
        "    lda $58",
        "    adc screen_row_lo,x",
        "    sta zp_scr_ptr",
        "    lda $59",
        "    adc screen_row_hi,x",
        "    sta zp_scr_ptr + 1",
        "    rts",
        "",
        "screen_row_lo:",
        "    .byte <0, <40, <80, <120, <160, <200, <240, <280, <320, <360, <400, <440, <480, <520, <560, <600",
        "screen_row_hi:",
        "    .byte >0, >40, >80, >120, >160, >200, >240, >280, >320, >360, >400, >440, >480, >520, >560, >600",
        "",
        "header_text:",
        "    .byte $21, $34, $21, $32, $29, $00, $30, $2f, $2b, $25, $39, $00, $2d, $35, $33, $29, $23, $00, $30, $2c, $21, $39, $25, $32, $ff",
        "",
        "lbl_title:",
        "    .byte $34, $29, $34, $2c, $25, $1a, $00, $00, $00, $ff",
        "",
        f"song_title_str:",
        f"    .byte {', '.join(f'${b:02x}' for b in title_antic)}, $ff",
        "",
        f"lbl_tempo:",
        f"    .byte {', '.join(f'${b:02x}' for b in tempo_antic)}, $ff",
        "",
        "lbl_status:",
        "    .byte $33, $34, $21, $34, $35, $33, $1a, $00, $00, $ff",
        "",
        f"lbl_time:",
        f"    .byte {', '.join(f'${b:02x}' for b in time_antic)}, $ff",
        "",
        f"lbl_step:",
        f"    .byte {', '.join(f'${b:02x}' for b in step_antic)}, $ff",
        "",
        "txt_playing:",
        "    .byte $3b, $30, $2c, $21, $39, $29, $2e, $27, $3d, $ff",
        "",
        "txt_paused:",
        "    .byte $3b, $30, $21, $35, $33, $25, $24, $00, $3d, $ff",
        "",
        "lbl_footer:",
        "    .byte $3b, $33, $30, $21, $23, $25, $00, $0f, $00, $2b, $25, $39, $3d, $00, $30, $2c, $21, $39, $0f, $30, $21, $35, $33, $25, $00, $2d, $35, $33, $29, $23, $ff",
        "",
        "ui_timer_frames: .byte 0",
        "ui_timer_sec:    .byte 0",
        "ui_timer_min:    .byte 0",
        "ui_digit_lo:     .byte 0",
        "ui_cur_ch:       .byte 0",
        "ui_temp_vol:     .byte 0",
        "",
        f"    icl '{player_asm_path.as_posix()}'",
        "",
    ]

    if music_addr_str:
        asm_lines.append(f"    org {music_addr_str}")

    asm_lines.append(song_asm)
    asm_lines.append("")
    asm_lines.append("    run harness_start")
    asm_lines.append("")

    asm_content = "\n".join(asm_lines)

    # Temporary assembly file
    temp_asm = out_p.with_suffix(".asm")
    temp_asm.write_text(asm_content, encoding="utf-8")

    # Run MADS
    cmd = [str(mads_exe), str(temp_asm), f"-o:{out_p}"]
    proc = subprocess.run(cmd, capture_output=True, text=True)

    if proc.returncode != 0:
        raise MusicCompositionError(
            f"MADS compilation failed (exit code {proc.returncode}):\nSTDOUT: {proc.stdout}\nSTDERR: {proc.stderr}"
        )

    return out_p

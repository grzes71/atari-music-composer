"""High-level Client and Pipeline Facade for AI Music Composition."""

from __future__ import annotations

import json
import logging
from pathlib import Path
import subprocess
import time
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
    AIProviderAPIError,
    CompositionAttempt,
    MusicCompositionError,
    ValidationReport,
)
from atari_music.ai.dsl import DSLSyntaxError, export_music_dsl, parse_music_dsl
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


def load_composition(
    source: Union[str, Path, Dict[str, Any], AICompositionDoc],
    format: Optional[str] = None,
) -> AICompositionDoc:
    """Load and validate an AI Composition document from file, string, dict, or instance.

    Supports both canonical JSON and Music DSL.
    If format is omitted, inspects file extension or delegates to JSON parser.

    Parameters
    ----------
    source : Union[str, Path, Dict[str, Any], AICompositionDoc]
        Path to file (.json or .dsl), raw string, parsed dictionary, or doc instance.
    format : Optional[str]
        Explicit format: 'json' or 'dsl'. If None, detected by file extension or tried as JSON.

    Returns
    -------
    AICompositionDoc
        Fully validated canonical composition document.
    """
    if isinstance(source, AICompositionDoc):
        return source

    if isinstance(source, dict):
        return validate_composition(source)

    if isinstance(source, Path) or (isinstance(source, str) and len(source) < 512 and Path(source).is_file()):
        p = Path(source)
        fmt = (format or "").lower()
        text = p.read_text(encoding="utf-8")
        if fmt == "dsl":
            doc = parse_music_dsl(text)
            return validate_composition(doc)
        elif fmt == "json":
            return load_composition_json(text)
        else:
            # Format not specified: detect by content without relying on file extension
            stripped = text.strip()
            if stripped.startswith("{"):
                return load_composition_json(text)
            else:
                doc = parse_music_dsl(text)
                return validate_composition(doc)

    # Raw string
    fmt = (format or "").lower()
    if fmt == "dsl":
        doc = parse_music_dsl(source)
        return validate_composition(doc)
    elif fmt == "json":
        return load_composition_json(source)
    else:
        stripped = str(source).strip()
        if stripped.startswith("{"):
            return load_composition_json(source)
        else:
            doc = parse_music_dsl(source)
            return validate_composition(doc)


def load_composition_dsl(source: Union[str, Path]) -> AICompositionDoc:
    """Load and validate an AI Composition document strictly from Music DSL source.
    
    Parameters
    ----------
    source : Union[str, Path]
        Path to .dsl file or raw Music DSL text string.
        
    Returns
    -------
    AICompositionDoc
        Fully validated canonical composition document.
    """
    if isinstance(source, Path) or (isinstance(source, str) and len(source) < 512 and Path(source).is_file()):
        text = Path(source).read_text(encoding="utf-8")
    else:
        text = str(source)
    doc = parse_music_dsl(text)
    return validate_composition(doc)


def generate_music_from_dsl(dsl_source: Union[str, Path]) -> MusicGenerationResult:
    """Compile a Music DSL source string or file directly through the generation pipeline."""
    doc = load_composition_dsl(dsl_source)
    return generate_music_from_composition(doc)


def generate_music_from_composition(
    composition: Union[AICompositionDoc, Dict[str, Any], str, Path],
) -> MusicGenerationResult:
    """Execute the complete translation pipeline: AI Composition -> Music IR -> POKEY IR -> Result.
    
    Parameters
    ----------
    composition : Union[AICompositionDoc, Dict[str, Any], str, Path]
        The composition document to process (AICompositionDoc, Dict, or file/string path).
        
    Returns
    -------
    MusicGenerationResult
        Standard result object containing Music IR, POKEY IR, and export methods (render_wav, save_json).
    """
    if not isinstance(composition, AICompositionDoc):
        doc = load_composition(composition)
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
    return_history: bool = False,
) -> Union[AICompositionDoc, Tuple[AICompositionDoc, List[CompositionAttempt]]]:
    """Generate and validate an AI composition using an iterative repair loop with feedback.
    
    Attempts up to 1 + max_retries generations (default: 1 initial + 3 retries = max 4 attempts).
    If validation fails, the structured validation report is formatted into feedback
    and sent back to the provider along with the previous invalid composition.
    Supports both canonical JSON and Music DSL modes based on request.format.
    
    Parameters
    ----------
    request : CompositionRequest
        High-level musical request parameters.
    provider : AICompositionProvider
        AI provider backend to query (Mock or OpenAI).
    max_retries : int, default=3
        Maximum retry attempts after initial failure. Must be >= 0.
    return_history : bool, default=False
        If True, return tuple of (validated_doc, history).
        
    Returns
    -------
    AICompositionDoc or Tuple[AICompositionDoc, List[CompositionAttempt]]
        Fully validated composition document (and attempt history if requested).
        
    Raises
    ------
    AICompositionGenerationError
        If validation errors cannot be resolved after max_retries retries.
    """
    max_attempts = 1 + max(0, max_retries)
    history: list[CompositionAttempt] = []
    feedback: Optional[str] = None
    previous_composition: Optional[Dict[str, Any]] = None
    previous_dsl: Optional[str] = None
    is_dsl_mode = (getattr(request, "format", "json") or "json").lower() == "dsl"

    for attempt_idx in range(1, max_attempts + 1):
        attempt_start_time = time.perf_counter()
        logger.debug(
            "Composition Repair Loop: starting attempt %d/%d (max_retries=%d, format=%s)",
            attempt_idx,
            max_attempts,
            max_retries,
            "dsl" if is_dsl_mode else "json",
        )

        # 1. Ask provider for composition (with feedback/context if retrying)
        try:
            if is_dsl_mode:
                if not hasattr(provider, "generate_composition_dsl"):
                    raise MusicCompositionError(
                        f"Provider '{type(provider).__name__}' does not support Music DSL generation."
                    )
                raw_dsl = provider.generate_composition_dsl(
                    request,
                    feedback=feedback,
                    previous_dsl=previous_dsl,
                )
            else:
                raw_dict = provider.generate_composition(
                    request,
                    feedback=feedback,
                    previous_composition=previous_composition,
                )
        except AIProviderAPIError as api_err:
            from atari_music.ai.providers.openai import _is_transient_http_error, extract_retry_delay
            is_trans, code, desc = _is_transient_http_error(api_err)
            if is_trans and attempt_idx < max_attempts:
                base_delay = 5.0 * (2 ** (attempt_idx - 1))
                delay = extract_retry_delay(api_err, default_backoff=base_delay)
                source = "server retryDelay" if delay != base_delay else "exponential backoff"
                logger.warning(
                    "Composition Repair Loop: Transient API error [%s / code %s] on attempt %d: %s. "
                    "Waiting %.1fs (%s) before retrying attempt...",
                    desc,
                    code,
                    attempt_idx,
                    api_err,
                    delay,
                    source,
                )
                time.sleep(delay)
                continue
            raise

        p_name = getattr(provider, "provider_name", type(provider).__name__)

        if is_dsl_mode:
            logger.debug(
                "Received raw DSL payload from provider '%s' (attempt %d, length: %d chars)",
                p_name,
                attempt_idx,
                len(raw_dsl),
            )
            # Try parsing DSL
            try:
                doc = parse_music_dsl(raw_dsl, validate=False)
                report = validate_composition_report(doc)
                raw_dict_for_history = doc.model_dump(mode="json")
            except DSLSyntaxError as syn_err:
                report = ValidationReport(valid=False, issues=[])
                report.add_issue(
                    category="schema",
                    code="DSL_SYNTAX_ERROR",
                    message=f"DSL syntax error on line {syn_err.line_number}:{syn_err.column or 1}: {syn_err.message} (Line content: {syn_err.line_text!r})",
                    path=f"line_{syn_err.line_number}",
                    details={"line": syn_err.line_number, "col": syn_err.column, "snippet": syn_err.line_text},
                )
                raw_dict_for_history = {"raw_dsl": raw_dsl}
            except Exception as parse_err:
                report = ValidationReport(valid=False, issues=[])
                report.add_issue(
                    category="schema",
                    code="DSL_PARSE_ERROR",
                    message=f"DSL parsing failed: {parse_err}",
                    path="<root>",
                    details={"error": str(parse_err)},
                )
                raw_dict_for_history = {"raw_dsl": raw_dsl}

            attempt_wall_ms = round((time.perf_counter() - attempt_start_time) * 1000.0, 2)
            attempt_record = CompositionAttempt(
                attempt_number=attempt_idx,
                composition=raw_dict_for_history,
                report=report,
                usage=getattr(provider, "last_usage", None),
                wall_time_ms=attempt_wall_ms,
            )
            history.append(attempt_record)

            if report.valid:
                logger.debug(
                    "DSL Composition validation PASSED on attempt %d (0 issues). Proceeding with validated composition.",
                    attempt_idx,
                )
                valid_doc = validate_composition(doc)
                if return_history:
                    return valid_doc, history
                return valid_doc

            issues_summary = [f"[{i.category.upper()}] {i.code}: {i.message}" for i in report.issues]
            logger.debug(
                "DSL Composition validation FAILED on attempt %d with %d issue(s): %s",
                attempt_idx,
                len(report.issues),
                "; ".join(issues_summary),
            )

            feedback = report.format_feedback()
            previous_dsl = raw_dsl
            previous_composition = raw_dict_for_history

        else:
            raw_keys = list(raw_dict.keys()) if isinstance(raw_dict, dict) else []
            logger.debug(
                "Received raw composition payload from provider '%s' (attempt %d, top-level keys: %s)",
                p_name,
                attempt_idx,
                raw_keys,
            )

            # 2. Run full 3-Tier validation report
            report = validate_composition_report(raw_dict)
            attempt_wall_ms = round((time.perf_counter() - attempt_start_time) * 1000.0, 2)
            attempt_record = CompositionAttempt(
                attempt_number=attempt_idx,
                composition=raw_dict,
                report=report,
                usage=getattr(provider, "last_usage", None),
                wall_time_ms=attempt_wall_ms,
            )
            history.append(attempt_record)

            # 3. Check validity
            if report.valid:
                logger.debug(
                    "Composition validation PASSED on attempt %d (0 issues). Proceeding with validated composition.",
                    attempt_idx,
                )
                valid_doc = validate_composition(raw_dict)
                if return_history:
                    return valid_doc, history
                return valid_doc

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
    format: Optional[str] = None,
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
    format : Optional[str]
        Explicit composition format override: 'json' or 'dsl'.
        
    Returns
    -------
    AICompositionDoc
        Validated composition document.
    """
    if format:
        request.format = format.lower()
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
    format: Optional[str] = None,
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
    format : Optional[str]
        Optional explicit format: 'json' or 'dsl'.
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
    if "format" in kwargs and format is None:
        format = kwargs["format"]

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

    if not isinstance(composition, AICompositionDoc):
        comp_doc = load_composition(composition, format=format)
    else:
        comp_doc = composition

    res = generate_music_from_composition(comp_doc)
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

    title_str = (comp_doc.metadata.title or "POKEY Music")[:28]
    title_antic = _ascii_to_antic(f"TITLE:   {title_str}")
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
        f"zp_str_ptr     = PLAYER_ZP_BASE + 12",
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
        "    and #$3F",
        "    ldx #3",
        "@chk_k:",
        "    cmp key_table,x",
        "    beq @toggle_m",
        "    dex",
        "    bpl @chk_k",
        "    cmp #$21                    ; Key 'Space'",
        "    bne @no_key",
        "    jsr music_is_playing",
        "    bne @do_stop",
        "    jsr music_play",
        "    jmp @no_key",
        "@do_stop:",
        "    jsr music_stop",
        "    jmp @no_key",
        "@toggle_m:",
        "    lda ch_mute_mask,x",
        "    eor #1",
        "    sta ch_mute_mask,x",
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
        "    ; Set dark green background ($C4) and border ($C4)",
        "    lda #$C4",
        "    sta $02C6                   ; COLOR2 (Playfield 2 / text background)",
        "    sta $02C8                   ; COLOR4 (Background / border)",
        "    sta $D018                   ; COLPF2 (GTIA immediate)",
        "    sta $D01A                   ; COLBK (GTIA immediate)",
        "    lda #$0E",
        "    sta $02C5                   ; COLOR1 (Text luminance)",
        "    sta $D017                   ; COLPF1 (GTIA immediate)",
        "",
        "    ; Clear screen (768 bytes)",
        "    lda $58",
        "    sta zp_scr_ptr",
        "    lda $59",
        "    sta zp_scr_ptr + 1",
        "    lda #0",
        "    tax",
        "    ldy #0",
        "@clr_scr:",
        "    sta (zp_scr_ptr),y",
        "    iny",
        "    bne @clr_scr",
        "    inc zp_scr_ptr + 1",
        "    inx",
        "    cpx #3",
        "    bne @clr_scr",
        "",
        "    ; Draw top border (row 0)",
        "    ldx #0",
        "    ldy #0",
        "    jsr get_cell_ptr",
        "    ldy #39",
        "    lda #13                     ; '-' in ANTIC",
        "@draw_h0:",
        "    sta (zp_scr_ptr),y",
        "    dey",
        "    bpl @draw_h0",
        "",
        "    ; Draw Header Text (row 1, col 8)",
        "    ldx #1",
        "    ldy #8",
        "    jsr get_cell_ptr",
        "    lda #<header_text",
        "    sta zp_str_ptr",
        "    lda #>header_text",
        "    sta zp_str_ptr + 1",
        "    jsr print_string",
        "",
        "    ; Draw Title (row 3, col 2)",
        "    ldx #3",
        "    ldy #2",
        "    jsr get_cell_ptr",
        "    lda #<lbl_title",
        "    sta zp_str_ptr",
        "    lda #>lbl_title",
        "    sta zp_str_ptr + 1",
        "    jsr print_string",
        "",
        "    ; Draw Tempo (row 4, col 2)",
        "    ldx #4",
        "    ldy #2",
        "    jsr get_cell_ptr",
        "    lda #<lbl_tempo",
        "    sta zp_str_ptr",
        "    lda #>lbl_tempo",
        "    sta zp_str_ptr + 1",
        "    jsr print_string",
        "",
        "    ; Draw Status Label (row 6, col 2)",
        "    ldx #6",
        "    ldy #2",
        "    jsr get_cell_ptr",
        "    lda #<lbl_status",
        "    sta zp_str_ptr",
        "    lda #>lbl_status",
        "    sta zp_str_ptr + 1",
        "    jsr print_string",
        "",
        "    ; Draw Time Label (row 7, col 2)",
        "    ldx #7",
        "    ldy #2",
        "    jsr get_cell_ptr",
        "    lda #<lbl_time",
        "    sta zp_str_ptr",
        "    lda #>lbl_time",
        "    sta zp_str_ptr + 1",
        "    jsr print_string",
        "",
        "    ; Draw Step Label (row 8, col 2)",
        "    ldx #8",
        "    ldy #2",
        "    jsr get_cell_ptr",
        "    lda #<lbl_step",
        "    sta zp_str_ptr",
        "    lda #>lbl_step",
        "    sta zp_str_ptr + 1",
        "    jsr print_string",
        "",
        "    ; Draw Channel Visualizer Boxes (rows 10..13)",
        "    lda #0",
        "    sta ui_cur_ch",
        "@draw_ch_boxes:",
        "    ldx ui_cur_ch",
        "    txa",
        "    clc",
        "    adc #10",
        "    tax",
        "    ldy #2",
        "    jsr get_cell_ptr",
        "    lda #<template_ch",
        "    sta zp_str_ptr",
        "    lda #>template_ch",
        "    sta zp_str_ptr + 1",
        "    jsr print_string",
        "    ldy #2",
        "    lda ui_cur_ch",
        "    clc",
        "    adc #$11            ; '1' + ch",
        "    sta (zp_scr_ptr),y",
        "    inc ui_cur_ch",
        "    lda ui_cur_ch",
        "    cmp #4",
        "    bne @draw_ch_boxes",
        "    lda #0",
        "    sta ui_cur_ch",
        "",
        "    ; Draw Footer (row 15, col 3)",
        "    ldx #15",
        "    ldy #3",
        "    jsr get_cell_ptr",
        "    lda #<lbl_footer",
        "    sta zp_str_ptr",
        "    lda #>lbl_footer",
        "    sta zp_str_ptr + 1",
        "    jsr print_string",
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
        "    lda #<txt_playing",
        "    sta zp_str_ptr",
        "    lda #>txt_playing",
        "    sta zp_str_ptr + 1",
        "    jmp @pr_status",
        "",
        "@draw_status_paused:",
        "    lda #<txt_paused",
        "    sta zp_str_ptr",
        "    lda #>txt_paused",
        "    sta zp_str_ptr + 1",
        "",
        "@pr_status:",
        "    ldx #6",
        "    ldy #11",
        "    jsr get_cell_ptr",
        "    jsr print_string",
        "",
        "    ; 2. Draw Elapsed Time MM:SS at row 7, col 11",
        "    ldx #7",
        "    ldy #11",
        "    jsr get_cell_ptr",
        "    lda ui_timer_min",
        "    jsr convert_2digit",
        "    ldy #0",
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
        "    ldy #11",
        "    jsr get_cell_ptr",
        "    lda seq_step_idx",
        "    lsr                 ; seq_step_idx / 2 = current pattern step",
        "    jsr convert_2digit",
        "    ldy #0",
        "    txa",
        "    sta (zp_scr_ptr),y",
        "    iny",
        "    lda ui_digit_lo",
        "    sta (zp_scr_ptr),y",
        "",
        "    ; 4. Draw VU meters and ON/OFF status (rows 10..13)",
        "    lda #0",
        "    sta ui_cur_ch",
        "@vu_ch_loop:",
        "    ldx ui_cur_ch",
        "    txa",
        "    clc",
        "    adc #10",
        "    tax",
        "    ldy #0",
        "    jsr get_cell_ptr    ; zp_scr_ptr = start of channel row",
        "",
        "    ldx ui_cur_ch",
        "    lda ch_mute_mask,x",
        "    beq @vu_ch_active",
        "",
        "    ; Channel is muted: zero volume, draw 'OFF'",
        "    lda #0",
        "    sta ui_temp_vol",
        "    ldy #26",
        "    lda #$2F            ; 'O'",
        "    sta (zp_scr_ptr),y",
        "    iny",
        "    lda #$26            ; 'F'",
        "    sta (zp_scr_ptr),y",
        "    iny",
        "    lda #$26            ; 'F'",
        "    sta (zp_scr_ptr),y",
        "    jmp @vu_draw_bars",
        "",
        "@vu_ch_active:",
        "    lda ch_cur_vol,x    ; Volume 0..15",
        "    sta ui_temp_vol",
        "    ldy #26",
        "    lda #$2F            ; 'O'",
        "    sta (zp_scr_ptr),y",
        "    iny",
        "    lda #$2E            ; 'N'",
        "    sta (zp_scr_ptr),y",
        "    iny",
        "    lda #0              ; ' '",
        "    sta (zp_scr_ptr),y",
        "",
        "@vu_draw_bars:",
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
        "get_cell_ptr:",
        "    tya",
        "    clc",
        "    adc $58",
        "    adc screen_row_lo,x",
        "    sta zp_scr_ptr",
        "    lda $59",
        "    adc screen_row_hi,x",
        "    sta zp_scr_ptr + 1",
        "    rts",
        "",
        "print_string:",
        "    ldy #0",
        "@pr_str_loop:",
        "    lda (zp_str_ptr),y",
        "    cmp #$FF",
        "    beq @pr_str_done",
        "    sta (zp_scr_ptr),y",
        "    iny",
        "    bne @pr_str_loop",
        "@pr_str_done:",
        "    rts",
        "",
        "key_table:       .byte $1F, $1E, $1A, $18",
        "",
        "template_ch:",
        "    .byte $23, $28, $11, $1A, 0, $3B, 13, 13, 13, 13, 13, 13, 13, 13, 13, 13, 13, 13, 13, 13, 13, 13, $3D, 0, $2F, $2E, 0, $FF",
        "",
        "screen_row_lo:",
        "    .byte <0, <40, <80, <120, <160, <200, <240, <280, <320, <360, <400, <440, <480, <520, <560, <600",
        "screen_row_hi:",
        "    .byte >0, >40, >80, >120, >160, >200, >240, >280, >320, >360, >400, >440, >480, >520, >560, >600",
        "",
        "header_text:",
        "    .byte $21, $34, $21, $32, $29, $00, $30, $2f, $2b, $25, $39, $00, $2d, $35, $33, $29, $23, $00, $30, $2c, $21, $39, $25, $32, $ff",
        "",
        f"lbl_title:",
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
        "    .byte $3b, $11, $0d, $14, $3d, $00, $2d, $35, $34, $25, $00, $23, $28, $00, $00, $00, $3b, $33, $30, $21, $23, $25, $3d, $00, $30, $2c, $21, $39, $0f, $30, $21, $35, $33, $25, $ff",
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

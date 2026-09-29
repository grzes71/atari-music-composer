"""Music DSL (Domain Specific Language) for Atari 8-bit POKEY Music Generation.

Provides a compact, human- and LLM-friendly textual representation of chiptune
music that compiles directly into the canonical ``AICompositionDoc`` schema.
Also provides a lossless exporter from ``AICompositionDoc`` to Music DSL.

Pipeline:
    Music DSL -> parse_music_dsl() -> AICompositionDoc -> validate_composition()
    AICompositionDoc -> export_music_dsl() -> Music DSL
"""

from __future__ import annotations

import re
import shlex
from typing import Any, Dict, List, Optional, Set, Tuple

from atari_music.ai.schema import (
    AICompositionDoc,
    AICompositionMetadata,
    AIHardwareConfig,
    AIInstrumentDef,
    AIPatternChannelEvent,
    AIPatternDef,
    MusicCompositionError,
)
from atari_music.ai.validation import normalize_channel_idx, validate_composition
from atari_music.ir import note_name_to_midi


# =============================================================================
# DSL Exceptions
# =============================================================================

class DSLSyntaxError(MusicCompositionError):
    """Syntax or grammatical error in Music DSL input."""

    def __init__(
        self,
        message: str,
        line_number: int,
        column: Optional[int] = None,
        line_text: Optional[str] = None,
    ) -> None:
        self.message = message
        self.line_number = line_number
        self.column = column
        self.line_text = line_text
        col_part = f", col {column}" if column is not None else ""
        text_part = f"\n  > {line_text}" if line_text else ""
        super().__init__(f"Line {line_number}{col_part}: {message}{text_part}")


# =============================================================================
# Helper Regex & Timbre Resolution
# =============================================================================

# Matches note tokens like C4/4, D#2/8, Bb3/16, R/4, -/4, C4/4:12, H4/4
NOTE_TOKEN_RE = re.compile(
    r"^(?P<pitch>[A-Za-z0-9#b\-]+)"
    r"(?:/(?P<dur>\d+))?"
    r"(?::(?P<vol>\d+))?$"
)

# Matches pattern headers like [PATTERN A1], [A1], [PATTERN A1 length=32 role=theme]
PATTERN_HEADER_RE = re.compile(r"^\[(?:PATTERN\s+)?(?P<id>[A-Za-z0-9_]+)(?P<params>.*)\]$")

# Matches channel lines like CH1 LEAD V14 or CH2 BASS
CHANNEL_HEADER_RE = re.compile(
    r"^CH(?P<ch>[1-4])(?:\s+(?P<inst>[A-Za-z0-9_]+))?(?:\s+[Vv](?P<vol>\d+))?$"
)


def _infer_character_from_id(inst_id: str) -> str:
    """Infer semantic instrument archetype from identifier string."""
    name = inst_id.strip().lower()
    if any(k in name for k in ("kick", "tom", "thud")):
        return "kick"
    if any(k in name for k in ("perc", "drum", "snare", "hihat", "noise", "hat", "cymbal", "clap")):
        return "percussion"
    if "bass" in name:
        return "bass"
    if any(k in name for k in ("pad", "dark", "drone")):
        return "dark_lead"
    if any(k in name for k in ("harm", "chord", "counter")):
        return "harmony"
    if any(k in name for k in ("bell", "ornament", "arp", "high")):
        return "bell"
    return "bright_lead"


# =============================================================================
# Parser: DSL -> AICompositionDoc
# =============================================================================

def parse_music_dsl(text: str, validate: bool = True) -> AICompositionDoc:
    """Parse a Music DSL text document into an ``AICompositionDoc``.

    Parameters
    ----------
    text : str
        Music DSL text source.
    validate : bool, default=True
        Whether to run canonical 3-tier validation before returning.

    Returns
    -------
    AICompositionDoc
        Canonical composition document.

    Raises
    ------
    DSLSyntaxError
        On syntax, lexical, or structural parsing failures.
    MusicCompositionError
        On downstream validation errors (if validate=True).
    """
    raw_lines = text.splitlines()

    title: str = "POKEY Music"
    author: str = "AI Composer"
    key: str = "C"
    mode: str = "minor"
    bpm: int = 120
    channels_count: int = 4
    use_16bit_bass: bool = False
    loop_point: int = 0
    sequence: List[str] = []
    instruments_dict: Dict[str, AIInstrumentDef] = {}

    # State tracking
    patterns: List[AIPatternDef] = []
    current_pat_id: Optional[str] = None
    current_pat_length: Optional[int] = None
    current_pat_role: Optional[str] = None
    current_pat_channels: Dict[str, List[AIPatternChannelEvent]] = {}
    current_channel_num: Optional[int] = None
    current_channel_inst: Optional[str] = None
    current_channel_vol: int = 14
    current_channel_step: int = 0
    channel_total_durations: Dict[int, int] = {}

    def _flush_current_pattern(line_no: int) -> None:
        nonlocal current_pat_id, current_pat_length, current_pat_role
        nonlocal current_pat_channels, channel_total_durations
        if current_pat_id is None:
            return

        # Determine length_steps deterministically
        if current_pat_length is not None:
            final_len = current_pat_length
        else:
            if channel_total_durations:
                final_len = max(channel_total_durations.values())
            else:
                final_len = 16
            if final_len <= 0:
                final_len = 16

        # Check if events exceed explicit length
        for ch_key, ev_list in current_pat_channels.items():
            for ev in ev_list:
                if ev.step + ev.duration > final_len:
                    if current_pat_length is not None:
                        raise DSLSyntaxError(
                            f"Pattern '{current_pat_id}' channel {ch_key} events extend to step "
                            f"{ev.step + ev.duration}, exceeding explicit length={final_len}",
                            line_number=line_no,
                        )
                    else:
                        final_len = ev.step + ev.duration

        # Ensure all channels up to channels_count exist in dict
        for c in range(1, channels_count + 1):
            c_str = str(c)
            if c_str not in current_pat_channels:
                current_pat_channels[c_str] = []

        patterns.append(
            AIPatternDef(
                id=current_pat_id,
                length_steps=final_len,
                channels=current_pat_channels,
                role=current_pat_role,
            )
        )
        current_pat_id = None
        current_pat_length = None
        current_pat_role = None
        current_pat_channels = {}
        channel_total_durations = {}

    for line_idx, raw_line in enumerate(raw_lines, start=1):
        line = raw_line.strip()
        # Strip comments (only '#' preceded by whitespace or at start of line, so musical sharps like C#4 or D#2 are preserved)
        if "#" in line:
            in_quote = False
            comment_pos = -1
            for pos, ch in enumerate(line):
                if ch in ('"', "'"):
                    in_quote = not in_quote
                elif ch == "#" and not in_quote and (pos == 0 or line[pos - 1].isspace()):
                    comment_pos = pos
                    break
            if comment_pos != -1:
                line = line[:comment_pos].strip()

        if not line:
            continue

        # Check for Pattern Header [PATTERN <id> ...]
        if line.startswith("[") and line.endswith("]"):
            _flush_current_pattern(line_idx)
            current_channel_num = None
            m = PATTERN_HEADER_RE.match(line)
            if not m:
                raise DSLSyntaxError(f"Malformed pattern header: '{line}'", line_number=line_idx, line_text=raw_line)
            pat_id = m.group("id")
            params_str = m.group("params").strip()
            explicit_len = None
            pat_role = None

            if params_str:
                for token in params_str.split():
                    if "=" in token:
                        k, v = token.split("=", 1)
                        k = k.lower().strip()
                        v = v.strip()
                        if k in ("len", "length", "length_steps"):
                            try:
                                explicit_len = int(v)
                                if explicit_len < 1:
                                    raise ValueError()
                            except ValueError:
                                raise DSLSyntaxError(
                                    f"Invalid pattern length '{v}', must be an integer >= 1",
                                    line_number=line_idx,
                                    line_text=raw_line,
                                )
                        elif k in ("role", "type"):
                            pat_role = v.lower()
                    else:
                        raise DSLSyntaxError(
                            f"Unexpected token in pattern header: '{token}'",
                            line_number=line_idx,
                            line_text=raw_line,
                        )

            current_pat_id = pat_id
            current_pat_length = explicit_len
            current_pat_role = pat_role
            current_pat_channels = {}
            channel_total_durations = {}
            continue

        # Check for Channel Header: CH<1..4> [INST] [V<vol>]
        upper_tokens = line.split()
        first_token = upper_tokens[0].upper()
        if re.match(r"^CH[1-4]$", first_token):
            if current_pat_id is None:
                raise DSLSyntaxError(
                    f"Channel '{first_token}' defined outside of any [PATTERN ...]",
                    line_number=line_idx,
                    line_text=raw_line,
                )
            ch_num = int(first_token[2:])
            current_channel_num = ch_num
            current_channel_step = 0

            # Default instrument and volume
            inst_name = f"ch{ch_num}"
            vol = 14

            # Inspect remaining tokens on the channel line
            note_tokens: List[str] = []
            parsing_header = True

            for tok in upper_tokens[1:]:
                if parsing_header:
                    if tok.upper().startswith("V") and tok[1:].isdigit():
                        vol = int(tok[1:])
                        if not (0 <= vol <= 15):
                            raise DSLSyntaxError(
                                f"Volume {vol} out of range [0..15]",
                                line_number=line_idx,
                                line_text=raw_line,
                            )
                    elif "/" in tok:
                        parsing_header = False
                        note_tokens.append(tok)
                    else:
                        inst_name = tok.lower()
                else:
                    note_tokens.append(tok)

            current_channel_inst = inst_name
            current_channel_vol = vol

            ch_str = str(ch_num)
            if ch_str not in current_pat_channels:
                current_pat_channels[ch_str] = []

            # Parse any note tokens that appeared on the channel line
            for n_tok in note_tokens:
                nm = NOTE_TOKEN_RE.match(n_tok)
                if not nm:
                    raise DSLSyntaxError(
                        f"Malformed note token '{n_tok}'",
                        line_number=line_idx,
                        line_text=raw_line,
                    )
                pitch_raw = nm.group("pitch").upper()
                dur_str = nm.group("dur")
                vol_str = nm.group("vol")

                if dur_str is None:
                    raise DSLSyntaxError(
                        f"Missing duration in note '{n_tok}' (expected format e.g. D4/4)",
                        line_number=line_idx,
                        line_text=raw_line,
                    )
                try:
                    dur = int(dur_str)
                    if dur < 1:
                        raise ValueError()
                except ValueError:
                    raise DSLSyntaxError(
                        f"Invalid duration in note '{n_tok}', must be an integer >= 1",
                        line_number=line_idx,
                        line_text=raw_line,
                    )

                note_vol = int(vol_str) if vol_str is not None else current_channel_vol
                if not (0 <= note_vol <= 15):
                    raise DSLSyntaxError(
                        f"Note volume {note_vol} out of range [0..15] in '{n_tok}'",
                        line_number=line_idx,
                        line_text=raw_line,
                    )

                is_rest = pitch_raw in ("R", "REST", "-", "OFF", "SIL")
                if is_rest:
                    ev_note = "REST"
                    ev_vol = 0
                else:
                    # Validate scientific pitch
                    if note_name_to_midi(pitch_raw) is None:
                        raise DSLSyntaxError(
                            f"Invalid note pitch '{pitch_raw}' in '{n_tok}'. Expected format e.g. C4, D#3, Bb2, or R",
                            line_number=line_idx,
                            line_text=raw_line,
                        )
                    ev_note = pitch_raw.capitalize() if len(pitch_raw) == 2 else pitch_raw[0].upper() + pitch_raw[1:].lower()
                    ev_vol = note_vol

                ev = AIPatternChannelEvent(
                    step=current_channel_step,
                    note=ev_note,
                    instrument=current_channel_inst,
                    duration=dur,
                    volume=ev_vol,
                )
                current_pat_channels[ch_str].append(ev)
                current_channel_step += dur
                channel_total_durations[ch_num] = current_channel_step

            continue

        # If inside a channel, additional lines are note tokens
        if current_channel_num is not None:
            # Check if this line is another directive instead of note tokens
            directive_match = re.match(r"^[A-Za-z_]+", line)
            is_directive = False
            if directive_match:
                word = directive_match.group(0).upper()
                if word in ("TITLE", "AUTHOR", "KEY", "MODE", "BPM", "CHANNELS", "BASS", "BASS16", "LOOP", "SEQUENCE", "FORM", "INSTRUMENT"):
                    is_directive = True

            if not is_directive:
                ch_str = str(current_channel_num)
                for n_tok in line.split():
                    nm = NOTE_TOKEN_RE.match(n_tok)
                    if not nm:
                        raise DSLSyntaxError(
                            f"Malformed note token '{n_tok}'",
                            line_number=line_idx,
                            line_text=raw_line,
                        )
                    pitch_raw = nm.group("pitch").upper()
                    dur_str = nm.group("dur")
                    vol_str = nm.group("vol")

                    if dur_str is None:
                        raise DSLSyntaxError(
                            f"Missing duration in note '{n_tok}' (expected format e.g. D4/4)",
                            line_number=line_idx,
                            line_text=raw_line,
                        )
                    try:
                        dur = int(dur_str)
                        if dur < 1:
                            raise ValueError()
                    except ValueError:
                        raise DSLSyntaxError(
                            f"Invalid duration in note '{n_tok}', must be an integer >= 1",
                            line_number=line_idx,
                            line_text=raw_line,
                        )

                    note_vol = int(vol_str) if vol_str is not None else current_channel_vol
                    if not (0 <= note_vol <= 15):
                        raise DSLSyntaxError(
                            f"Note volume {note_vol} out of range [0..15] in '{n_tok}'",
                            line_number=line_idx,
                            line_text=raw_line,
                        )

                    is_rest = pitch_raw in ("R", "REST", "-", "OFF", "SIL")
                    if is_rest:
                        ev_note = "REST"
                        ev_vol = 0
                    else:
                        if note_name_to_midi(pitch_raw) is None:
                            raise DSLSyntaxError(
                                f"Invalid note pitch '{pitch_raw}' in '{n_tok}'. Expected format e.g. C4, D#3, Bb2, or R",
                                line_number=line_idx,
                                line_text=raw_line,
                            )
                        ev_note = pitch_raw.capitalize() if len(pitch_raw) == 2 else pitch_raw[0].upper() + pitch_raw[1:].lower()
                        ev_vol = note_vol

                    ev = AIPatternChannelEvent(
                        step=current_channel_step,
                        note=ev_note,
                        instrument=current_channel_inst or f"ch{current_channel_num}",
                        duration=dur,
                        volume=ev_vol,
                    )
                    current_pat_channels[ch_str].append(ev)
                    current_channel_step += dur
                    channel_total_durations[current_channel_num] = current_channel_step
                continue

        # Top-Level Directives
        # Use shlex to handle quoted arguments
        try:
            tokens = shlex.split(line)
        except ValueError as err:
            raise DSLSyntaxError(f"Lexical error: {err}", line_number=line_idx, line_text=raw_line)

        directive = tokens[0].upper()
        args = tokens[1:]

        if directive == "TITLE":
            if not args:
                raise DSLSyntaxError("TITLE directive requires a string argument", line_number=line_idx, line_text=raw_line)
            title = args[0]
        elif directive == "AUTHOR":
            if not args:
                raise DSLSyntaxError("AUTHOR directive requires a string argument", line_number=line_idx, line_text=raw_line)
            author = args[0]
        elif directive == "KEY":
            if not args:
                raise DSLSyntaxError("KEY directive requires a root key (e.g. C, D, F#)", line_number=line_idx, line_text=raw_line)
            key = args[0].upper()
        elif directive == "MODE":
            if not args:
                raise DSLSyntaxError("MODE directive requires a scale mode (e.g. minor, major)", line_number=line_idx, line_text=raw_line)
            mode = args[0].lower()
        elif directive == "BPM":
            if not args or not args[0].isdigit():
                raise DSLSyntaxError("BPM directive requires an integer tempo (40..250)", line_number=line_idx, line_text=raw_line)
            bpm_val = int(args[0])
            if not (40 <= bpm_val <= 250):
                raise DSLSyntaxError(f"BPM {bpm_val} out of range [40..250]", line_number=line_idx, line_text=raw_line)
            bpm = bpm_val
        elif directive == "CHANNELS":
            if not args or not args[0].isdigit():
                raise DSLSyntaxError("CHANNELS directive requires an integer (1..4)", line_number=line_idx, line_text=raw_line)
            ch_val = int(args[0])
            if not (1 <= ch_val <= 4):
                raise DSLSyntaxError(f"Channels {ch_val} out of range [1..4]", line_number=line_idx, line_text=raw_line)
            channels_count = ch_val
        elif directive in ("BASS", "BASS16"):
            if directive == "BASS16":
                use_16bit_bass = True
            elif args and args[0].upper() in ("16", "16BIT", "TRUE", "YES", "ON"):
                use_16bit_bass = True
            elif args and args[0].upper() in ("8", "8BIT", "FALSE", "NO", "OFF"):
                use_16bit_bass = False
            else:
                use_16bit_bass = True
        elif directive == "LOOP":
            if not args or not args[0].isdigit():
                raise DSLSyntaxError("LOOP directive requires an integer sequence step (>= 0)", line_number=line_idx, line_text=raw_line)
            loop_point = int(args[0])
        elif directive in ("SEQUENCE", "FORM"):
            if not args:
                raise DSLSyntaxError(f"{directive} requires at least one pattern identifier", line_number=line_idx, line_text=raw_line)
            sequence = list(args)
        elif directive == "INSTRUMENT":
            # INSTRUMENT <id> [character=<name>] [dist=<hex|int>] [att=<int>] [dec=<int>] [sus=<int>] [rel=<int>]
            if not args:
                raise DSLSyntaxError("INSTRUMENT directive requires an instrument ID", line_number=line_idx, line_text=raw_line)
            inst_id = args[0].lower()
            name_val: Optional[str] = None
            char = _infer_character_from_id(inst_id)
            dist_val: Optional[int] = None
            att_val: Optional[int] = None
            dec_val: Optional[int] = None
            sus_val: Optional[int] = None
            rel_val: Optional[int] = None

            for param in args[1:]:
                if "=" in param:
                    pk, pv = param.split("=", 1)
                    pk = pk.lower().strip()
                    pv = pv.strip().strip('"\'')
                    if pk in ("name", "title"):
                        name_val = pv
                    elif pk in ("char", "character"):
                        char = pv.lower()
                    elif pk in ("dist", "distortion"):
                        try:
                            dist_val = int(pv[1:], 16) if pv.startswith("$") else (int(pv, 16) if pv.lower().startswith("0x") else int(pv))
                        except ValueError:
                            raise DSLSyntaxError(f"Invalid distortion value '{pv}'", line_number=line_idx, line_text=raw_line)
                    elif pk in ("att", "attack"):
                        att_val = int(pv)
                    elif pk in ("dec", "decay"):
                        dec_val = int(pv)
                    elif pk in ("sus", "sustain"):
                        sus_val = int(pv)
                    elif pk in ("rel", "release"):
                        rel_val = int(pv)
                    else:
                        raise DSLSyntaxError(f"Unknown instrument parameter '{pk}'", line_number=line_idx, line_text=raw_line)
                else:
                    raise DSLSyntaxError(f"Expected key=value parameter in INSTRUMENT, got '{param}'", line_number=line_idx, line_text=raw_line)

            instruments_dict[inst_id] = AIInstrumentDef(
                id=inst_id,
                name=name_val or inst_id.capitalize(),
                character=char,
                distortion=dist_val,
                attack_frames=att_val,
                decay_frames=dec_val,
                sustain_vol=sus_val,
                release_frames=rel_val,
            )
        else:
            raise DSLSyntaxError(f"Unknown directive '{directive}'", line_number=line_idx, line_text=raw_line)

    # Flush last pattern
    _flush_current_pattern(len(raw_lines) + 1)

    if not patterns:
        raise DSLSyntaxError("No patterns defined in Music DSL document", line_number=1)

    if not sequence:
        # Default sequence: list all unique pattern IDs in order of declaration
        sequence = [p.id for p in patterns]

    # Auto-synthesize default instruments for any referenced instrument ID missing from instruments_dict
    for pat in patterns:
        for ch_key, ev_list in pat.channels.items():
            for ev in ev_list:
                iid = ev.instrument
                if iid not in instruments_dict:
                    char = _infer_character_from_id(iid)
                    instruments_dict[iid] = AIInstrumentDef(
                        id=iid,
                        name=iid.capitalize(),
                        character=char,
                    )

    if not instruments_dict:
        instruments_dict["lead"] = AIInstrumentDef(id="lead", name="Lead", character="bright_lead")

    metadata = AICompositionMetadata(
        title=title,
        author=author,
        key=key,
        mode=mode,
        bpm=bpm,
    )
    hardware = AIHardwareConfig(
        channels=channels_count,
        use_16bit_bass=use_16bit_bass,
    )

    doc = AICompositionDoc(
        format="atari-music-composition",
        version=1,
        metadata=metadata,
        hardware=hardware,
        instruments=list(instruments_dict.values()),
        patterns=patterns,
        sequence=sequence,
        loop_point=loop_point,
    )

    if validate:
        return validate_composition(doc)
    return doc


# =============================================================================
# Exporter: AICompositionDoc -> DSL
# =============================================================================

def export_music_dsl(doc: AICompositionDoc) -> str:
    """Serialize an ``AICompositionDoc`` into compact, readable Music DSL text.

    Parameters
    ----------
    doc : AICompositionDoc
        Canonical composition document.

    Returns
    -------
    str
        Formatted Music DSL string.
    """
    lines: List[str] = []

    # 1. Global Directives
    lines.append(f'TITLE "{doc.metadata.title}"')
    if doc.metadata.author and doc.metadata.author != "AI Composer":
        lines.append(f'AUTHOR "{doc.metadata.author}"')
    lines.append(f"KEY {doc.metadata.key}")
    lines.append(f"MODE {doc.metadata.mode.upper()}")
    lines.append(f"BPM {doc.metadata.bpm}")
    if doc.hardware.channels != 4:
        lines.append(f"CHANNELS {doc.hardware.channels}")
    if doc.hardware.use_16bit_bass:
        lines.append("BASS 16BIT")
    if doc.loop_point != 0:
        lines.append(f"LOOP {doc.loop_point}")

    lines.append("")
    lines.append(f"SEQUENCE {' '.join(doc.sequence)}")
    lines.append("")

    # 2. Instruments
    if doc.instruments:
        for inst in doc.instruments:
            parts = [f"INSTRUMENT {inst.id}"]
            if inst.name and inst.name != inst.id.capitalize():
                parts.append(f'name="{inst.name}"')
            parts.append(f"character={inst.character}")
            if inst.distortion is not None:
                parts.append(f"dist=${inst.distortion:02x}")
            if inst.attack_frames is not None:
                parts.append(f"att={inst.attack_frames}")
            if inst.decay_frames is not None:
                parts.append(f"dec={inst.decay_frames}")
            if inst.sustain_vol is not None:
                parts.append(f"sus={inst.sustain_vol}")
            if inst.release_frames is not None:
                parts.append(f"rel={inst.release_frames}")
            lines.append(" ".join(parts))
        lines.append("")

    # 3. Patterns
    has_zero = any(
        any(str(k).strip() == "0" for k in pat.channels.keys())
        for pat in doc.patterns
    )

    for pat in doc.patterns:
        header_parts = [f"[PATTERN {pat.id}"]
        # Include length parameter if needed
        header_parts.append(f"length={pat.length_steps}")
        if pat.role:
            header_parts.append(f"role={pat.role}")
        header_line = " ".join(header_parts) + "]"
        lines.append(header_line)

        # Sort channels 1..4
        norm_ch_map: Dict[int, List[AIPatternChannelEvent]] = {}
        for ch_key, ev_list in pat.channels.items():
            ch_idx = normalize_channel_idx(ch_key, has_zero=has_zero)
            norm_ch_map[ch_idx] = sorted(ev_list, key=lambda e: e.step)

        for ch_idx in range(1, 5):
            events = norm_ch_map.get(ch_idx, [])
            if not events:
                continue

            # Determine dominant instrument and default volume
            inst_name = events[0].instrument
            # Find most common volume among non-rest events
            active_vols = [e.volume for e in events if e.volume is not None and e.note and e.note.upper() not in ("REST", "---", "OFF")]
            default_vol = active_vols[0] if active_vols else 14

            ch_header = f"CH{ch_idx} {inst_name} V{default_vol}"
            lines.append(ch_header)

            # Generate note tokens, inserting rests for gaps
            note_tokens: List[str] = []
            current_step = 0

            for ev in events:
                # Fill any step gap before this event with a Rest
                if ev.step > current_step:
                    gap = ev.step - current_step
                    note_tokens.append(f"R/{gap}")
                    current_step = ev.step

                is_rest = (ev.note is None) or str(ev.note).upper() in ("---", "REST", "OFF", "SIL", "")
                if is_rest:
                    note_tokens.append(f"R/{ev.duration}")
                else:
                    token = f"{ev.note}/{ev.duration}"
                    if ev.volume is not None and ev.volume != default_vol:
                        token += f":{ev.volume}"
                    note_tokens.append(token)
                current_step += ev.duration

            # If total channel length is less than pattern length, append trailing rest
            if current_step < pat.length_steps:
                trailing = pat.length_steps - current_step
                note_tokens.append(f"R/{trailing}")

            # Format note tokens wrapped nicely
            line_buf: List[str] = []
            for tok in note_tokens:
                line_buf.append(tok)
                if len(" ".join(line_buf)) >= 60:
                    lines.append(" ".join(line_buf))
                    line_buf = []
            if line_buf:
                lines.append(" ".join(line_buf))

            lines.append("")

    return "\n".join(lines).rstrip() + "\n"

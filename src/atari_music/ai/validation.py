"""Three-Tier Validation Engine for AI Music Compositions.

Validation Tiers:
1. Schema Validation (MusicCompositionSchemaError): JSON types, required fields, format/version.
2. Musical Validation (MusicCompositionValidationError): Notes, duration, steps, IDs, sequence, loop point.
3. Hardware Validation (MusicIRValidationError): POKEY limits (4 channels, 16-bit bass pairing, volume 0..15).
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Set, Union
from pydantic import ValidationError

from atari_music.ai.schema import (
    AICompositionDoc,
    MusicCompositionSchemaError,
    MusicCompositionValidationError,
    MusicIRValidationError,
    ValidationIssue,
    ValidationReport,
)
from atari_music.ir import note_name_to_midi


# =============================================================================
# Machine-Readable Error Codes
# =============================================================================

SCHEMA_JSON_DECODE = "SCHEMA_JSON_DECODE"
SCHEMA_INVALID_TYPE = "SCHEMA_INVALID_TYPE"
SCHEMA_MISSING_FIELD = "SCHEMA_MISSING_FIELD"
SCHEMA_VALIDATION_ERROR = "SCHEMA_VALIDATION_ERROR"

EMPTY_SEQUENCE = "EMPTY_SEQUENCE"
NO_PATTERNS = "NO_PATTERNS"
UNKNOWN_PATTERN = "UNKNOWN_PATTERN"
INVALID_LOOP_POINT = "INVALID_LOOP_POINT"
INVALID_PATTERN_LENGTH = "INVALID_PATTERN_LENGTH"
INVALID_CHANNEL_IDENTIFIER = "INVALID_CHANNEL_IDENTIFIER"
INVALID_STEP = "INVALID_STEP"
INVALID_DURATION = "INVALID_DURATION"
UNKNOWN_INSTRUMENT = "UNKNOWN_INSTRUMENT"
INVALID_NOTE = "INVALID_NOTE"
NOTE_OVERLAP = "NOTE_OVERLAP"

POKEY_CHANNEL_LIMIT = "POKEY_CHANNEL_LIMIT"
INVALID_DISTORTION = "INVALID_DISTORTION"
CHANNEL_OUT_OF_RANGE = "CHANNEL_OUT_OF_RANGE"
VOLUME_OUT_OF_RANGE = "VOLUME_OUT_OF_RANGE"
BASS16_CHANNEL_CONFLICT = "BASS16_CHANNEL_CONFLICT"



# =============================================================================
# Helper Normalization
# =============================================================================

def normalize_channel_idx(ch_key: Union[int, str], has_zero: bool = False) -> int:
    """Normalize channel key (0..3 or 1..4, str or int) to 1-based index (1..4)."""
    try:
        val = int(str(ch_key).strip())
    except ValueError:
        raise MusicCompositionValidationError(
            f"Invalid channel identifier '{ch_key}'. Expected integer 0..3 or 1..4."
        )

    if val == 0:
        return 1
    elif val in (1, 2, 3):
        return (val + 1) if has_zero else val
    elif val == 4:
        return 4
    else:
        raise MusicIRValidationError(
            f"Channel '{ch_key}' (parsed as {val}) is out of POKEY hardware bounds. Allowed channels are 0..3 or 1..4 (max 4 channels)."
        )


# =============================================================================
# Level 1: Schema Validation
# =============================================================================

def validate_schema(data: Union[Dict[str, Any], str, AICompositionDoc]) -> AICompositionDoc:
    """Level 1 Validation: Verify JSON schema structure, required fields, and data types.
    
    Raises
    ------
    MusicCompositionSchemaError
        If schema structure, format tag, or data types are invalid.
    """
    if isinstance(data, AICompositionDoc):
        return data

    if isinstance(data, str):
        try:
            parsed = json.loads(data)
        except json.JSONDecodeError as err:
            raise MusicCompositionSchemaError(f"Malformed JSON syntax: {err}") from err
    elif isinstance(data, dict):
        parsed = data
    else:
        raise MusicCompositionSchemaError(f"Expected dict, JSON string or AICompositionDoc, got {type(data).__name__}")

    if not isinstance(parsed, dict):
        raise MusicCompositionSchemaError(f"Root JSON document must be an object/dict, got {type(parsed).__name__}")

    # Check mandatory top-level keys
    for req_field in ("format", "version", "metadata", "patterns", "sequence"):
        if req_field not in parsed:
            raise MusicCompositionSchemaError(
                f"Missing required top-level field '{req_field}' in composition document."
            )

    try:
        doc = AICompositionDoc.model_validate(parsed)
    except ValidationError as err:
        # Format detailed error message
        errors = err.errors()
        err_msgs = []
        for e in errors:
            loc = " -> ".join(str(x) for x in e.get("loc", []))
            msg = e.get("msg", "invalid")
            val = e.get("input", None)
            err_msgs.append(f"Field '{loc}': {msg} (received: {val!r})")
        raise MusicCompositionSchemaError(
            f"Schema validation failed ({len(errors)} error(s)):\n  - " + "\n  - ".join(err_msgs)
        ) from err

    return doc


# =============================================================================
# Level 2: Musical Validation
# =============================================================================

def validate_musical(doc: AICompositionDoc) -> None:
    """Level 2 Validation: Verify musical grammar, consistency of IDs, steps, notes, and sequence.
    
    Raises
    ------
    MusicCompositionValidationError
        If notes, durations, steps, instrument IDs, pattern IDs or sequence references are invalid.
    """
    # 1. Instruments index
    known_instrument_ids: Set[str] = {inst.id for inst in doc.instruments}
    if not known_instrument_ids:
        # Default fallback if empty
        known_instrument_ids.add("lead")

    # 2. Sequence consistency
    if not doc.sequence:
        raise MusicCompositionValidationError("Sequence cannot be empty. Must contain at least one pattern identifier.")

    pattern_map: Dict[str, Any] = {pat.id: pat for pat in doc.patterns}
    if not pattern_map:
        raise MusicCompositionValidationError("Document contains no patterns.")

    for seq_idx, pat_id in enumerate(doc.sequence):
        if pat_id not in pattern_map:
            raise MusicCompositionValidationError(
                f"Sequence step {seq_idx} references undefined pattern '{pat_id}'. Available patterns: {sorted(pattern_map.keys())}"
            )

    # 2b. Form plan consistency (if provided)
    if doc.form_plan and doc.form_plan.sections:
        for sec_idx, sec in enumerate(doc.form_plan.sections):
            if sec.pattern_id not in pattern_map:
                raise MusicCompositionValidationError(
                    f"Form plan section {sec_idx} ('{sec.section_id}') references undefined pattern '{sec.pattern_id}'. Available patterns: {sorted(pattern_map.keys())}"
                )
            if sec.variation_of and sec.variation_of not in pattern_map:
                raise MusicCompositionValidationError(
                    f"Form plan section {sec_idx} ('{sec.section_id}') specifies variation_of='{sec.variation_of}', but base pattern is undefined."
                )

    # 3. Loop point
    if doc.loop_point < 0 or doc.loop_point >= len(doc.sequence):
        raise MusicCompositionValidationError(
            f"Invalid loop_point {doc.loop_point}. Must be within sequence bounds [0, {len(doc.sequence) - 1}]."
        )

    # 4. Pattern validation
    for pat in doc.patterns:
        if pat.length_steps <= 0:
            raise MusicCompositionValidationError(
                f"[Pattern '{pat.id}']: Invalid length_steps {pat.length_steps}. Must be >= 1."
            )

        has_zero = any(str(k).strip() == "0" for k in pat.channels.keys())
        for ch_key, events in pat.channels.items():
            ch_idx = normalize_channel_idx(ch_key, has_zero=has_zero)

            # Check individual events
            last_step = -1
            for ev_idx, ev in enumerate(events):
                # Step range
                if ev.step < 0 or ev.step >= pat.length_steps:
                    raise MusicCompositionValidationError(
                        f"[Pattern '{pat.id}', Channel {ch_idx}, Event {ev_idx}]: Step {ev.step} is out of bounds [0, {pat.length_steps - 1}]."
                    )

                # Duration
                if ev.duration < 1:
                    raise MusicCompositionValidationError(
                        f"[Pattern '{pat.id}', Channel {ch_idx}, Step {ev.step}]: Duration {ev.duration} is invalid. Must be >= 1."
                    )

                # Instrument existence
                if ev.instrument not in known_instrument_ids:
                    raise MusicCompositionValidationError(
                        f"[Pattern '{pat.id}', Channel {ch_idx}, Step {ev.step}]: Event references undefined instrument '{ev.instrument}'. Defined instruments: {sorted(known_instrument_ids)}"
                    )

                # Note pitch validity
                if ev.note is not None and str(ev.note).upper() not in ("---", "REST", "OFF", "SIL", ""):
                    midi_val = note_name_to_midi(str(ev.note))
                    if midi_val is None:
                        raise MusicCompositionValidationError(
                            f"[Pattern '{pat.id}', Channel {ch_idx}, Step {ev.step}]: Invalid note pitch '{ev.note}'. Expected valid note name (e.g. 'C4', 'A#2', 'Eb3') or 'REST'."
                        )

            # Monophonic voice conflict / overlap check (POKEY channels are strictly monophonic)
            active_events = [
                ev for ev in events
                if ev.note is not None and str(ev.note).upper() not in ("---", "REST", "OFF", "SIL", "")
            ]
            active_events.sort(key=lambda e: (e.step, -e.duration))
            for i in range(len(active_events)):
                n1 = active_events[i]
                n1_end = n1.step + n1.duration
                for j in range(i + 1, len(active_events)):
                    n2 = active_events[j]
                    if n2.step < n1_end:
                        n2_end = n2.step + n2.duration
                        raise MusicCompositionValidationError(
                            f"Overlapping notes in pattern '{pat.id}', channel {ch_key}: "
                            f"note '{n1.note}' (instrument '{n1.instrument}') at step {n1.step} with duration {n1.duration} [{n1.step}..{n1_end}) overlaps "
                            f"note '{n2.note}' (instrument '{n2.instrument}') at step {n2.step} with duration {n2.duration} [{n2.step}..{n2_end})"
                        )
                    else:
                        break


# =============================================================================
# Level 3: Hardware Validation
# =============================================================================

def validate_hardware(doc: AICompositionDoc) -> None:
    """Level 3 Validation: Verify POKEY hardware limits (channel count, volume, 16-bit bass pairing).
    
    Raises
    ------
    MusicIRValidationError
        If hardware limits (channels > 4, 16-bit bass collision, volume out of range) are violated.
    """
    # 1. Channel count
    if doc.hardware.channels < 1 or doc.hardware.channels > 4:
        raise MusicIRValidationError(
            f"Hardware channel count {doc.hardware.channels} exceeds POKEY physical limits (1..4 channels)."
        )

    # 2. Check distortion across instruments
    valid_distortions = {0, 2, 4, 6, 8, 10, 12, 14, 0x00, 0x20, 0x40, 0x60, 0x80, 0xA0, 0xC0, 0xE0}
    for inst in doc.instruments:
        if inst.distortion is not None and inst.distortion not in valid_distortions:
            raise MusicIRValidationError(
                f"[Instrument '{inst.id}']: Invalid POKEY AUDC distortion {inst.distortion}. "
                f"Allowed distortion values: {sorted(valid_distortions)}"
            )

    # 3. Check channel indices across all patterns
    for pat in doc.patterns:
        has_zero = any(str(k).strip() == "0" for k in pat.channels.keys())
        for ch_key, events in pat.channels.items():
            ch_idx = normalize_channel_idx(ch_key, has_zero=has_zero)
            if ch_idx > doc.hardware.channels:
                raise MusicIRValidationError(
                    f"[Pattern '{pat.id}']: Event on channel {ch_idx} exceeds declared hardware channel count {doc.hardware.channels}."
                )

            # Volume range check
            for ev in events:
                if ev.volume is not None and (ev.volume < 0 or ev.volume > 15):
                    raise MusicIRValidationError(
                        f"[Pattern '{pat.id}', Channel {ch_idx}, Step {ev.step}]: Volume {ev.volume} exceeds POKEY 4-bit volume range [0..15]."
                    )

    # 4. 16-bit bass constraint validation
    if doc.hardware.use_16bit_bass:
        # In POKEY, 16-bit bass couples Channel 1 (low divider) and Channel 2 (high divider & volume).
        # Channel 2 cannot be used for independent melodies while 16-bit bass is active.
        for pat in doc.patterns:
            has_zero = any(str(k).strip() == "0" for k in pat.channels.keys())
            ch1_events = []
            ch2_events = []
            for ch_key, events in pat.channels.items():
                ch_idx = normalize_channel_idx(ch_key, has_zero=has_zero)
                if ch_idx == 1:
                    ch1_events = [e for e in events if e.note and e.note.upper() not in ("---", "REST", "OFF")]
                elif ch_idx == 2:
                    ch2_events = [e for e in events if e.note and e.note.upper() not in ("---", "REST", "OFF")]

            # If Channel 1 has active bass notes, Channel 2 must not have independent melodic notes
            # unless they are explicitly aligned slave notes
            if ch1_events and ch2_events:
                # Check if ch2 events are separate independent notes
                ch1_steps = {e.step for e in ch1_events}
                ch2_steps = {e.step for e in ch2_events}
                independent_steps = ch2_steps - ch1_steps
                if independent_steps:
                    raise MusicIRValidationError(
                        f"[Pattern '{pat.id}']: 16-bit bass collision on paired channels 1 & 2. "
                        f"Channel 2 contains independent active notes at step(s) {sorted(independent_steps)}. "
                        "When use_16bit_bass is enabled, Channel 2 is a hardware frequency slave to Channel 1."
                    )


# =============================================================================
# Structured Validation Report Engine
# =============================================================================

def validate_composition_report(data: Union[Dict[str, Any], str, AICompositionDoc]) -> ValidationReport:
    """Execute complete 3-Tier validation and return a structured ValidationReport.
    
    Collects all detectable issues across schema, musical grammar, and hardware
    constraints in a single structured report for LLM diagnostic feedback.
    
    Parameters
    ----------
    data : Union[Dict[str, Any], str, AICompositionDoc]
        The composition document to validate.
        
    Returns
    -------
    ValidationReport
        Report containing valid boolean flag and list of ValidationIssue instances.
    """
    report = ValidationReport(valid=True, issues=[])

    # -------------------------------------------------------------------------
    # Tier 1: Schema Validation
    # -------------------------------------------------------------------------
    if isinstance(data, AICompositionDoc):
        doc = data
    else:
        if isinstance(data, str):
            try:
                parsed = json.loads(data)
            except json.JSONDecodeError as err:
                report.add_issue(
                    category="schema",
                    code=SCHEMA_JSON_DECODE,
                    message=f"Malformed JSON syntax: {err}",
                    path="<root>",
                    details={"error": str(err)},
                )
                return report
        elif isinstance(data, dict):
            parsed = data
        else:
            report.add_issue(
                category="schema",
                code=SCHEMA_INVALID_TYPE,
                message=f"Expected dict, JSON string or AICompositionDoc, got {type(data).__name__}",
                path="<root>",
                details={"type": type(data).__name__},
            )
            return report

        if not isinstance(parsed, dict):
            report.add_issue(
                category="schema",
                code=SCHEMA_INVALID_TYPE,
                message=f"Root JSON document must be an object/dict, got {type(parsed).__name__}",
                path="<root>",
                details={"type": type(parsed).__name__},
            )
            return report

        missing_fields = [f for f in ("format", "version", "metadata", "patterns", "sequence") if f not in parsed]
        if missing_fields:
            for mf in missing_fields:
                report.add_issue(
                    category="schema",
                    code=SCHEMA_MISSING_FIELD,
                    message=f"Missing required top-level field '{mf}' in composition document.",
                    path=mf,
                    details={"missing_field": mf},
                )
            return report

        try:
            doc = AICompositionDoc.model_validate(parsed)
        except ValidationError as err:
            errors = err.errors()
            for e in errors:
                loc = " -> ".join(str(x) for x in e.get("loc", []))
                msg = e.get("msg", "invalid")
                val = e.get("input", None)
                report.add_issue(
                    category="schema",
                    code=SCHEMA_VALIDATION_ERROR,
                    message=f"Field '{loc}': {msg} (received: {val!r})",
                    path=loc,
                    details={"loc": loc, "msg": msg, "input": val},
                )
            return report

    # -------------------------------------------------------------------------
    # Tier 2: Musical Validation
    # -------------------------------------------------------------------------
    known_instrument_ids: Set[str] = {inst.id for inst in doc.instruments}
    if not known_instrument_ids:
        known_instrument_ids.add("lead")

    if not doc.sequence:
        report.add_issue(
            category="musical",
            code=EMPTY_SEQUENCE,
            message="Sequence cannot be empty. Must contain at least one pattern identifier.",
            path="sequence",
        )

    pattern_map: Dict[str, Any] = {pat.id: pat for pat in doc.patterns}
    if not pattern_map:
        report.add_issue(
            category="musical",
            code=NO_PATTERNS,
            message="Document contains no patterns.",
            path="patterns",
        )

    for seq_idx, pat_id in enumerate(doc.sequence):
        if pat_id not in pattern_map:
            report.add_issue(
                category="musical",
                code=UNKNOWN_PATTERN,
                message=f"Sequence step {seq_idx} references undefined pattern '{pat_id}'. Available patterns: {sorted(pattern_map.keys())}",
                path=f"sequence[{seq_idx}]",
                details={"sequence_step": seq_idx, "pattern_id": pat_id, "available_patterns": sorted(pattern_map.keys())},
            )

    if doc.form_plan and doc.form_plan.sections:
        for sec_idx, sec in enumerate(doc.form_plan.sections):
            sec_path = f"form_plan.sections[{sec_idx}]"
            if sec.pattern_id not in pattern_map:
                report.add_issue(
                    category="musical",
                    code=UNKNOWN_PATTERN,
                    message=f"Form plan section {sec_idx} ('{sec.section_id}') references undefined pattern '{sec.pattern_id}'.",
                    path=f"{sec_path}.pattern_id",
                    details={"section_index": sec_idx, "section_id": sec.section_id, "pattern_id": sec.pattern_id},
                )
            if sec.variation_of and sec.variation_of not in pattern_map:
                report.add_issue(
                    category="musical",
                    code=UNKNOWN_PATTERN,
                    message=f"Form plan section {sec_idx} ('{sec.section_id}') specifies variation_of='{sec.variation_of}', but base pattern is undefined.",
                    path=f"{sec_path}.variation_of",
                    details={"section_index": sec_idx, "section_id": sec.section_id, "variation_of": sec.variation_of},
                )

    if doc.loop_point < 0 or (doc.sequence and doc.loop_point >= len(doc.sequence)):
        report.add_issue(
            category="musical",
            code=INVALID_LOOP_POINT,
            message=f"Invalid loop_point {doc.loop_point}. Must be within sequence bounds [0, {len(doc.sequence) - 1}].",
            path="loop_point",
            details={"loop_point": doc.loop_point, "sequence_length": len(doc.sequence)},
        )

    for pat in doc.patterns:
        pat_path = f"patterns[{pat.id}]"
        if pat.length_steps <= 0:
            report.add_issue(
                category="musical",
                code=INVALID_PATTERN_LENGTH,
                message=f"[Pattern '{pat.id}']: Invalid length_steps {pat.length_steps}. Must be >= 1.",
                path=f"{pat_path}.length_steps",
                details={"pattern": pat.id, "length_steps": pat.length_steps},
            )

        has_zero = any(str(k).strip() == "0" for k in pat.channels.keys())
        for ch_key, events in pat.channels.items():
            try:
                ch_idx = normalize_channel_idx(ch_key, has_zero=has_zero)
            except MusicCompositionValidationError as err:
                report.add_issue(
                    category="musical",
                    code=INVALID_CHANNEL_IDENTIFIER,
                    message=str(err),
                    path=f"{pat_path}.channels[{ch_key}]",
                    details={"pattern": pat.id, "channel": ch_key},
                )
                continue
            except MusicIRValidationError as err:
                report.add_issue(
                    category="hardware",
                    code=CHANNEL_OUT_OF_RANGE,
                    message=str(err),
                    path=f"{pat_path}.channels[{ch_key}]",
                    details={"pattern": pat.id, "channel": ch_key},
                )
                continue

            for ev_idx, ev in enumerate(events):
                ev_path = f"{pat_path}.channels[{ch_key}].events[{ev_idx}]"
                if ev.step < 0 or ev.step >= pat.length_steps:
                    report.add_issue(
                        category="musical",
                        code=INVALID_STEP,
                        message=f"[Pattern '{pat.id}', Channel {ch_idx}, Event {ev_idx}]: Step {ev.step} is out of bounds [0, {pat.length_steps - 1}].",
                        path=f"{ev_path}.step",
                        details={"pattern": pat.id, "channel": ch_key, "event_idx": ev_idx, "step": ev.step, "length_steps": pat.length_steps},
                    )
                if ev.duration < 1:
                    report.add_issue(
                        category="musical",
                        code=INVALID_DURATION,
                        message=f"[Pattern '{pat.id}', Channel {ch_idx}, Step {ev.step}]: Duration {ev.duration} is invalid. Must be >= 1.",
                        path=f"{ev_path}.duration",
                        details={"pattern": pat.id, "channel": ch_key, "step": ev.step, "duration": ev.duration},
                    )
                if ev.instrument not in known_instrument_ids:
                    report.add_issue(
                        category="musical",
                        code=UNKNOWN_INSTRUMENT,
                        message=f"[Pattern '{pat.id}', Channel {ch_idx}, Step {ev.step}]: Event references undefined instrument '{ev.instrument}'. Defined instruments: {sorted(known_instrument_ids)}",
                        path=f"{ev_path}.instrument",
                        details={"pattern": pat.id, "channel": ch_key, "step": ev.step, "instrument": ev.instrument, "defined": sorted(known_instrument_ids)},
                    )
                if ev.note is not None and str(ev.note).upper() not in ("---", "REST", "OFF", "SIL", ""):
                    midi_val = note_name_to_midi(str(ev.note))
                    if midi_val is None:
                        report.add_issue(
                            category="musical",
                            code=INVALID_NOTE,
                            message=f"[Pattern '{pat.id}', Channel {ch_idx}, Step {ev.step}]: Invalid note pitch '{ev.note}'. Expected valid note name (e.g. 'C4', 'A#2', 'Eb3') or 'REST'.",
                            path=f"{ev_path}.note",
                            details={"pattern": pat.id, "channel": ch_key, "step": ev.step, "note": ev.note},
                        )

            # Monophonic voice conflict / overlap check
            active_events = [
                (ev_idx, ev) for ev_idx, ev in enumerate(events)
                if ev.note is not None and str(ev.note).upper() not in ("---", "REST", "OFF", "SIL", "")
            ]
            active_events.sort(key=lambda t: (t[1].step, -t[1].duration))
            for i in range(len(active_events)):
                idx1, n1 = active_events[i]
                n1_end = n1.step + n1.duration
                for j in range(i + 1, len(active_events)):
                    idx2, n2 = active_events[j]
                    if n2.step < n1_end:
                        n2_end = n2.step + n2.duration
                        msg = (
                            f"Overlapping notes in pattern '{pat.id}', channel {ch_key}: "
                            f"note '{n1.note}' (instrument '{n1.instrument}') at step {n1.step} with duration {n1.duration} [{n1.step}..{n1_end}) overlaps "
                            f"note '{n2.note}' (instrument '{n2.instrument}') at step {n2.step} with duration {n2.duration} [{n2.step}..{n2_end})"
                        )
                        report.add_issue(
                            category="musical",
                            code=NOTE_OVERLAP,
                            message=msg,
                            path=f"{pat_path}.channels[{ch_key}].events[{idx2}]",
                            details={
                                "pattern": pat.id,
                                "channel": ch_key,
                                "event": {
                                    "step": n2.step,
                                    "note": n2.note,
                                    "duration": n2.duration,
                                    "instrument": n2.instrument,
                                },
                                "conflicting_event": {
                                    "step": n1.step,
                                    "note": n1.note,
                                    "duration": n1.duration,
                                    "instrument": n1.instrument,
                                },
                            },
                        )
                    else:
                        break

    # -------------------------------------------------------------------------
    # Tier 3: Hardware Validation
    # -------------------------------------------------------------------------
    if doc.hardware.channels < 1 or doc.hardware.channels > 4:
        report.add_issue(
            category="hardware",
            code=POKEY_CHANNEL_LIMIT,
            message=f"Hardware channel count {doc.hardware.channels} exceeds POKEY physical limits (1..4 channels).",
            path="hardware.channels",
            details={"channels": doc.hardware.channels},
        )

    valid_distortions = {0, 2, 4, 6, 8, 10, 12, 14, 0x00, 0x20, 0x40, 0x60, 0x80, 0xA0, 0xC0, 0xE0}
    for inst_idx, inst in enumerate(doc.instruments):
        if inst.distortion is not None and inst.distortion not in valid_distortions:
            report.add_issue(
                category="hardware",
                code=INVALID_DISTORTION,
                message=f"[Instrument '{inst.id}']: Invalid POKEY AUDC distortion {inst.distortion}. Allowed distortion values: {sorted(valid_distortions)}",
                path=f"instruments[{inst_idx}].distortion",
                details={"instrument": inst.id, "distortion": inst.distortion, "allowed": sorted(valid_distortions)},
            )

    for pat in doc.patterns:
        has_zero = any(str(k).strip() == "0" for k in pat.channels.keys())
        for ch_key, events in pat.channels.items():
            try:
                ch_idx = normalize_channel_idx(ch_key, has_zero=has_zero)
            except Exception:
                continue
            if ch_idx > doc.hardware.channels:
                report.add_issue(
                    category="hardware",
                    code=CHANNEL_OUT_OF_RANGE,
                    message=f"[Pattern '{pat.id}']: Event on channel {ch_idx} exceeds declared hardware channel count {doc.hardware.channels}.",
                    path=f"patterns[{pat.id}].channels[{ch_key}]",
                    details={"pattern": pat.id, "channel": ch_idx, "max_channels": doc.hardware.channels},
                )
            for ev_idx, ev in enumerate(events):
                if ev.volume is not None and (ev.volume < 0 or ev.volume > 15):
                    report.add_issue(
                        category="hardware",
                        code=VOLUME_OUT_OF_RANGE,
                        message=f"[Pattern '{pat.id}', Channel {ch_idx}, Step {ev.step}]: Volume {ev.volume} exceeds POKEY 4-bit volume range [0..15].",
                        path=f"patterns[{pat.id}].channels[{ch_key}].events[{ev_idx}].volume",
                        details={"pattern": pat.id, "channel": ch_idx, "step": ev.step, "volume": ev.volume},
                    )

    if doc.hardware.use_16bit_bass:
        for pat in doc.patterns:
            has_zero = any(str(k).strip() == "0" for k in pat.channels.keys())
            ch1_events = []
            ch2_events = []
            for ch_key, events in pat.channels.items():
                try:
                    ch_idx = normalize_channel_idx(ch_key, has_zero=has_zero)
                except Exception:
                    continue
                if ch_idx == 1:
                    ch1_events = [e for e in events if e.note and e.note.upper() not in ("---", "REST", "OFF")]
                elif ch_idx == 2:
                    ch2_events = [e for e in events if e.note and e.note.upper() not in ("---", "REST", "OFF")]
            if ch1_events and ch2_events:
                ch1_steps = {e.step for e in ch1_events}
                ch2_steps = {e.step for e in ch2_events}
                independent_steps = ch2_steps - ch1_steps
                if independent_steps:
                    report.add_issue(
                        category="hardware",
                        code=BASS16_CHANNEL_CONFLICT,
                        message=(
                            f"[Pattern '{pat.id}']: 16-bit bass collision on paired channels 1 & 2. "
                            f"Channel 2 contains independent active notes at step(s) {sorted(independent_steps)}. "
                            "When use_16bit_bass is enabled, Channel 2 is a hardware frequency slave to Channel 1."
                        ),
                        path=f"patterns[{pat.id}].channels",
                        details={"pattern": pat.id, "independent_steps": sorted(independent_steps)},
                    )

    return report


# =============================================================================
# Master Validation Entry Point (Fail-Fast API)
# =============================================================================

def validate_composition(data: Union[Dict[str, Any], str, AICompositionDoc]) -> AICompositionDoc:
    """Execute complete 3-Tier validation on composition document (fail-fast API).
    
    1. Schema validation -> MusicCompositionSchemaError
    2. Musical validation -> MusicCompositionValidationError
    3. Hardware validation -> MusicIRValidationError
    
    Returns
    -------
    AICompositionDoc
        Fully validated document instance.
    """
    report = validate_composition_report(data)
    if not report.valid:
        first_issue = report.issues[0]
        if first_issue.category == "schema":
            exc: Exception = MusicCompositionSchemaError(first_issue.message)
        elif first_issue.category == "hardware":
            exc = MusicIRValidationError(first_issue.message)
        else:
            exc = MusicCompositionValidationError(first_issue.message)
        setattr(exc, "report", report)
        setattr(exc, "issue", first_issue)
        raise exc

    return validate_schema(data)


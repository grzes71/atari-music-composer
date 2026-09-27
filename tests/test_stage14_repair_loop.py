"""Unit and integration tests for Etap 14: LLM Validation Feedback & Composition Repair Loop.

Verifies:
1. ValidationReport and ValidationIssue data structures, stability of error codes, localization (path/details),
   and multiple issue accumulation in a single report pass.
2. Formatted feedback generation with preservation instructions.
3. Iterative repair loop execution (generate_composition_with_retry, request_ai_composition):
   - Immediate success (1 attempt, 0 retries)
   - Invalid then valid (2 attempts, 1 retry)
   - Exhaustion of retry limit (max_retries=3 -> 4 attempts, max_retries=0 -> 1 attempt)
   - Error mutation across attempts (Attempt 1: NOTE_OVERLAP -> Attempt 2: INVALID_NOTE -> Attempt 3: valid)
   - Full re-validation across all tiers on every retry.
4. Requirement 26 canonical scenario (C4 step 0 dur 8 + E4 step 4 dur 4 -> repaired to C4 step 0 dur 4).
5. Provider infrastructure error isolation (authentication / dependency errors not retried as musical errors).
"""

from __future__ import annotations

import copy
import sys
from typing import Any, Dict
import pytest

from atari_music.ai.client import (
    generate_composition_with_retry,
    generate_music_from_composition,
    request_ai_composition,
)
from atari_music.ai.providers.base import CompositionRequest
from atari_music.ai.providers.mock import MockAICompositionProvider
from atari_music.ai.providers.openai import OpenAICompositionProvider
from atari_music.ai.schema import (
    AICompositionDoc,
    AICompositionGenerationError,
    AIProviderMissingKeyError,
    CompositionAttempt,
    MusicCompositionValidationError,
    ValidationIssue,
    ValidationReport,
)
from atari_music.ai.validation import (
    BASS16_CHANNEL_CONFLICT,
    CHANNEL_OUT_OF_RANGE,
    EMPTY_SEQUENCE,
    INVALID_DURATION,
    INVALID_LOOP_POINT,
    INVALID_NOTE,
    INVALID_STEP,
    NOTE_OVERLAP,
    POKEY_CHANNEL_LIMIT,
    SCHEMA_MISSING_FIELD,
    UNKNOWN_INSTRUMENT,
    UNKNOWN_PATTERN,
    VOLUME_OUT_OF_RANGE,
    validate_composition,
    validate_composition_report,
)


@pytest.fixture
def canonical_valid_doc() -> Dict[str, Any]:
    """Return a minimal valid composition document dictionary."""
    return {
        "format": "atari-music-composition",
        "version": 1,
        "metadata": {
            "title": "Repair Test Song",
            "key": "C",
            "mode": "minor",
            "bpm": 120,
        },
        "hardware": {
            "channels": 4,
            "use_16bit_bass": False,
        },
        "instruments": [
            {"id": "lead", "name": "Pulse Lead", "character": "bright_lead"},
            {"id": "bass", "name": "Deep Bass", "character": "bass"},
        ],
        "patterns": [
            {
                "id": "A",
                "length_steps": 16,
                "channels": {
                    "0": [
                        {"step": 0, "note": "C4", "instrument": "lead", "duration": 4, "volume": 14},
                        {"step": 4, "note": "E4", "instrument": "lead", "duration": 4, "volume": 14},
                    ],
                    "1": [
                        {"step": 0, "note": "C2", "instrument": "bass", "duration": 8, "volume": 12},
                    ],
                    "2": [],
                    "3": [],
                },
            }
        ],
        "sequence": ["A"],
        "loop_point": 0,
    }


# =============================================================================
# 1. ValidationReport & ValidationIssue Tests
# =============================================================================

def test_validation_report_on_valid_composition(canonical_valid_doc):
    """A completely valid composition returns valid=True with zero issues."""
    report = validate_composition_report(canonical_valid_doc)
    assert report.valid is True
    assert len(report.issues) == 0
    assert len(report.errors) == 0


def test_validation_report_stable_codes_and_localization(canonical_valid_doc):
    """Validation issues have stable codes, category, path, and details."""
    doc = copy.deepcopy(canonical_valid_doc)
    # Add an overlapping event on channel 0
    doc["patterns"][0]["channels"]["0"] = [
        {"step": 0, "note": "C4", "instrument": "lead", "duration": 8, "volume": 14},
        {"step": 4, "note": "E4", "instrument": "lead", "duration": 4, "volume": 14},
    ]

    report = validate_composition_report(doc)
    assert report.valid is False
    assert len(report.issues) >= 1

    overlap_issue = next((i for i in report.issues if i.code == NOTE_OVERLAP), None)
    assert overlap_issue is not None
    assert overlap_issue.category == "musical"
    assert overlap_issue.code == "NOTE_OVERLAP"
    assert "patterns[A].channels[0].events" in overlap_issue.path
    assert overlap_issue.details["pattern"] == "A"
    assert overlap_issue.details["channel"] == "0"
    assert overlap_issue.details["event"]["note"] == "E4"
    assert overlap_issue.details["conflicting_event"]["note"] == "C4"


def test_validation_report_accumulates_multiple_issues(canonical_valid_doc):
    """Validator does not stop at first error; it accumulates all detectable issues in one report."""
    doc = copy.deepcopy(canonical_valid_doc)
    # 1. Unknown instrument
    doc["patterns"][0]["channels"]["0"][0]["instrument"] = "ghost_synth"
    # 2. Invalid note pitch
    doc["patterns"][0]["channels"]["0"][1]["note"] = "X9_BAD"
    # 3. Volume out of range
    doc["patterns"][0]["channels"]["1"][0]["volume"] = 99

    report = validate_composition_report(doc)
    assert report.valid is False
    issue_codes = {iss.code for iss in report.issues}

    assert UNKNOWN_INSTRUMENT in issue_codes
    assert INVALID_NOTE in issue_codes
    assert VOLUME_OUT_OF_RANGE in issue_codes


def test_validation_report_format_feedback(canonical_valid_doc):
    """format_feedback() generates a clean diagnostic message instructing preservation and schema compliance."""
    doc = copy.deepcopy(canonical_valid_doc)
    doc["patterns"][0]["channels"]["0"] = [
        {"step": 0, "note": "C4", "instrument": "lead", "duration": 8, "volume": 14},
        {"step": 4, "note": "E4", "instrument": "lead", "duration": 4, "volume": 14},
    ]

    report = validate_composition_report(doc)
    feedback = report.format_feedback()

    assert "[NOTE_OVERLAP]" in feedback
    assert "location: patterns[A].channels[0].events" in feedback
    assert "Preserve all valid parts" in feedback
    assert "Modify ONLY what is necessary" in feedback
    assert "Return the complete corrected composition" in feedback


# =============================================================================
# 2. Retry Loop & Mock Provider Scenarios
# =============================================================================

def test_retry_scenario_a_immediate_success():
    """Scenario A: Provider returns valid document on attempt 1 (1 call, 0 retries)."""
    provider = MockAICompositionProvider(scenario="immediate_success")
    req = CompositionRequest(style="action")

    doc = generate_composition_with_retry(req, provider, max_retries=3)

    assert isinstance(doc, AICompositionDoc)
    assert provider.call_count == 1
    assert provider.received_feedbacks == [None]
    assert provider.received_previous_compositions == [None]


def test_retry_scenario_b_invalid_then_valid():
    """Scenario B: Attempt 1 is invalid, Attempt 2 is repaired and succeeds (2 calls, 1 retry)."""
    provider = MockAICompositionProvider(scenario="invalid_then_valid")
    req = CompositionRequest(style="action")

    doc = generate_composition_with_retry(req, provider, max_retries=3)

    assert isinstance(doc, AICompositionDoc)
    assert provider.call_count == 2
    assert provider.received_feedbacks[0] is None
    assert provider.received_feedbacks[1] is not None
    assert "[NOTE_OVERLAP]" in provider.received_feedbacks[1]
    assert provider.received_previous_compositions[1] is not None


def test_retry_scenario_c_retry_limit_exhausted():
    """Scenario C: Provider returns invalid document on all attempts.
    
    With max_retries=3: 1 initial attempt + 3 retries = exactly 4 attempts total.
    Raises AICompositionGenerationError.
    """
    provider = MockAICompositionProvider(scenario="always_invalid")
    req = CompositionRequest(style="action")

    with pytest.raises(AICompositionGenerationError) as exc_info:
        generate_composition_with_retry(req, provider, max_retries=3)

    err = exc_info.value
    assert err.attempts_count == 4
    assert len(err.history) == 4
    assert provider.call_count == 4
    assert err.last_report is not None
    assert err.last_report.valid is False
    assert any(iss.code == NOTE_OVERLAP for iss in err.last_report.issues)


def test_retry_with_zero_retries():
    """When max_retries=0, exactly 1 attempt is made before raising AICompositionGenerationError."""
    provider = MockAICompositionProvider(scenario="always_invalid")
    req = CompositionRequest(style="action")

    with pytest.raises(AICompositionGenerationError) as exc_info:
        generate_composition_with_retry(req, provider, max_retries=0)

    err = exc_info.value
    assert err.attempts_count == 1
    assert len(err.history) == 1
    assert provider.call_count == 1


def test_retry_scenario_d_changing_errors_across_attempts():
    """Scenario D: Error changes across attempts, demonstrating full re-validation on every retry.
    
    Attempt 1: NOTE_OVERLAP
    Attempt 2: INVALID_NOTE
    Attempt 3: Valid
    """
    provider = MockAICompositionProvider(scenario="changing_errors")
    req = CompositionRequest(style="action")

    doc = generate_composition_with_retry(req, provider, max_retries=3)

    assert isinstance(doc, AICompositionDoc)
    assert provider.call_count == 3
    # Check feedback sent to attempt 2 had NOTE_OVERLAP
    assert "[NOTE_OVERLAP]" in provider.received_feedbacks[1]
    # Check feedback sent to attempt 3 had INVALID_NOTE
    assert "[INVALID_NOTE]" in provider.received_feedbacks[2]


# =============================================================================
# 3. Requirement 26: Canonical Note Overlap Repair to End-to-End Pipeline
# =============================================================================

def test_canonical_monophony_overlap_repair_and_pipeline(canonical_valid_doc):
    """Test Requirement 26:
    
    Attempt 1 has C4 step 0 duration 8 and E4 step 4 duration 4.
    Validator rejects with NOTE_OVERLAP.
    LLM repairs to C4 step 0 duration 4 and E4 step 4 duration 4.
    Validator accepts.
    Final output compiles cleanly through existing Music IR and POKEY IR.
    """
    attempt1_doc = copy.deepcopy(canonical_valid_doc)
    attempt1_doc["patterns"][0]["channels"]["0"] = [
        {"step": 0, "note": "C4", "instrument": "lead", "duration": 8, "volume": 14},
        {"step": 4, "note": "E4", "instrument": "lead", "duration": 4, "volume": 14},
    ]

    attempt2_doc = copy.deepcopy(canonical_valid_doc)
    attempt2_doc["patterns"][0]["channels"]["0"] = [
        {"step": 0, "note": "C4", "instrument": "lead", "duration": 4, "volume": 14},
        {"step": 4, "note": "E4", "instrument": "lead", "duration": 4, "volume": 14},
    ]

    provider = MockAICompositionProvider(sequence=[attempt1_doc, attempt2_doc])
    req = CompositionRequest(style="action")

    # Run repair loop
    doc = generate_composition_with_retry(req, provider, max_retries=3)
    assert provider.call_count == 2

    # Verify attempt 1 feedback had the exact overlap details
    fb = provider.received_feedbacks[1]
    assert "[NOTE_OVERLAP]" in fb
    assert "C4" in fb and "E4" in fb

    # Verify final document is valid AICompositionDoc
    assert isinstance(doc, AICompositionDoc)

    # Translate through existing downstream pipeline: Music IR -> POKEY IR
    result = generate_music_from_composition(doc)
    assert result.music_ir is not None
    assert result.pokey_ir is not None
    assert len(result.pokey_ir.patterns) >= 1
    assert result.metadata.channels_used == 4


# =============================================================================
# 4. Infrastructure vs Musical Error Isolation
# =============================================================================

def test_infrastructure_error_not_retried():
    """Provider infrastructure errors (e.g. missing API key) must not trigger retry loop."""
    # Instantiate OpenAI provider without API key
    provider = OpenAICompositionProvider(api_key="")
    req = CompositionRequest(style="action")

    with pytest.raises(AIProviderMissingKeyError):
        generate_composition_with_retry(req, provider, max_retries=3)


def test_openai_dependency_remains_optional():
    """Running retry loop with mock provider does not import or require 'openai' package."""
    # Ensure 'openai' is not artificially loaded in sys.modules during mock execution
    provider = MockAICompositionProvider(scenario="immediate_success")
    req = CompositionRequest(style="action")

    doc = generate_composition_with_retry(req, provider, max_retries=2)
    assert isinstance(doc, AICompositionDoc)
    assert "openai" not in sys.modules


def test_request_ai_composition_api_with_max_retries():
    """Public facade request_ai_composition passes max_retries to the repair loop."""
    req = CompositionRequest(style="action")
    doc = request_ai_composition(req, provider_name="mock", max_retries=2)
    assert isinstance(doc, AICompositionDoc)
    assert doc.metadata.title is not None

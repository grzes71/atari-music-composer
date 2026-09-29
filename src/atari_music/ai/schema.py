"""Data Models and Schema Definitions for AI Music Composition JSON.

Contract version: 1 ("atari-music-composition").
Provides declarative, high-level music specification without low-level 6502/POKEY details.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Union
from pydantic import BaseModel, Field, field_validator


# =============================================================================
# Validation Exceptions
# =============================================================================

class MusicCompositionError(Exception):
    """Base exception for all AI composition errors."""
    pass


class MusicCompositionSchemaError(MusicCompositionError):
    """Level 1: Document structural or JSON schema validation error."""
    pass


class MusicCompositionValidationError(MusicCompositionError):
    """Level 2: Musical grammar and internal consistency validation error."""
    pass


class MusicIRValidationError(MusicCompositionError):
    """Level 3: Hardware constraints and POKEY IR compatibility error."""
    pass


# =============================================================================
# Provider Exceptions
# =============================================================================

class AIProviderError(MusicCompositionError):
    """Base exception for AI provider communication and generation failures."""
    pass


class AIProviderMissingKeyError(AIProviderError):
    """Raised when an API key required by a provider is missing or empty."""
    pass


class AIProviderDependencyError(AIProviderError):
    """Raised when an optional dependency (such as 'openai') is not installed."""
    pass


class AIProviderAPIError(AIProviderError):
    """Raised when an external AI provider API returns an HTTP or operational error."""
    pass


class AIProviderStructuredOutputError(AIProviderError):
    """Raised when a model response cannot be parsed into the expected structured schema."""
    pass


class AICompositionGenerationError(AIProviderError):
    """Raised when composition generation fails or exhausts all retry attempts."""

    def __init__(
        self,
        message: str,
        attempts_count: int = 1,
        last_composition: Optional[Dict[str, Any]] = None,
        last_report: Optional[ValidationReport] = None,
        history: Optional[List[CompositionAttempt]] = None,
    ) -> None:
        super().__init__(message)
        self.attempts_count = attempts_count
        self.last_composition = last_composition
        self.last_report = last_report
        self.history = history or []


# =============================================================================
# Validation Report Models
# =============================================================================

class ValidationIssue(BaseModel):
    """Machine-readable description of a single validation violation."""
    category: str = Field(description="Violation category: 'schema', 'musical', or 'hardware'")
    code: str = Field(description="Stable machine-readable error code (e.g. NOTE_OVERLAP, INVALID_NOTE)")
    message: str = Field(description="Human-readable explanation of the violation")
    path: Optional[str] = Field(default=None, description="Exact document path (e.g. 'patterns[A].channels[0].events[1]')")
    details: Dict[str, Any] = Field(default_factory=dict, description="Structured diagnostics and contextual parameters")


class ValidationReport(BaseModel):
    """Structured report consolidating all issues found across all validation tiers."""
    valid: bool = Field(default=True, description="True if no issues were encountered")
    issues: List[ValidationIssue] = Field(default_factory=list, description="List of recorded validation issues")
    warnings: List[ValidationIssue] = Field(
        default_factory=list,
        description="Non-fatal issues: playable, but not exactly as requested (never invalidates the report)",
    )

    @property
    def errors(self) -> List[ValidationIssue]:
        """Convenience alias for issues."""
        return self.issues

    def add_issue(
        self,
        category: str,
        code: str,
        message: str,
        path: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Record an issue and mark report as invalid."""
        self.valid = False
        self.issues.append(
            ValidationIssue(
                category=category,
                code=code,
                message=message,
                path=path,
                details=details or {},
            )
        )

    def add_warning(
        self,
        category: str,
        code: str,
        message: str,
        path: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Record a non-fatal issue without invalidating the report.

        Warnings describe lossy-but-playable hardware outcomes (for example a pitch
        below the 8-bit AUDF floor). They must not fail validation and must not
        trigger composition repair, so ``valid`` is deliberately left untouched.
        """
        self.warnings.append(
            ValidationIssue(
                category=category,
                code=code,
                message=message,
                path=path,
                details=details or {},
            )
        )

    def format_feedback(self) -> str:
        """Format issues into actionable structured feedback for LLM composition repair."""
        lines = [
            "Your composition failed validation.",
            "",
            "Fix the following issues:",
        ]
        for issue in self.issues:
            loc = f" (location: {issue.path})" if issue.path else ""
            lines.append(f"\n[{issue.code}]{loc}")
            lines.append(f"Problem: {issue.message}")
            if issue.details:
                lines.append("Details:")
                for k, v in issue.details.items():
                    lines.append(f"  * {k}: {v}")

        lines.extend([
            "",
            "CRITICAL INSTRUCTIONS FOR CORRECTION:",
            "- Preserve all valid parts of the existing composition.",
            "- Modify ONLY what is necessary to resolve the reported validation errors.",
            "- Return the complete corrected composition using the required structured schema.",
        ])
        return "\n".join(lines)


class CompositionAttempt(BaseModel):
    """Diagnostic record of an individual generation attempt in the repair loop."""
    attempt_number: int
    composition: Optional[Dict[str, Any]] = None
    report: ValidationReport
    usage: Optional[Dict[str, int]] = None
    wall_time_ms: Optional[float] = None



# =============================================================================
# Composition Document Models
# =============================================================================

class AICompositionMetadata(BaseModel):
    """Metadata describing the piece and its musical key/tempo parameters."""
    title: str = Field(description="Title of the composition")
    author: str = Field(default="AI Composer", description="Composer or model attribution")
    description: Optional[str] = Field(default=None, description="Optional brief description")
    key: str = Field(default="C", description="Root musical key (e.g. C, D, E, F, G, A, B)")
    mode: str = Field(default="minor", description="Musical mode/scale (e.g. minor, major, dorian, mixolydian)")
    bpm: int = Field(default=120, ge=40, le=250, description="Tempo in beats per minute (40..250)")
    duration_seconds: Optional[float] = Field(default=None, ge=1.0, le=300.0, description="Target duration in seconds")


class AIHardwareConfig(BaseModel):
    """Hardware target constraints and capabilities."""
    channels: int = Field(default=4, ge=1, le=4, description="Target POKEY channels (1..4)")
    use_16bit_bass: bool = Field(default=False, description="Enable 16-bit pure tone bass coupling on Ch1+Ch2")


class AIInstrumentDef(BaseModel):
    """Semantic instrument definition."""
    id: str = Field(description="Unique instrument identifier referenced by events (e.g. 'lead', 'bass')")
    name: str = Field(description="Human readable instrument name")
    character: str = Field(
        default="bright_lead",
        description="Semantic timbre archetype. Supported: bright_lead, dark_lead, soft_pad, bass, "
        "percussion, noise, drum, snare, hihat, kick, tom, bell, ornament, harmony, counter",
    )
    distortion: Optional[int] = Field(
        default=None,
        description="Optional POKEY AUDC distortion override: $00, $20, $40, $60, $80, $A0, $C0 or $E0 "
        "(note: $E0 is audibly identical to $A0; the real noise mode is $80)",
    )
    attack_frames: Optional[int] = Field(default=None, ge=0, le=15, description="Optional ADSR attack frames (0..15)")
    decay_frames: Optional[int] = Field(default=None, ge=0, le=15, description="Optional ADSR decay frames (0..15)")
    sustain_vol: Optional[int] = Field(default=None, ge=0, le=15, description="Optional ADSR sustain volume (0..15)")
    release_frames: Optional[int] = Field(default=None, ge=0, le=15, description="Optional ADSR release frames (0..15)")


class AIPatternChannelEvent(BaseModel):
    """Note or rest event at a specific step in a pattern."""
    step: int = Field(ge=0, description="Step offset within the pattern (0-indexed)")
    note: Optional[str] = Field(default=None, description="Note pitch name (e.g. 'C4', 'A#2', 'Eb3') or None/'REST'")
    instrument: str = Field(description="Instrument ID matching an instrument in instruments list")
    duration: int = Field(default=1, description="Duration in steps (>= 1; enforced by hardware validation)")
    volume: Optional[int] = Field(default=14, description="Initial velocity/volume (0..15; enforced by hardware validation)")


class AIPatternDef(BaseModel):
    """Pattern containing multi-channel event sequences."""
    id: str = Field(description="Unique pattern identifier (e.g. 'A', 'B', 'Intro')")
    length_steps: int = Field(default=16, ge=1, le=128, description="Length of pattern in steps (typically 16, 32, or 64)")
    channels: Dict[str, List[AIPatternChannelEvent]] = Field(
        default_factory=dict,
        description="Channel event lists keyed by channel index (0..3 or 1..4)",
    )
    role: Optional[str] = Field(
        default=None,
        description="Optional musical role: intro, theme, variation, contrast, bridge, breakdown, fill, outro",
    )
    variation_of: Optional[str] = Field(
        default=None,
        description="Base pattern ID if this pattern is a thematic variation (e.g. 'themeA')",
    )
    texture_notes: Optional[str] = Field(
        default=None,
        description="Optional texture / instrumentation notes (e.g. 'bass solo', 'full band', 'breakdown')",
    )


class AISectionPlanItem(BaseModel):
    """A planned structural section within the composition's architectural form."""
    section_id: str = Field(description="Section label in form plan, e.g. 'Intro', 'A', 'A_var', 'B', 'Fill1', 'Breakdown', 'Outro'")
    pattern_id: str = Field(description="Pattern ID in patterns list realizing this section")
    role: str = Field(
        default="theme",
        description="Musical function: intro, theme, variation, contrast, bridge, breakdown, fill, outro",
    )
    variation_of: Optional[str] = Field(
        default=None,
        description="Base pattern ID if this section is a variation (e.g. 'A')",
    )
    description: Optional[str] = Field(
        default=None,
        description="Brief musical intent, texture changes, or variation details",
    )


class AIFormPlanDef(BaseModel):
    """Macro-structural form plan establishing themes, variations, and transitions."""
    form_type: str = Field(
        default="episodic_variation",
        description="Architectural form archetype: e.g. rondo_variation, episodic_variation, ternary_variation, arch_form",
    )
    primary_theme_description: Optional[str] = Field(
        default=None,
        description="Core melodic, rhythmic, and harmonic concept of Theme A",
    )
    contrast_theme_description: Optional[str] = Field(
        default=None,
        description="Contrasting concept of Theme B or C (tonality, texture, mood shift)",
    )
    sections: List[AISectionPlanItem] = Field(
        default_factory=list,
        description="Ordered sequence of planned musical sections",
    )


class AIIntentDef(BaseModel):
    """Creative musical intent and prompt parameters."""
    style: Optional[str] = None
    mood: Optional[List[str]] = None
    structure: Optional[str] = None
    composition_notes: Optional[str] = None


class AIProvenanceDef(BaseModel):
    """Audit trail and generation provenance."""
    source: str = "ai"
    provider: Optional[str] = None
    model: Optional[str] = None
    generated_at: Optional[str] = None
    request_id: Optional[str] = None


class AICompositionDoc(BaseModel):
    """Top-Level AI Composition Document.
    
    Versioned declarative schema defining complete composition.
    """
    format: str = Field(default="atari-music-composition", description="Must be 'atari-music-composition'")
    version: int = Field(default=1, description="Format version integer (currently 1)")
    metadata: AICompositionMetadata
    form_plan: Optional[AIFormPlanDef] = Field(
        default=None,
        description="Optional macro-structural musical form plan establishing themes and variations",
    )
    hardware: AIHardwareConfig = Field(default_factory=AIHardwareConfig)
    instruments: List[AIInstrumentDef] = Field(default_factory=list)
    patterns: List[AIPatternDef] = Field(default_factory=list)
    sequence: List[str] = Field(default_factory=list)
    loop_point: int = Field(default=0, ge=0, description="Sequence step index to loop back to (0-indexed)")
    intent: Optional[AIIntentDef] = None
    provenance: Optional[AIProvenanceDef] = None

    @field_validator("format")
    @classmethod
    def validate_format_tag(cls, v: str) -> str:
        if v != "atari-music-composition":
            raise ValueError(f"Invalid format '{v}', expected 'atari-music-composition'")
        return v

    @field_validator("version")
    @classmethod
    def validate_version_num(cls, v: int) -> int:
        if v != 1:
            raise ValueError(f"Unsupported format version {v}, expected 1")
        return v

"""Atari Music AI Composition Layer.

Enables AI models to act as composers, generating declarative JSON documents
that are strictly validated and interpreted into Symbolic Music IR and POKEY IR.
"""

from __future__ import annotations

from atari_music.ai.analysis import (
    CompositionAnalysisReport,
    HarmonyMetrics,
    MelodyMetrics,
    PokeyMetrics,
    RhythmMetrics,
    StructureMetrics,
    analyze_composition,
    calculate_bpm_frames_per_tick,
    calculate_composition_duration,
    calculate_loop_duration,
    composition_fingerprint,
    verify_duration_invariant,
)
from atari_music.ai.structure_analysis import (
    DetailedStructureMetrics,
    MusicalFormAnalysis,
    PatternComparison,
    analyze_composition_structure,
    calculate_domain_diversities,
    calculate_material_reuse_ratio,
    compare_patterns,
    deduce_musical_form,
    find_repeated_subsequences,
)
from atari_music.ai.client import (
    build_xex_from_composition,
    generate_composition_with_retry,
    generate_music_from_composition,
    generate_music_from_json,
    load_composition_json,
    request_ai_composition,
)
from atari_music.ai.composition import (
    compile_composition_to_pokey_ir,
    interpret_composition_to_music_ir,
    map_instrument_character,
)
from atari_music.ai.providers import (
    AICompositionProvider,
    CompositionRequest,
    MockAICompositionProvider,
    OpenAICompositionProvider,
    get_ai_provider,
)
from atari_music.ai.schema import (
    AICompositionDoc,
    AICompositionGenerationError,
    AICompositionMetadata,
    AIFormPlanDef,
    AIHardwareConfig,
    AIInstrumentDef,
    AIPatternChannelEvent,
    AIPatternDef,
    AISectionPlanItem,
    AIProviderAPIError,
    AIProviderDependencyError,
    AIProviderError,
    AIProviderMissingKeyError,
    AIProviderStructuredOutputError,
    CompositionAttempt,
    MusicCompositionError,
    MusicCompositionSchemaError,
    MusicCompositionValidationError,
    MusicIRValidationError,
    ValidationIssue,
    ValidationReport,
)
from atari_music.ai.validation import (
    validate_composition,
    validate_composition_report,
    validate_hardware,
    validate_musical,
    validate_schema,
)


__all__ = [
    # Document schema & models
    "AICompositionDoc",
    "AICompositionMetadata",
    "AIFormPlanDef",
    "AIHardwareConfig",
    "AIInstrumentDef",
    "AIPatternChannelEvent",
    "AIPatternDef",
    "AISectionPlanItem",
    # Exceptions
    "MusicCompositionError",
    "MusicCompositionSchemaError",
    "MusicCompositionValidationError",
    "MusicIRValidationError",
    "AIProviderError",
    "AIProviderMissingKeyError",
    "AIProviderDependencyError",
    "AIProviderAPIError",
    "AIProviderStructuredOutputError",
    # Validation
    "validate_composition",
    "validate_schema",
    "validate_musical",
    "validate_hardware",
    # Analysis & Fingerprinting
    "analyze_composition",
    "calculate_bpm_frames_per_tick",
    "calculate_composition_duration",
    "calculate_loop_duration",
    "composition_fingerprint",
    "verify_duration_invariant",
    "CompositionAnalysisReport",
    "RhythmMetrics",
    "MelodyMetrics",
    "HarmonyMetrics",
    "StructureMetrics",
    "PokeyMetrics",
    # Structure & Variation Quality (Stage 16)
    "DetailedStructureMetrics",
    "MusicalFormAnalysis",
    "PatternComparison",
    "analyze_composition_structure",
    "calculate_domain_diversities",
    "calculate_material_reuse_ratio",
    "compare_patterns",
    "deduce_musical_form",
    "find_repeated_subsequences",
    # Interpretation
    "interpret_composition_to_music_ir",
    "compile_composition_to_pokey_ir",
    "map_instrument_character",
    # High-level client API
    "load_composition_json",
    "generate_music_from_composition",
    "generate_music_from_json",
    "request_ai_composition",
    "build_xex_from_composition",
    # Providers
    "CompositionRequest",
    "AICompositionProvider",
    "OpenAICompositionProvider",
    "MockAICompositionProvider",
    "get_ai_provider",
]

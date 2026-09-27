"""Unit and regression tests for Stage 16 Musical Structure & Variation Quality."""

import pytest

from atari_music.ai.schema import (
    AICompositionDoc,
    AICompositionMetadata,
    AIHardwareConfig,
    AIInstrumentDef,
    AIPatternChannelEvent,
    AIPatternDef,
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


def _make_pattern(pat_id: str, length: int = 16, notes: list[tuple[int, str, int]] | None = None) -> AIPatternDef:
    """Helper to build an AIPatternDef with Ch1 events [(step, note, dur), ...]."""
    ch1_events = []
    if notes:
        for s, n, d in notes:
            ch1_events.append(AIPatternChannelEvent(step=s, note=n, instrument="lead", duration=d, volume=12))
    return AIPatternDef(
        id=pat_id,
        length_steps=length,
        channels={"1": ch1_events, "2": [], "3": [], "4": []},
    )


def _make_doc(patterns: list[AIPatternDef], sequence: list[str]) -> AICompositionDoc:
    return AICompositionDoc(
        metadata=AICompositionMetadata(title="Test Structure Song", bpm=120, key="C", mode="minor"),
        hardware=AIHardwareConfig(channels=4, use_16bit_bass=False),
        instruments=[AIInstrumentDef(id="lead", name="Lead", character="bright_lead")],
        patterns=patterns,
        sequence=sequence,
    )


def test_identical_pattern_detection():
    """Identical note content in different pattern IDs must yield similarity=1.0 and is_identical=True."""
    p1 = _make_pattern("patA", 16, [(0, "C4", 4), (4, "E4", 4), (8, "G4", 8)])
    p2 = _make_pattern("patB", 16, [(0, "C4", 4), (4, "E4", 4), (8, "G4", 8)])

    cmp = compare_patterns(p1, p2)
    assert cmp.is_identical is True
    assert cmp.similarity == 1.0
    assert cmp.distance == 0.0
    assert cmp.relationship == "identical"


def test_near_identical_variation_detection():
    """Pattern with only a 1-semitone subtle variation should be detected as near_variation."""
    p1 = _make_pattern("patA", 16, [(0, "C4", 4), (4, "E4", 4), (8, "G4", 8)])
    # Only middle note slightly changed from E4 to F4
    p2 = _make_pattern("patA_var", 16, [(0, "C4", 4), (4, "F4", 4), (8, "G4", 8)])

    cmp = compare_patterns(p1, p2)
    assert cmp.is_identical is False
    assert cmp.similarity >= 0.80
    assert cmp.relationship == "near_variation"


def test_distinct_patterns_detection():
    """Completely different melodies and rhythms should be classified as distinct."""
    p1 = _make_pattern("patA", 16, [(0, "C4", 4), (4, "E4", 4), (8, "G4", 8)])
    p2 = _make_pattern("patB", 16, [(0, "A2", 2), (2, "A2", 2), (4, "D3", 4), (8, "REST", 8)])

    cmp = compare_patterns(p1, p2)
    assert cmp.is_identical is False
    assert cmp.similarity < 0.60
    assert cmp.relationship == "distinct"


def test_repeated_subsequence_detection():
    """Detects repeated multi-pattern blocks and computes sequence coverage percentage."""
    # Sequence: [Intro, A, B, C, A, B, C, Outro]
    # Block [A, B, C] length 3 repeats 2 times
    seq = ["Intro", "A", "B", "C", "A", "B", "C", "Outro"]
    res = find_repeated_subsequences(seq)

    assert res["longest_subsequence"] == ["A", "B", "C"]
    assert res["longest_subsequence_len"] == 3
    assert res["longest_subsequence_count"] == 2
    # Covered indices: 1, 2, 3 and 4, 5, 6 -> 6 out of 8 = 75.0%
    assert res["repeated_blocks_coverage_pct"] == 75.0


def test_material_reuse_ratio_through_composed():
    """A completely through-composed piece where every pattern is unique has 0.0 reuse ratio."""
    p1 = _make_pattern("P1", 16, [(0, "C4", 16)])
    p2 = _make_pattern("P2", 16, [(0, "E4", 16)])
    p3 = _make_pattern("P3", 16, [(0, "G4", 16)])
    doc = _make_doc([p1, p2, p3], ["P1", "P2", "P3"])

    cmps = {
        ("P1", "P2"): compare_patterns(p1, p2),
        ("P2", "P1"): compare_patterns(p1, p2),
        ("P2", "P3"): compare_patterns(p2, p3),
        ("P3", "P2"): compare_patterns(p2, p3),
        ("P1", "P3"): compare_patterns(p1, p3),
        ("P3", "P1"): compare_patterns(p1, p3),
    }
    reuse = calculate_material_reuse_ratio(doc, cmps)
    assert reuse == 0.0


def test_material_reuse_ratio_repetitive_loop():
    """A 4-step sequence repeating the same pattern has high material reuse (0.75)."""
    p1 = _make_pattern("P1", 16, [(0, "C4", 16)])
    doc = _make_doc([p1], ["P1", "P1", "P1", "P1"])
    cmps = {}

    reuse = calculate_material_reuse_ratio(doc, cmps)
    # First pattern (slot 0) is new (16 steps). Next 3 slots are 100% reuse (48 steps).
    # 48 / 64 = 0.75
    assert reuse == pytest.approx(0.75, abs=0.01)


def test_musical_form_deduction():
    """Deduces Intro, main themes, variations, and Outro sections correctly."""
    intro = _make_pattern("intro", 16, [(0, "C4", 2)])  # sparse
    themeA = _make_pattern("A", 16, [(0, "C4", 4), (4, "E4", 4), (8, "G4", 4), (12, "C5", 4)])
    themeA_var = _make_pattern("A2", 16, [(0, "C4", 4), (4, "E4", 4), (8, "G4", 4), (12, "D5", 4)])  # near-variation
    themeB = _make_pattern("B", 16, [(0, "F3", 8), (8, "A3", 8)])  # distinct
    outro = _make_pattern("outro", 16, [(0, "C3", 16)])  # outro

    doc = _make_doc(
        [intro, themeA, themeA_var, themeB, outro],
        ["intro", "A", "A2", "B", "A", "outro"],
    )
    pats = doc.patterns
    cmps = {}
    for i in range(len(pats)):
        for j in range(len(pats)):
            if i != j:
                cmps[(pats[i].id, pats[j].id)] = compare_patterns(pats[i], pats[j])

    form = deduce_musical_form(doc, cmps)
    assert form.formal_sequence[0] == "INTRO"
    assert form.formal_sequence[1] == "A"
    assert form.formal_sequence[2] == "A'"
    assert form.formal_sequence[3] == "B"
    assert form.formal_sequence[4] == "A"
    assert form.formal_sequence[5] == "OUTRO"
    assert "INTRO - A - A' - B - A - OUTRO" in form.compact_form


def test_domain_diversities():
    """Monotonous piece should have lower diversity scores than a rich harmonic/melodic piece."""
    mono_pat = _make_pattern("mono", 16, [(0, "C4", 16)])
    mono_doc = _make_doc([mono_pat], ["mono"])
    m_div, r_div, h_div = calculate_domain_diversities(mono_doc)
    assert m_div <= 0.10
    assert r_div <= 0.25
    assert h_div == 0.0  # no vertical chords

    # Rich piece
    rich_ch = {
        "1": [AIPatternChannelEvent(step=s*2, note=n, instrument="lead", duration=2, volume=12)
              for s, n in enumerate(["C4", "D4", "E4", "F4", "G4", "A4", "B4", "C5"])],
        "2": [AIPatternChannelEvent(step=s*4, note=n, instrument="lead", duration=4, volume=10)
              for s, n in enumerate(["E3", "G3", "B3", "D4"])],
        "3": [AIPatternChannelEvent(step=0, note="C2", instrument="lead", duration=16, volume=14)],
        "4": [],
    }
    rich_pat = AIPatternDef(id="rich", length_steps=16, channels=rich_ch)
    rich_doc = _make_doc([rich_pat], ["rich"])
    m_div2, r_div2, h_div2 = calculate_domain_diversities(rich_doc)

    assert m_div2 > m_div
    assert h_div2 > 0.50  # multiple sounding interval classes


def test_full_analyze_composition_structure():
    """End-to-end execution of analyze_composition_structure."""
    p1 = _make_pattern("P1", 16, [(0, "C4", 8), (8, "G4", 8)])
    p2 = _make_pattern("P2", 16, [(0, "F4", 8), (8, "A4", 8)])
    doc = _make_doc([p1, p2], ["P1", "P2", "P1", "P2"])

    metrics = analyze_composition_structure(doc)
    assert isinstance(metrics, DetailedStructureMetrics)
    assert metrics.pattern_count == 2
    assert metrics.sequence_length == 4
    assert metrics.total_steps == 64
    assert metrics.repetition_ratio == 0.5
    assert metrics.unique_pattern_ratio == 0.5
    assert metrics.unique_transitions_count == 2  # (P1, P2) and (P2, P1)
    assert metrics.longest_repeated_subsequence == ["P1", "P2"]
    assert metrics.repeated_subsequences_coverage_pct == 100.0
    assert 0.0 <= metrics.material_reuse_ratio <= 1.0


def test_stage17_variations_and_fills_metrics():
    """Verify that thematic variations and fill patterns are detected objectively."""
    from atari_music.ai.schema import AISectionPlanItem, AIFormPlanDef

    # Base theme A (16 steps)
    p_a = _make_pattern("themeA", 16, [(0, "C4", 4), (4, "D4", 4), (8, "E4", 4), (12, "G4", 4)])
    # Variation A' (16 steps: 3 identical notes, 1 altered cadence note at step 12)
    p_a_var = _make_pattern("themeA_var", 16, [(0, "C4", 4), (4, "D4", 4), (8, "E4", 4), (12, "B4", 4)])
    p_a_var.variation_of = "themeA"
    p_a_var.role = "variation"
    # Transition fill (8 steps)
    p_fill = _make_pattern("fill1", 8, [(0, "C4", 2), (2, "D4", 2), (4, "E4", 2), (6, "F4", 2)])
    p_fill.role = "fill"

    doc = _make_doc([p_a, p_a_var, p_fill], ["themeA", "themeA_var", "fill1", "themeA"])
    doc.form_plan = AIFormPlanDef(
        form_type="theme_and_variation",
        sections=[
            AISectionPlanItem(section_id="A", pattern_id="themeA", role="theme"),
            AISectionPlanItem(section_id="A'", pattern_id="themeA_var", role="variation", variation_of="themeA"),
            AISectionPlanItem(section_id="Fill", pattern_id="fill1", role="fill"),
            AISectionPlanItem(section_id="A", pattern_id="themeA", role="theme"),
        ]
    )

    metrics = analyze_composition_structure(doc)
    assert metrics.variation_count >= 1
    assert metrics.variation_ratio >= 0.33
    assert metrics.transition_fill_count == 1
    assert metrics.sections_count == 4
    assert 0.70 <= metrics.variation_similarity <= 0.99


def test_stage17_texture_changes_and_structural_novelty():
    """Verify texture changes detection across channels and second-half novelty."""
    # Pattern 1: 4 channels active
    ch_full = {
        "1": [AIPatternChannelEvent(step=0, note="C4", instrument="lead", duration=4)],
        "2": [AIPatternChannelEvent(step=0, note="E3", instrument="lead", duration=4)],
        "3": [AIPatternChannelEvent(step=0, note="C2", instrument="lead", duration=4)],
        "4": [AIPatternChannelEvent(step=0, note="C1", instrument="lead", duration=4)],
    }
    p_full = AIPatternDef(id="full", length_steps=16, channels=ch_full)

    # Pattern 2: Breakdown with only 1 channel active (solo bass)
    ch_solo = {
        "1": [],
        "2": [],
        "3": [AIPatternChannelEvent(step=0, note="C2", instrument="lead", duration=4)],
        "4": [],
    }
    p_breakdown = AIPatternDef(id="breakdown", length_steps=16, channels=ch_solo, role="breakdown")

    # Pattern 3: Outro
    p_outro = _make_pattern("outro", 16, [(0, "C4", 8)])

    # Sequence: full -> breakdown -> full -> outro
    doc = _make_doc([p_full, p_breakdown, p_outro], ["full", "breakdown", "full", "outro"])
    metrics = analyze_composition_structure(doc)

    # In sequence: full (4ch) -> breakdown (1ch) -> full (4ch) -> outro (1ch) -> 3 changes of active channel set
    assert metrics.texture_changes_count == 3
    assert metrics.active_channels_distribution["4_ch"] == 1
    assert metrics.active_channels_distribution["1_ch"] == 2
    # In second half ["full", "outro"]: outro was NOT in first half ["full", "breakdown"], so novelty > 0
    assert metrics.structural_novelty >= 0.50

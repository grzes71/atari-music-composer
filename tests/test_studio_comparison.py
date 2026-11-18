"""Tests for headless Studio Phase 3 A/B Comparison session logic (PySide6-free)."""

from __future__ import annotations

from pathlib import Path

import pytest

from atari_music.studio import (
    ComparisonError,
    ComparisonSession,
    InstrumentService,
    RenderService,
    StudioArrangementConfig,
    load_studio_composition,
)

pytestmark = pytest.mark.core

REPO_ROOT = Path(__file__).resolve().parents[1]


def test_comparison_slot_lifecycle_empty_not_rendered_ready_outdated() -> None:
    inst_svc = InstrumentService()
    render_svc = RenderService(inst_svc)
    session = ComparisonSession(inst_svc, render_svc)
    try:
        state = load_studio_composition(REPO_ROOT / "examples" / "ai" / "action_fast.json")
        before_sha = state.base_ir_sha256
        before_fp = state.musical_fingerprint

        session.bind_composition(state)

        # Initial slots are Empty
        st_a = session.slot_status("A", state=state, working_config=state.baseline_config)
        st_b = session.slot_status("B", state=state, working_config=state.baseline_config)
        assert st_a.render_status == "empty" and not st_a.can_listen and not st_a.can_render
        assert st_b.render_status == "empty" and not st_b.can_listen and not st_b.can_render

        # Save to A -> Not rendered (and matches_editor=True)
        cfg_a = StudioArrangementConfig(
            channel_instruments={1: "lead_pure_sustain", 2: "bass_15khz_pure", 3: None, 4: None}
        )
        st_a = session.save_slot("A", state, cfg_a, label="Sustain Mix")
        assert st_a.render_status == "not_rendered"
        assert st_a.matches_editor is True
        assert st_a.can_listen is False
        assert st_a.can_render is True

        # Render A through shared RenderService and record it -> Ready
        entry_a = render_svc.render_preview(state, cfg_a)
        assert session.record_rendered_entry("A", state, entry_a) is True
        st_a = session.slot_status("A", state=state, working_config=cfg_a)
        assert st_a.render_status == "ready"
        assert st_a.can_listen is True

        # Editing working_config externally does NOT alter slot A or its Ready render!
        edited_cfg = cfg_a.with_channel(4, "perc_snare_crisp")
        st_a_after_edit = session.slot_status("A", state=state, working_config=edited_cfg)
        assert st_a_after_edit.render_status == "ready"
        assert st_a_after_edit.can_listen is True
        assert st_a_after_edit.matches_editor is False
        assert session.get_variant("A").config == cfg_a  # type: ignore[union-attr]

        # Explicitly saving new edited_cfg to slot A before rendering marks A as Outdated
        st_a_outdated = session.save_slot("A", state, edited_cfg, label="Snare Update")
        assert st_a_outdated.render_status == "outdated"
        assert st_a_outdated.matches_editor is True
        assert st_a_outdated.can_listen is False
        with pytest.raises(ComparisonError) as exc_listen:
            session.select_listen_slot("A", state)
        assert exc_listen.value.code == "SLOT_NOT_READY"

        # Rendering updated config promotes A back to Ready cleanly
        entry_a2 = render_svc.render_preview(state, edited_cfg)
        assert session.record_rendered_entry("A", state, entry_a2) is True
        assert session.slot_status("A", state=state, working_config=edited_cfg).render_status == "ready"

        # Re-saving old cfg_a (already in RenderService cache!) resolves Ready immediately without re-render
        st_a_cached = session.save_slot("A", state, cfg_a)
        assert st_a_cached.render_status == "ready"
        assert st_a_cached.variant is not None and st_a_cached.variant.rendered_entry is not None
        assert st_a_cached.variant.rendered_entry.wav_path == entry_a.wav_path

        # Baseline state remains immutable
        assert state.base_ir_sha256 == before_sha
        assert state.musical_fingerprint == before_fp
    finally:
        render_svc.cleanup()


def test_comparison_ab_independence_shared_cache_and_zero_render_switch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    inst_svc = InstrumentService()
    render_svc = RenderService(inst_svc)
    session = ComparisonSession(inst_svc, render_svc)
    try:
        state = load_studio_composition(REPO_ROOT / "examples" / "ai" / "action_fast.json")
        cfg_a = StudioArrangementConfig(
            channel_instruments={1: "lead_pure_sustain", 2: "bass_15khz_pure", 3: None, 4: "perc_kick_tight"}
        )
        cfg_b = StudioArrangementConfig(
            channel_instruments={1: "lead_attack_bite", 2: "bass_poly4_punch", 3: None, 4: "perc_snare_crisp"}
        )

        session.save_slot("A", state, cfg_a, label="Warm")
        session.save_slot("B", state, cfg_b, label="Punchy")
        entry_a = render_svc.render_preview(state, cfg_a)
        entry_b = render_svc.render_preview(state, cfg_b)
        assert entry_a.wav_path != entry_b.wav_path
        assert session.record_rendered_entry("A", state, entry_a) is True
        assert session.record_rendered_entry("B", state, entry_b) is True

        # Loading B config to editor and mutating it never mutates slot A or B
        loaded_b_cfg, loaded_label = session.load_slot_config("B")
        assert loaded_label == "Punchy"
        assert loaded_b_cfg == cfg_b
        _mutated = loaded_b_cfg.with_channel(3, "harmony_soft_square")
        assert session.get_variant("A").config == cfg_a  # type: ignore[union-attr]
        assert session.get_variant("B").config == cfg_b  # type: ignore[union-attr]

        # Switching active listen A <-> B MUST NOT invoke RenderService.render_preview!
        def _forbid_render(*_args, **_kwargs):
            raise AssertionError("A/B switching must not re-render!")

        monkeypatch.setattr(RenderService, "render_preview", _forbid_render)
        picked_a = session.select_listen_slot("A", state)
        assert picked_a.wav_path == entry_a.wav_path
        assert session.active_listen_slot == "A"
        assert session.slot_status("A", state=state).active_listen is True
        assert session.slot_status("B", state=state).active_listen is False

        picked_b = session.select_listen_slot("B", state)
        assert picked_b.wav_path == entry_b.wav_path
        assert session.active_listen_slot == "B"
        assert session.slot_status("A", state=state).active_listen is False
        assert session.slot_status("B", state=state).active_listen is True
    finally:
        render_svc.cleanup()


def test_comparison_rejects_stale_worker_results_and_clears_on_new_composition() -> None:
    inst_svc = InstrumentService()
    render_svc = RenderService(inst_svc)
    session = ComparisonSession(inst_svc, render_svc)
    try:
        state_1 = load_studio_composition(REPO_ROOT / "examples" / "ai" / "action_fast.json")
        state_2 = load_studio_composition(REPO_ROOT / "examples" / "songs" / "wybierak-2.dsl")

        cfg_old = StudioArrangementConfig(channel_instruments={1: "lead_pure_sustain", 2: "bass_15khz_pure", 3: None, 4: None})
        cfg_new = StudioArrangementConfig(channel_instruments={1: "lead_attack_bite", 2: "bass_15khz_pure", 3: None, 4: None})

        session.save_slot("A", state_1, cfg_old)
        stale_entry = render_svc.render_preview(state_1, cfg_old)

        # Update slot A to cfg_new before stale worker finishes -> stale entry must be rejected!
        session.save_slot("A", state_1, cfg_new)
        assert session.record_rendered_entry("A", state_1, stale_entry) is False
        assert session.slot_status("A", state=state_1).render_status == "not_rendered"

        # Now render cfg_new cleanly and switch composition -> session clears and rejects state_1 entries!
        session.save_slot("B", state_1, cfg_old)
        assert session.record_rendered_entry("B", state_1, stale_entry) is True
        session.select_listen_slot("B", state_1)
        assert session.active_listen_slot == "B"

        session.bind_composition(state_2)
        assert session.active_listen_slot is None
        assert session.get_variant("A") is None
        assert session.get_variant("B") is None
        assert session.record_rendered_entry("B", state_1, stale_entry) is False

        with pytest.raises(ComparisonError) as exc_mismatch:
            session.select_listen_slot("A", state_1)
        assert exc_mismatch.value.code == "COMPOSITION_MISMATCH"

        with pytest.raises(ComparisonError) as exc_slot:
            session.get_variant("C")
        assert exc_slot.value.code == "INVALID_SLOT"

        with pytest.raises(ComparisonError) as exc_empty:
            session.load_slot_config("A")
        assert exc_empty.value.code == "SLOT_EMPTY"
    finally:
        render_svc.cleanup()

"""Live production LLM validation tests (Etap 14.1).

Requires explicit execution:
    pytest -m live -v

Automatically skipped if no valid production credentials (DEEPSEEK_API_KEY / OPENAI_API_KEY)
are configured or if running regular test suite (`pytest -q`).
"""

from __future__ import annotations

import os
from pathlib import Path
import pytest

from atari_music.ai.client import (
    build_xex_from_composition,
    generate_music_from_composition,
    request_ai_composition,
)
from atari_music.ai.providers.base import CompositionRequest
from atari_music.ai.schema import AICompositionDoc
from atari_music.ai.validation import validate_composition_report


def _get_live_credentials():
    """Retrieve credentials without leaking secrets."""
    try:
        from config import Config
        cfg = Config.from_args(args=[], validate=False)
        key = cfg.ai_api_key
        url = cfg.ai_base_url
        model = cfg.ai_model
    except Exception:
        key = (
            os.environ.get("AI_API_KEY")
            or os.environ.get("DEEPSEEK_API_KEY")
            or os.environ.get("OPENAI_API_KEY")
        )
        url = (
            os.environ.get("AI_BASE_URL")
            or os.environ.get("DEEPSEEK_BASE_URL")
            or os.environ.get("OPENAI_BASE_URL")
        )
        model = (
            os.environ.get("AI_MODEL")
            or os.environ.get("DEEPSEEK_MODEL")
            or os.environ.get("OPENAI_MODEL")
        )

    if not key or key.strip() == "your_api_key_here":
        return None, None, None
    return key, url, model


@pytest.mark.live
def test_production_llm_end_to_end_generation(tmp_path: Path):
    """Query production LLM, validate composition, and compile to Atari XEX executable."""
    api_key, base_url, model = _get_live_credentials()
    if not api_key:
        pytest.skip("Production API key not configured or set to placeholder.")

    try:
        import openai  # noqa: F401
    except ImportError:
        pytest.skip("openai package not installed.")

    req = CompositionRequest(
        style="dark dungeon exploration",
        bpm=88,
        channels=4,
        use_16bit_bass=True,
        duration_seconds=20,
    )

    doc = request_ai_composition(
        request=req,
        provider_name="openai",
        model=model,
        api_key=api_key,
        max_retries=2,
    )

    assert isinstance(doc, AICompositionDoc)
    assert doc.format == "atari-music-composition"
    assert doc.version == 1

    # Full report verification
    report = validate_composition_report(doc)
    assert report.valid is True
    assert len(report.issues) == 0

    # Pipeline verification: Music IR and POKEY IR
    res = generate_music_from_composition(doc)
    assert res.music_ir is not None
    assert res.pokey_ir is not None
    assert len(res.pokey_ir.patterns) >= 1

    # Analysis and fingerprinting verification
    from atari_music.ai.analysis import analyze_composition, composition_fingerprint
    fp = composition_fingerprint(doc)
    assert isinstance(fp, str) and len(fp) == 64

    analysis = analyze_composition(doc)
    assert analysis.rhythm.total_notes > 0
    assert analysis.structure.duration_seconds > 0.0
    assert analysis.pokey.channel_utilization is not None

    # End-to-end binary compilation
    xex_path = tmp_path / "live_test.xex"
    build_xex_from_composition(doc, output_path=xex_path)
    assert xex_path.exists()
    assert xex_path.stat().st_size > 500

    # Verify Atari DOS $FFFF binary header
    raw_bytes = xex_path.read_bytes()
    assert raw_bytes[0] == 0xFF and raw_bytes[1] == 0xFF

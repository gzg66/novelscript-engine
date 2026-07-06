from __future__ import annotations

import pytest

from novelscript.config import PROJECT_ROOT
from novelscript.stages.stage0_upstream import _pick_chapter_indices


def test_pick_chapter_indices_samples_spread() -> None:
    picks = _pick_chapter_indices(132)
    assert 0 in picks
    assert 131 in picks
    assert len(picks) <= 8


def test_stage0_prompts_exist() -> None:
    base = PROJECT_ROOT / "prompts" / "stage0_upstream"
    for name in ("outline.md", "characters.md", "brief.md"):
        assert (base / name).exists(), name

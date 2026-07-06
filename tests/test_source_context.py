from __future__ import annotations

import pytest

from novelscript.config import PROJECT_ROOT
from novelscript.pipeline.context import load_project
from novelscript.stages.source import SourceContextError, ensure_source_context, load_source_context
from novelscript.stages.stage0_upstream import build_novel_digest


def test_ensure_source_context_seeds_when_skip_llm(tmp_path) -> None:
    root = tmp_path / "empty"
    (root / "input").mkdir(parents=True)
    (root / "input" / "novel.txt").write_text("Chapter 1\n\nFreya wakes up.", encoding="utf-8")
    ctx = load_project(root)
    src = ensure_source_context(ctx, skip_llm=True)
    assert "Freya" in src["outline"]
    assert (root / "input" / "stage0" / "outline.md").exists()
    assert (root / "S0_adaptation_brief.md").exists()


def test_build_novel_digest(tmp_path) -> None:
    root = tmp_path / "novel"
    (root / "input").mkdir(parents=True)
    lines = ["Chapter 1\n\nOpening.\n"]
    for i in range(2, 21):
        lines.append(f"Chapter {i}\n\nBody {i}.\n")
    (root / "input" / "novel.txt").write_text("".join(lines), encoding="utf-8")
    ctx = load_project(root)
    digest, total = build_novel_digest(ctx)
    assert total == 20
    assert "Chapter 1" in digest
    assert "Chapter 20" in digest


def test_missing_novel_raises(tmp_path) -> None:
    root = tmp_path / "bad"
    (root / "input").mkdir(parents=True)
    ctx = load_project(root)
    with pytest.raises(SourceContextError):
        ensure_source_context(ctx, skip_llm=True)


def test_dragons_ice_live_has_source_context() -> None:
    ctx = load_project(PROJECT_ROOT / "projects" / "dragons-ice-live")
    src = load_source_context(ctx)
    assert src["brief"].strip()
    assert src["outline"].strip()

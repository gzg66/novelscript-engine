from __future__ import annotations

from novelscript.config import PROJECT_ROOT
from novelscript.pipeline.context import load_project
from novelscript.stages.source import load_chapter_range_excerpt, load_chapter_texts


def test_load_chapter_texts_includes_requested_chapters() -> None:
    ctx = load_project(PROJECT_ROOT / "projects" / "dragon-ice-132")
    excerpt = load_chapter_texts(ctx, [1, 2], max_chars_per_chapter=500, max_total_chars=2000)
    assert "### Chapter 1" in excerpt
    assert "### Chapter 2" in excerpt
    assert "blondie" in excerpt.lower() or "Freya" in excerpt


def test_load_chapter_range_excerpt() -> None:
    ctx = load_project(PROJECT_ROOT / "projects" / "dragon-ice-132")
    excerpt = load_chapter_range_excerpt(ctx, 1, 3, per_chapter_chars=400, max_total_chars=1500)
    assert "### Chapter 1" in excerpt
    assert "### Chapter 3" in excerpt

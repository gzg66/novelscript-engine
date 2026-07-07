from __future__ import annotations

import json
from pathlib import Path

from novelscript.config import PROJECT_ROOT
from novelscript.index.must_keep import build_must_keep_index
from novelscript.pipeline.context import init_project, load_project
from novelscript.pipeline.orchestrator import Pipeline
from novelscript.stages.source import (
    build_review_context,
    format_chapter_toc,
    format_must_keep_block,
    format_p1_source_block,
    format_source_block,
    load_episode_chapter_texts,
    load_must_keep_scenes,
    load_source_context,
)


def test_rebuild_must_keep_after_s0(tmp_path: Path) -> None:
    novel = PROJECT_ROOT / "input" / "novel.txt"
    root = tmp_path / "mk-proj"
    init_project(root, novel_src=novel)

    ctx = load_project(root)
    pipe = Pipeline(ctx)
    pipe._run_index()
    assert not (root / "index" / "must_keep_scenes.json").exists()

    engine = PROJECT_ROOT / "projects" / "full-run" / "S0_story_engine.md"
    (root / "S0_story_engine.md").write_text(engine.read_text(encoding="utf-8"), encoding="utf-8")
    pipe._rebuild_must_keep_index()
    mk_path = root / "index" / "must_keep_scenes.json"
    assert mk_path.exists()
    scenes = json.loads(mk_path.read_text(encoding="utf-8"))
    assert len(scenes) >= 10


def test_run_index_rebuilds_must_keep_when_s0_present(tmp_path: Path) -> None:
    novel = PROJECT_ROOT / "input" / "novel.txt"
    root = tmp_path / "mk-proj2"
    init_project(root, novel_src=novel)
    engine = PROJECT_ROOT / "projects" / "full-run" / "S0_story_engine.md"
    (root / "S0_story_engine.md").write_text(engine.read_text(encoding="utf-8"), encoding="utf-8")

    ctx = load_project(root)
    Pipeline(ctx)._run_index()
    scenes = json.loads((root / "index" / "must_keep_scenes.json").read_text(encoding="utf-8"))
    assert len(scenes) >= 10


def test_format_p1_source_block_includes_digest(tmp_path: Path) -> None:
    novel = PROJECT_ROOT / "input" / "novel.txt"
    root = tmp_path / "p1-proj"
    init_project(root, novel_src=novel)
    stage0 = root / "input" / "stage0"
    stage0.mkdir(parents=True, exist_ok=True)
    (stage0 / "outline.md").write_text("# 故事大纲\n\n## Logline\nTest\n", encoding="utf-8")
    (stage0 / "characters.md").write_text("# 角色库\n\n## 主角\nFreya\n", encoding="utf-8")
    (root / "S0_adaptation_brief.md").write_text("# 改编简报\n\n必保\n", encoding="utf-8")

    ctx = load_project(root)
    block = format_p1_source_block(ctx, load_source_context(ctx))
    assert "## 故事大纲" in block
    assert "## 全书正文抽样" in block
    assert "Chapter" in block


def test_load_episode_chapter_texts_scales_budget() -> None:
    ctx = load_project(PROJECT_ROOT / "projects" / "dragon-ice-132")
    short = load_episode_chapter_texts(ctx, [1, 2])
    long = load_episode_chapter_texts(ctx, list(range(1, 6)))
    assert len(long) > len(short)
    assert "…（截断）" not in short


def test_format_must_keep_block_filters_by_chapters() -> None:
    scenes = [
        {"id": 1, "name": "开篇", "source_chapters": [1, 2], "why_irreducible": "hook"},
        {"id": 2, "name": "终局", "source_chapters": [120, 121], "why_irreducible": "climax"},
    ]
    block = format_must_keep_block(scenes, season_id="S1", chapter_numbers=list(range(1, 31)))
    assert "开篇" in block
    assert "终局" not in block


def test_format_source_block_full_by_default() -> None:
    long_outline = "x" * 8000
    src = {"brief": "b", "outline": long_outline, "characters": "c", "novel_excerpt": "e"}
    block = format_source_block(src)
    assert len(block) > 7000
    compact = format_source_block(src, compact=True)
    assert len(compact) < len(block)


def test_format_chapter_toc_from_index(tmp_path: Path) -> None:
    from novelscript.index.chapters import index_novel
    from novelscript.pipeline.context import init_project

    novel = PROJECT_ROOT / "input" / "novel.txt"
    root = tmp_path / "toc-proj"
    init_project(root, novel_src=novel)
    index_novel(root / "input" / "novel.txt", root / "index")
    ctx = load_project(root)
    toc = format_chapter_toc(ctx)
    assert "章节目录" in toc
    assert "Ch1" in toc


def test_stage0_hash_invalidates_on_novel_change(tmp_path: Path) -> None:
    from novelscript.pipeline.context import init_project
    from novelscript.stages.source import persist_stage0_hash, stage0_cache_valid

    root = tmp_path / "hash-proj"
    (root / "input").mkdir(parents=True)
    novel = root / "input" / "novel.txt"
    novel.write_text("Chapter 1\n\nOriginal.\n", encoding="utf-8")
    init_project(root, novel_src=novel)
    stage0 = root / "input" / "stage0"
    stage0.mkdir(parents=True, exist_ok=True)
    (stage0 / "outline.md").write_text("# 故事大纲\n\n" + "x" * 300, encoding="utf-8")
    (stage0 / "characters.md").write_text("# 角色库\n\n" + "y" * 300, encoding="utf-8")
    (root / "S0_adaptation_brief.md").write_text("# 改编简报\n\n必保\n" + "z" * 300, encoding="utf-8")
    ctx = load_project(root)
    persist_stage0_hash(ctx)
    assert stage0_cache_valid(ctx)

    novel.write_text("Chapter 1\n\nChanged completely.\n", encoding="utf-8")
    ctx = load_project(root)
    assert not stage0_cache_valid(ctx)


def test_extract_must_keep_section() -> None:
    from novelscript.index.must_keep import extract_must_keep_section

    md = "## 名场面必保清单\n\n| # | 名场面 |\n|---|---|\n| 1 | 开篇 |\n\n## 其他\n"
    section = extract_must_keep_section(md)
    assert "开篇" in section
    assert "## 其他" not in section


def test_build_review_context_includes_must_keep() -> None:
    ctx = load_project(PROJECT_ROOT / "projects" / "full-run")
    build_must_keep_index(ctx.root / "S0_story_engine.md", ctx.index_dir)
    ctx = load_project(ctx.root)
    review_ctx = build_review_context(ctx, "s3_S1", "episode list prompt")
    assert "名场面必保" in review_ctx
    assert "episode list prompt" in review_ctx


def test_load_must_keep_scenes_from_project() -> None:
    ctx = load_project(PROJECT_ROOT / "projects" / "full-run")
    build_must_keep_index(ctx.root / "S0_story_engine.md", ctx.index_dir)
    scenes = load_must_keep_scenes(ctx)
    assert len(scenes) >= 10

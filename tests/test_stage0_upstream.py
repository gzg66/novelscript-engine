from __future__ import annotations

import pytest

from novelscript.config import PROJECT_ROOT
from novelscript.pipeline.context import load_project
from novelscript.stages.stage0_upstream import (
    _pick_chapter_indices,
    build_novel_digest,
    build_outline_source,
)


def test_pick_chapter_indices_samples_spread() -> None:
    picks = _pick_chapter_indices(132)
    assert 0 in picks
    assert 131 in picks
    assert len(picks) <= 8


def test_stage0_prompts_exist() -> None:
    base = PROJECT_ROOT / "prompts" / "stage0_upstream"
    for name in ("outline.md", "characters.md", "brief.md"):
        assert (base / name).exists(), name


def test_build_outline_source_covers_all_chapters(tmp_path) -> None:
    root = tmp_path / "novel"
    (root / "input").mkdir(parents=True)
    lines = ["Blurb about Freya.\n\n"]
    for i in range(1, 21):
        body = f"Event in chapter {i}. " + ("x" * 700)
        lines.append(f"Chapter {i}\n\n{body}\n")
    (root / "input" / "novel.txt").write_text("".join(lines), encoding="utf-8")
    ctx = load_project(root)
    source, total = build_outline_source(ctx, per_chapter_chars=600)
    assert total == 20
    assert "Blurb about Freya" in source
    assert "### Chapter 1\n" in source
    assert "### Chapter 20\n" in source
    assert "Event in chapter 12" in source


def test_build_novel_digest_samples_only(tmp_path) -> None:
    root = tmp_path / "novel"
    (root / "input").mkdir(parents=True)
    lines = []
    for i in range(1, 21):
        lines.append(f"Chapter {i}\n\nBody {i}.\n")
    (root / "input" / "novel.txt").write_text("".join(lines), encoding="utf-8")
    ctx = load_project(root)
    digest, total = build_novel_digest(ctx)
    assert total == 20
    assert "### Chapter 1" in digest
    assert "### Chapter 20" in digest
    assert "章节目录与摘要" not in digest


def test_run_stage0_upstream_uses_emit_without_name_error(tmp_path, monkeypatch) -> None:
    from novelscript.config import load_settings
    from novelscript.stages import stage0_upstream

    root = tmp_path / "proj"
    (root / "input").mkdir(parents=True)
    (root / "project.meta.json").write_text('{"mode": "M1"}', encoding="utf-8")
    (root / "input" / "novel.txt").write_text(
        "".join(f"Chapter {i}\n\nEvent {i}.\n" for i in range(1, 11)),
        encoding="utf-8",
    )
    ctx = load_project(root)

    monkeypatch.setattr("novelscript.stages.source.stage0_cache_valid", lambda _ctx: False)
    monkeypatch.setattr("novelscript.stages.source.persist_stage0_hash", lambda _ctx: None)

    def fake_generate(**kwargs) -> None:
        out_path = kwargs["out_path"]
        out_path.parent.mkdir(parents=True, exist_ok=True)
        name = out_path.name
        if name == "outline.md":
            out_path.write_text("Logline: test\n章节组\n" + ("x" * 900), encoding="utf-8")
        elif name == "characters.md":
            out_path.write_text("role=hero\n" + ("y" * 600), encoding="utf-8")

    monkeypatch.setattr(stage0_upstream, "_generate_step", fake_generate)

    result = stage0_upstream.run_stage0_upstream(ctx, load_settings())
    assert result["status"] == "ok"
    assert (root / "input" / "stage0" / "outline.md").exists()
    assert not (root / "S0_adaptation_brief.md").exists()


def test_run_stage0_upstream_skips_completed_steps(tmp_path, monkeypatch) -> None:
    from novelscript.config import load_settings
    from novelscript.stages import stage0_upstream

    root = tmp_path / "proj"
    stage0 = root / "input" / "stage0"
    stage0.mkdir(parents=True)
    (root / "project.meta.json").write_text('{"mode": "M1"}', encoding="utf-8")
    (root / "input" / "novel.txt").write_text("Chapter 1\n\nEvent.\n", encoding="utf-8")
    (stage0 / "outline.md").write_text("Logline: cached\n章节组\n" + ("x" * 900), encoding="utf-8")
    ctx = load_project(root)

    monkeypatch.setattr("novelscript.stages.source.stage0_cache_valid", lambda _ctx: False)
    monkeypatch.setattr("novelscript.stages.source.persist_stage0_hash", lambda _ctx: None)

    called: list[str] = []

    def fake_generate(**kwargs) -> None:
        out_path = kwargs["out_path"]
        out_path.parent.mkdir(parents=True, exist_ok=True)
        called.append(out_path.name)
        if out_path.name == "characters.md":
            out_path.write_text("role=hero\n" + ("y" * 600), encoding="utf-8")

    monkeypatch.setattr(stage0_upstream, "_generate_step", fake_generate)

    result = stage0_upstream.run_stage0_upstream(ctx, load_settings())
    assert result["status"] == "ok"
    assert "outline.md" not in called
    assert "characters.md" in called
    assert "S0_adaptation_brief.md" not in called

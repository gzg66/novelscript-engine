from __future__ import annotations

from pathlib import Path

from novelscript.config import PROJECT_ROOT
from novelscript.pipeline.context import ensure_project, project_root_for_novel, slug_from_novel
from novelscript.pipeline.orchestrator import Pipeline

SAMPLE = PROJECT_ROOT / "projects" / "full-run"


def test_slug_from_novel() -> None:
    assert slug_from_novel(Path("Dragon's Ice.txt")) == "dragon-s-ice"
    assert slug_from_novel(Path("novel.txt")) == "novel"
    assert slug_from_novel(Path("projects/dragons-ice/input/novel.txt")) == "dragons-ice"


def test_project_root_for_novel() -> None:
    root = project_root_for_novel(Path("/tmp/Dragon Ice.txt"))
    assert root.name == "dragon-ice"


def test_ensure_project_creates_dir(tmp_path: Path) -> None:
    novel = tmp_path / "sample.txt"
    novel.write_text("Chapter 1\n\nHello world.", encoding="utf-8")
    stage0 = tmp_path / "stage0"
    stage0.mkdir()
    (stage0 / "outline.md").write_text("# Outline\nTest", encoding="utf-8")

    project = tmp_path / "projects" / "sample"
    ctx = ensure_project(novel, project_root=project)
    assert ctx.root == project
    assert (project / "input" / "novel.txt").exists()
    assert (project / "input" / "stage0" / "outline.md").read_text(encoding="utf-8")


def test_auto_approve_continues_past_s2(tmp_path: Path) -> None:
    import shutil

    novel = PROJECT_ROOT / "input" / "novel.txt"
    project = tmp_path / "run"
    ctx = ensure_project(novel, project_root=project)
    for name in ("S0_story_engine.md", "S1_series_premise.md", "S1_character_bible.md", "S2_season_map.md"):
        shutil.copy2(SAMPLE / name, project / name)
    pipe = Pipeline(ctx)
    result = pipe.run(through="S3", skip_llm=True, auto_approve=True)
    assert "blocked" not in result
    assert (project / "approved" / "S2.approved").exists()


def test_wait_approval_blocks_at_s2(tmp_path: Path) -> None:
    import shutil

    novel = PROJECT_ROOT / "input" / "novel.txt"
    project = tmp_path / "run-wait"
    ctx = ensure_project(novel, project_root=project)
    shutil.copy2(SAMPLE / "S2_season_map.md", project / "S2_season_map.md")
    pipe = Pipeline(ctx)
    result = pipe.run(through="S3", skip_llm=True, auto_approve=False)
    assert "blocked" in result
    assert "等待人工审批" in result["blocked"]

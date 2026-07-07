from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

WEB_DIR = Path(__file__).resolve().parents[1] / "web"
SPEC = importlib.util.spec_from_file_location("web_server", WEB_DIR / "server.py")
assert SPEC and SPEC.loader
web_server = importlib.util.module_from_spec(SPEC)
sys.modules["web_server"] = web_server
SPEC.loader.exec_module(web_server)


def _make_project(projects_dir: Path, slug: str) -> Path:
    root = projects_dir / slug
    root.mkdir(parents=True)
    (root / "input").mkdir()
    (root / "index").mkdir()
    (root / "runs").mkdir()
    (root / "input" / "novel.txt").write_text("Chapter 1\n\nFreya wakes.\n" * 20, encoding="utf-8")
    (root / "project.meta.json").write_text(
        json.dumps({"mode": "M1", "display_title": f"Title {slug}"}, ensure_ascii=False),
        encoding="utf-8",
    )
    return root


def _seed_stage0(project: Path) -> None:
    stage0 = project / "input" / "stage0"
    stage0.mkdir(parents=True, exist_ok=True)
    (stage0 / "outline.md").write_text(
        "# 故事大纲\n\n## Logline\nTest line\n\n## 章节组 Beats\n### 第 1 章\n" + "x" * 800,
        encoding="utf-8",
    )
    (stage0 / "characters.md").write_text(
        "### Hero — lead (id=`hero`, role=`protagonist`)\n" + "y" * 500,
        encoding="utf-8",
    )
    (project / "S0_adaptation_brief.md").write_text(
        "竖屏\n必保\n季间叙事原则\n" + "z" * 400,
        encoding="utf-8",
    )
    meta = json.loads((project / "project.meta.json").read_text(encoding="utf-8"))
    meta["stage0_novel_hash"] = "test-hash"
    (project / "project.meta.json").write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")


@pytest.fixture
def projects_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    root = tmp_path / "projects"
    root.mkdir()
    monkeypatch.setattr(web_server, "PROJECTS_DIR", root)
    return root


def test_run_stage_p1_only_regenerates_p1(projects_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    slug = "p1-rerun"
    root = _make_project(projects_dir, slug)
    _seed_stage0(root)
    cards = root / "source_cards"
    cards.mkdir()
    (cards / "index.md").write_text("# old cards\n", encoding="utf-8")
    outline_before = (root / "input" / "stage0" / "outline.md").read_text(encoding="utf-8")

    stage0_calls: list[str] = []
    ensure_calls: list[str] = []

    def fake_stage0(*_args, **_kwargs):
        stage0_calls.append("called")
        return {"status": "cached"}

    def fake_ensure(*_args, **_kwargs):
        ensure_calls.append("called")
        return {}

    def fake_p1(ctx, settings, *, skip_llm=False):
        out = ctx.root / "source_cards" / "index.md"
        out.parent.mkdir(exist_ok=True)
        out.write_text("# new cards\n", encoding="utf-8")
        return {"status": "ok"}

    monkeypatch.setattr("novelscript.stages.stage0_upstream.run_stage0_upstream", fake_stage0)
    monkeypatch.setattr("novelscript.stages.source.ensure_source_context", fake_ensure)
    monkeypatch.setattr("novelscript.stages.pre_pipeline.run_p1_source_cards", fake_p1)

    web_server._run_stage(slug, "P1", skip_llm=False)

    assert stage0_calls == []
    assert ensure_calls == []
    assert (root / "source_cards" / "index.md").read_text(encoding="utf-8") == "# new cards\n"
    assert (root / "input" / "stage0" / "outline.md").read_text(encoding="utf-8") == outline_before


def test_run_stage_s0_only_regenerates_engine(projects_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    slug = "s0-rerun"
    root = _make_project(projects_dir, slug)
    _seed_stage0(root)
    (root / "S0_story_engine.md").write_text("# old engine\n", encoding="utf-8")
    outline_before = (root / "input" / "stage0" / "outline.md").read_text(encoding="utf-8")

    ensure_calls: list[str] = []

    def fake_ensure(*_args, **_kwargs):
        ensure_calls.append("called")
        return {}

    def fake_s0(ctx, settings):
        (ctx.root / "S0_story_engine.md").write_text("# new engine\n", encoding="utf-8")
        return {"status": "ok"}

    monkeypatch.setattr("novelscript.stages.source.ensure_source_context", fake_ensure)
    monkeypatch.setattr("novelscript.stages.run_s0_engine", fake_s0)

    web_server._run_stage(slug, "S0", skip_llm=False)

    assert ensure_calls == []
    assert (root / "S0_story_engine.md").read_text(encoding="utf-8") == "# new engine\n"
    assert (root / "input" / "stage0" / "outline.md").read_text(encoding="utf-8") == outline_before


def test_run_stage_p3_only_regenerates_p3(projects_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    slug = "p3-rerun"
    root = _make_project(projects_dir, slug)
    _seed_stage0(root)
    (root / "S0_story_engine.md").write_text("# engine\n", encoding="utf-8")
    (root / "adaptation_strategy.md").write_text("# old strategy\n", encoding="utf-8")
    (root / "S1_series_premise.md").write_text("# downstream premise\n", encoding="utf-8")
    (root / "S2_season_map.md").write_text("# downstream s2\n", encoding="utf-8")

    ensure_calls: list[str] = []

    def fake_ensure(*_args, **_kwargs):
        ensure_calls.append("called")
        return {}

    def fake_p3(ctx, settings, *, skip_llm=False):
        (ctx.root / "adaptation_strategy.md").write_text("# new strategy\n", encoding="utf-8")
        return {"status": "ok"}

    monkeypatch.setattr("novelscript.stages.source.ensure_source_context", fake_ensure)
    monkeypatch.setattr("novelscript.stages.pre_pipeline.run_p3_strategy", fake_p3)

    web_server._run_stage(slug, "P3", skip_llm=False)

    assert ensure_calls == []
    assert (root / "adaptation_strategy.md").read_text(encoding="utf-8") == "# new strategy\n"
    assert not (root / "S1_series_premise.md").exists()
    assert not (root / "S2_season_map.md").exists()


def test_run_stage_p1_invalidates_downstream_engine(projects_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    slug = "p1-cascade"
    root = _make_project(projects_dir, slug)
    _seed_stage0(root)
    (root / "S0_story_engine.md").write_text("# engine\n", encoding="utf-8")
    (root / "adaptation_strategy.md").write_text("# strategy\n", encoding="utf-8")

    def fake_p1(ctx, settings, *, skip_llm=False):
        out = ctx.root / "source_cards" / "index.md"
        out.parent.mkdir(exist_ok=True)
        out.write_text("# new cards\n", encoding="utf-8")
        return {"status": "ok"}

    monkeypatch.setattr("novelscript.stages.pre_pipeline.run_p1_source_cards", fake_p1)

    web_server._run_stage(slug, "P1", skip_llm=False)

    assert not (root / "S0_story_engine.md").exists()
    assert not (root / "adaptation_strategy.md").exists()


def test_run_stage_s2_invalidates_s3_episodes(projects_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    slug = "s2-cascade"
    root = _make_project(projects_dir, slug)
    _seed_stage0(root)
    (root / "S0_story_engine.md").write_text("# engine\n", encoding="utf-8")
    (root / "S1_series_premise.md").write_text("# premise\n", encoding="utf-8")
    (root / "S2_season_map.md").write_text("# old s2\n", encoding="utf-8")
    s3 = root / "seasons" / "s1"
    s3.mkdir(parents=True)
    (s3 / "episode_list.md").write_text("# old s3 episodes\n", encoding="utf-8")

    def fake_s2(ctx, settings):
        (ctx.root / "S2_season_map.md").write_text("# new s2\n", encoding="utf-8")
        return {"status": "ok"}

    monkeypatch.setattr("novelscript.stages.run_s2_season_map", fake_s2)

    web_server._run_stage(slug, "S2", skip_llm=False)

    assert (root / "S2_season_map.md").read_text(encoding="utf-8") == "# new s2\n"
    assert not (s3 / "episode_list.md").exists()
    assert (root / "S1_series_premise.md").read_text(encoding="utf-8") == "# premise\n"


def test_normalize_stage_id_accepts_brief_and_stage0() -> None:
    assert web_server._normalize_stage_id("brief") == "brief"
    assert web_server._normalize_stage_id("BRIEF") == "brief"
    assert web_server._normalize_stage_id("stage0") == "stage0"
    assert web_server._normalize_stage_id("STAGE0") == "stage0"
    assert web_server._normalize_stage_id("P1") == "P1"

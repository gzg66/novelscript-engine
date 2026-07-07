from __future__ import annotations

import json
from pathlib import Path

from novelscript.pipeline.context import load_project
from novelscript.pipeline.stage_deps import (
    compute_input_hashes,
    downstream_stages,
    invalidate_downstream,
    persist_stage_hashes,
    stage_inputs_valid,
)


def _make_ctx(tmp_path: Path):
    root = tmp_path / "proj"
    root.mkdir()
    (root / "input").mkdir()
    (root / "index").mkdir()
    (root / "source_cards").mkdir()
    (root / "input" / "novel.txt").write_text("Chapter 1\n\nBody\n" * 50, encoding="utf-8")
    stage0 = root / "input" / "stage0"
    stage0.mkdir(parents=True)
    (stage0 / "outline.md").write_text("# outline\n" + "x" * 300, encoding="utf-8")
    (stage0 / "characters.md").write_text("role=hero\n" + "y" * 300, encoding="utf-8")
    (root / "project_preference.md").write_text("# pref\n", encoding="utf-8")
    (root / "source_cards" / "index.json").write_text('{"must_keep":[]}', encoding="utf-8")
    (root / "S0_story_engine.md").write_text("# engine v1\n", encoding="utf-8")
    (root / "S0_adaptation_brief.md").write_text("竖屏\n季间叙事原则\n全剧规模\n" + "z" * 400, encoding="utf-8")
    (root / "adaptation_strategy.md").write_text("# strategy v1\n", encoding="utf-8")
    (root / "S1_series_premise.md").write_text("# premise\n", encoding="utf-8")
    (root / "index" / "must_keep_scenes.json").write_text("[]", encoding="utf-8")
    (root / "project.meta.json").write_text("{}", encoding="utf-8")
    return load_project(root)


def test_stage_inputs_valid_detects_upstream_change(tmp_path: Path) -> None:
    ctx = _make_ctx(tmp_path)
    persist_stage_hashes(ctx, "S0")
    assert stage_inputs_valid(ctx, "S0")

    (ctx.root / "source_cards" / "index.json").write_text('{"must_keep":[{"id":"mk_001"}]}', encoding="utf-8")
    assert not stage_inputs_valid(ctx, "S0")


def test_invalidate_downstream_removes_files_and_hashes(tmp_path: Path) -> None:
    ctx = _make_ctx(tmp_path)
    persist_stage_hashes(ctx, "P3")
    persist_stage_hashes(ctx, "S1")
    s1 = ctx.root / "S1_series_premise.md"
    assert s1.exists()

    removed = invalidate_downstream(ctx, "P3")
    assert not s1.exists()
    assert "S1_series_premise.md" in removed
    assert "S1" not in (ctx.meta.get("stage_input_hashes") or {})


def test_invalidate_p1_cascades_to_s0_brief_p3(tmp_path: Path) -> None:
    ctx = _make_ctx(tmp_path)
    removed = invalidate_downstream(ctx, "P1")
    assert not (ctx.root / "S0_story_engine.md").exists()
    assert not (ctx.root / "S0_adaptation_brief.md").exists()
    assert not (ctx.root / "adaptation_strategy.md").exists()
    assert "S0_story_engine.md" in removed


def test_downstream_stages_order() -> None:
    ds = downstream_stages("P1")
    assert ds[:4] == ["S0", "brief", "P3", "S1"]


def test_compute_input_hashes_keys(tmp_path: Path) -> None:
    ctx = _make_ctx(tmp_path)
    hashes = compute_input_hashes(ctx)
    assert hashes["source_cards_hash"]
    assert hashes["s0_engine_hash"]
    assert hashes["must_keep_hash"]


def test_format_source_cards_summary_includes_rulings(tmp_path: Path) -> None:
    from novelscript.stages.source import format_source_cards_summary

    ctx = _make_ctx(tmp_path)
    (ctx.root / "source_cards" / "index.json").write_text(
        json.dumps(
            {
                "must_keep": [{"id": "mk_001", "title": "献丝带", "source_ref": "Ch7"}],
                "redundant": [{"id": "red_001", "title": "注水章", "source_ref": "Ch15"}],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (ctx.root / "S0_story_engine.md").write_text(
        """## 素材裁决表
| card_id | 裁决 | 理由 | 服务引擎 |
|---|---|---|---|
| mk_001 | 保留 | 核心 | 引擎2 |
| red_001 | 删除 | 冗余 | — |
""",
        encoding="utf-8",
    )
    summary = format_source_cards_summary(ctx)
    assert "mk_001" in summary
    assert "保留" in summary
    assert "引擎2" in summary

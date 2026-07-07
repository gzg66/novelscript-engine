from __future__ import annotations

from pathlib import Path

import pytest

from novelscript.audit.decision_log import append_decision, load_decisions, load_decision_queue, save_decision_queue
from novelscript.checkers.p0 import check_project_preference
from novelscript.checkers.p1 import check_source_cards, parse_source_cards_md
from novelscript.checkers.p3 import check_adaptation_strategy
from novelscript.pipeline.context import load_project
from novelscript.stages.pre_pipeline import _default_preference, build_decision_queue_from_s2, run_p0_preference
from novelscript.stages.source import SourceContextError


def test_p0_checker_passes_default() -> None:
    from novelscript.pipeline.context import ProjectContext

    ctx = ProjectContext(root=Path("dragon-ice"))
    md = _default_preference(ctx)
    report = check_project_preference(md)
    assert report.passed, report.issues


def test_p0_gate1_mode_unclear() -> None:
    md = """# 项目偏好 · Test

## 改写档位
随便改改

## 忠实对象
- 主线情节功能

## 目标形态
竖屏短剧

## 口味旋钮
- **节奏**：前 3 集强钩子闭环，单集 5–7 场戏
- **主角主动性**：每集至少 2 个主动 Beat
- **感情线**：加强拉扯，台词去油
- **世界观**：少解释，用视觉外化
- **内容边界**：不做低俗擦边

## 禁区
- 女主核心识别点不可改
"""
    report = check_project_preference(md)
    assert not report.passed
    assert any("Gate1" in i for i in report.issues)


def test_p0_gate2_fidelity_missing() -> None:
    md = """# 项目偏好 · Test

## 改写档位
精编生产（M1）

## 忠实对象
- 观众要觉得好看

## 目标形态
竖屏短剧

## 口味旋钮
- **节奏**：前 3 集强钩子闭环，单集 5–7 场戏
- **主角主动性**：每集至少 2 个主动 Beat
- **感情线**：加强拉扯，台词去油
- **世界观**：少解释，用视觉外化
- **内容边界**：不做低俗擦边

## 禁区
- 女主核心识别点不可改
"""
    report = check_project_preference(md)
    assert not report.passed
    assert any("Gate2" in i for i in report.issues)


def test_p0_gate3_taste_conflict() -> None:
    md = """# 项目偏好 · Test

## 改写档位
精编生产（M1）· 保主线

## 忠实对象
- 单本主线与名场面功能

## 目标形态
竖屏短剧

## 口味旋钮
- **节奏**：慢节奏铺垫为主，同时每集高密度爽点反转
- **主角主动性**：每集至少 2 个主动 Beat
- **感情线**：加强拉扯，台词去油
- **世界观**：零设定倾倒，同时详细世界观解说
- **内容边界**：不做低俗擦边

## 禁区
- 女主核心识别点不可改
"""
    report = check_project_preference(md)
    assert not report.passed
    assert any("Gate3" in i for i in report.issues)


def test_p0_gate4_forbidden_vague() -> None:
    md = """# 项目偏好 · Test

## 改写档位
精编生产（M1）· 保主线

## 忠实对象
- 单本主线与名场面功能

## 目标形态
竖屏短剧

## 口味旋钮
- **节奏**：前 3 集强钩子闭环，单集 5–7 场戏
- **主角主动性**：每集至少 2 个主动 Beat
- **感情线**：加强拉扯，台词去油
- **世界观**：少解释，用视觉外化
- **内容边界**：不做低俗擦边

## 禁区
- 要精彩好看
"""
    report = check_project_preference(md)
    assert not report.passed
    assert any("Gate4" in i for i in report.issues)


def test_p0_user_prompt_includes_full_novel(tmp_path: Path) -> None:
    root = tmp_path / "proj"
    (root / "input").mkdir(parents=True)
    novel = "Chapter 1\n\nFreya wakes in a strange room.\n"
    (root / "input" / "novel.txt").write_text(novel, encoding="utf-8")
    ctx = load_project(root)
    novel_text = ctx.novel_path().read_text(encoding="utf-8")
    assert "Freya" in novel_text
    assert novel_text == novel


def test_p0_requires_novel(tmp_path: Path) -> None:
    root = tmp_path / "empty"
    (root / "input").mkdir(parents=True)
    ctx = load_project(root)
    with pytest.raises(SourceContextError, match="P0 需要小说原文"):
        run_p0_preference(ctx, settings=None, skip_llm=False)


def test_p3_checker_minimal() -> None:
    md = """# 创作策略 · Test

## 创作策略卡
- **主引擎**：逆袭

## 允许改动
- 合并章节

## 禁止改动
- 女主识别点

## 主要风险
- 原著粉偏离
"""
    assert check_adaptation_strategy(md).passed


def test_source_cards_parse() -> None:
    md = """# 素材卡

## 事件卡
| id | 标题 | 原文位置 | 戏剧功能 | 可动性 |
|---|---|---|---|---|
""" + "\n".join(
        f"| evt_{i:03d} | 事件{i} | Ch{i} | 逆袭 | 不可删 |" for i in range(1, 16)
    ) + """

## 名场面卡
| id | 名场面 | 原文位置 | 情绪功能 | 不可压缩原因 |
|---|---|---|---|---|
| mk_001 | 献丝带 | Ch7 | 双男主 | 主动性 |

## 冗余卡
| id | 支线 | 原文位置 | 低功能原因 | 建议处理 |
|---|---|---|---|---|
| red_001 | 重复升级 | Ch20 | 重复 | 删除 |

## 角色卡
| id | 角色 | 定位 | 核心欲望 | 戏剧功能 |
|---|---|---|---|---|
| chr_001 | Freya | 主角 | 回家 | 逆袭 |
| chr_002 | A | 男主 | x | y |
| chr_003 | B | 男主 | x | y |
"""
    cards = parse_source_cards_md(md)
    assert len(cards["events"]) >= 10
    assert len(cards["characters"]) >= 3
    assert cards["must_keep"][0]["id"] == "mk_001"
    assert check_source_cards(md).passed


def test_decision_log_append(tmp_path: Path) -> None:
    audit = tmp_path / "audit"
    append_decision(audit, {"source_ref": "Ch7", "adaptation_action": "前置", "dramatic_reason": "补爱情线"})
    rows = load_decisions(audit)
    assert len(rows) == 1
    assert rows[0]["source_ref"] == "Ch7"


def test_decision_queue_from_s2(tmp_path: Path) -> None:
    from novelscript.pipeline.context import ProjectContext

    (tmp_path / "S2_season_map.md").write_text(
        "S1|S2 断点 Ch30\n献丝带名场面\n",
        encoding="utf-8",
    )
    ctx = ProjectContext(root=tmp_path)
    items = build_decision_queue_from_s2(ctx)
    assert len(items) >= 1
    save_decision_queue(tmp_path / "audit", items)
    assert len(load_decision_queue(tmp_path / "audit")) >= 1


def test_reviewer_fails_safe_on_bad_json() -> None:
    from novelscript.gates.reviewer import _parse_review

    result = _parse_review("not json at all")
    assert result.verdict == "revise"
    assert result.issues


def test_resolve_decision(tmp_path: Path) -> None:
    from novelscript.audit.decision_log import load_decisions, resolve_decision

    audit = tmp_path / "audit"
    save_decision_queue(
        audit,
        [{"id": "dq_test", "question": "Q?", "status": "pending", "recommendation": "A ok", "options": ["A ok"]}],
    )
    resolved = resolve_decision(audit, "dq_test", choice="A ok")
    assert resolved is not None
    assert resolved["status"] == "resolved"
    queue = load_decision_queue(audit)
    assert queue[0]["resolved_choice"] == "A ok"
    assert len(load_decisions(audit)) == 1

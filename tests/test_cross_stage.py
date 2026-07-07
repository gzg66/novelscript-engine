from __future__ import annotations

from novelscript.checkers.cross_stage import (
    check_p1_s0_rulings,
    check_s1_brief_season_keywords,
    check_s2_must_keep_coverage,
    run_cross_stage_checks,
)


def test_p1_s0_rulings_all_mk_covered() -> None:
    cards = {
        "must_keep": [
            {"id": "mk_001", "title": "A"},
            {"id": "mk_002", "title": "B"},
        ]
    }
    engine = """## 素材裁决表
| card_id | 裁决 | 理由 | 服务引擎 |
|---|---|---|---|
| mk_001 | 保留 | x | 引擎1 |
| mk_002 | 保留 | y | 引擎2 |
"""
    report = check_p1_s0_rulings(cards, engine)
    assert report.passed, report.issues


def test_p1_s0_rulings_missing_mk() -> None:
    cards = {"must_keep": [{"id": "mk_001", "title": "A"}]}
    engine = "## 素材裁决表\n| card_id | 裁决 | 理由 | 服务引擎 |\n|---|---|---|---|\n"
    report = check_p1_s0_rulings(cards, engine)
    assert not report.passed


def test_s2_must_keep_coverage() -> None:
    must_keep = [{"card_id": "mk_001", "name": "献丝带"}]
    s2 = "## 名场面落点\n| 名场面 | 季 | 集 |\n|---|---|---|\n| 献丝带 mk_001 | S1 | EP03 |\n"
    report = check_s2_must_keep_coverage(s2, must_keep)
    assert report.passed, report.issues


def test_s1_brief_season_count() -> None:
    brief = "## 目标形态硬约束\n| 全剧规模 | 5 季 × 24 集 |\n## 季间叙事原则\n每季末钩子\n"
    s1 = """## 主角逐季蜕变
| 季 | 季初 | 季末变成谁 |
|---|---|---|
| **S1** | a | b |
| **S2** | c | d |
| **S3** | e | f |
| **S4** | g | h |
| **S5** | i | j |
"""
    report = check_s1_brief_season_keywords(brief, s1)
    assert report.passed, report.issues


def test_run_cross_stage_checks_merged() -> None:
    cards = {"must_keep": [{"id": "mk_001", "title": "A"}]}
    engine = """## 素材裁决表
| card_id | 裁决 | 理由 | 服务引擎 |
|---|---|---|---|
| mk_001 | 保留 | r | 引擎1 |
"""
    report = run_cross_stage_checks(cards=cards, engine_md=engine)
    assert report.passed, report.issues

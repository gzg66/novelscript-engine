from __future__ import annotations

import pytest

from novelscript.checkers.s1 import check_s1_premise
from novelscript.checkers.s2 import check_s2_season_map_md, parse_season_map_md
from novelscript.config import PROJECT_ROOT
from novelscript.index.season_plan import (
    check_adaptation_brief,
    check_cross_stage_season_consistency,
    count_s1_season_arc_rows,
    infer_season_count,
    parse_adaptation_brief,
    resolve_season_count,
)

SAMPLE = PROJECT_ROOT / "projects" / "full-run"

GOOD_BRIEF = """\
# 改编简报 · Test → 竖屏短剧

## 目标形态硬约束

| 维度 | 约束 |
|---|---|
| 单季集数 | 20–30 集 |
| 全剧规模 | 5 季 × 24 集 ≈ 120 集（多季连载） |

## 季间叙事原则

- 每季末强钩子。
- 危机升级递进。

## 必保清单

1. 场面 A
"""


BAD_SINGLE_SEASON_BRIEF = """\
# 改编简报 · Bad

## 目标形态硬约束

| 维度 | 约束 |
|---|---|
| 单季集数 | 80–100 集 |
| 全剧规模 | 单季完结 |

## 必保清单

1. x
"""


def test_infer_season_count_132_chapters() -> None:
    assert infer_season_count(132) == 5
    assert infer_season_count(80) == 4
    assert infer_season_count(40) == 2


def test_parse_adaptation_brief_extracts_season_count() -> None:
    plan = parse_adaptation_brief(GOOD_BRIEF)
    assert plan["season_count"] == 5
    assert plan["episodes_per_season_min"] == 20
    assert plan["episodes_per_season_max"] == 30
    assert plan["has_inter_season_principle"] is True
    assert plan["is_single_season_finale"] is False


def test_parse_adaptation_brief_flags_single_season_finale() -> None:
    plan = parse_adaptation_brief(BAD_SINGLE_SEASON_BRIEF)
    assert plan["is_single_season_finale"] is True


def test_check_adaptation_brief_rejects_single_season() -> None:
    report = check_adaptation_brief(BAD_SINGLE_SEASON_BRIEF, total_chapters=132)
    assert not report.passed
    assert any("单季完结" in issue for issue in report.issues)


def test_check_adaptation_brief_accepts_good_brief() -> None:
    report = check_adaptation_brief(GOOD_BRIEF, total_chapters=132)
    assert report.passed, report.issues


def test_resolve_season_count_from_brief_or_infer() -> None:
    assert resolve_season_count(brief_md=GOOD_BRIEF, total_chapters=132) == 5
    assert resolve_season_count(brief_md="", total_chapters=132) == 5


def test_cross_stage_season_consistency_full_run() -> None:
    brief = (SAMPLE / "S0_adaptation_brief.md").read_text(encoding="utf-8")
    s1 = (SAMPLE / "S1_series_premise.md").read_text(encoding="utf-8")
    s2 = (SAMPLE / "S2_season_map.md").read_text(encoding="utf-8")
    report = check_cross_stage_season_consistency(
        brief_md=brief,
        s1_md=s1,
        s2_md=s2,
        total_chapters=132,
    )
    assert report.passed, report.issues
    assert count_s1_season_arc_rows(s1) == 5
    assert len(parse_season_map_md(s2)) == 5


def test_s1_premise_requires_exact_season_rows() -> None:
    s1 = (SAMPLE / "S1_series_premise.md").read_text(encoding="utf-8")
    assert check_s1_premise(s1, expected_seasons=5).passed
    assert not check_s1_premise(s1, expected_seasons=4).passed


def test_s2_checker_validates_breakpoint_section() -> None:
    s2 = (SAMPLE / "S2_season_map.md").read_text(encoding="utf-8")
    report = check_s2_season_map_md(s2, total_chapters=132, expected_seasons=5)
    assert report.passed, report.issues


def test_parse_brief_ignores_prohibition_mention_of_single_season() -> None:
    text = GOOD_BRIEF + "\n- 禁止「单季完结」大包大揽。\n"
    plan = parse_adaptation_brief(text)
    assert not plan["is_single_season_finale"]


def test_dragon_ice_brief_not_single_season_finale() -> None:
    path = PROJECT_ROOT / "projects" / "dragon-ice" / "S0_adaptation_brief.md"
    if not path.exists():
        pytest.skip("dragon-ice fixture missing")
    text = path.read_text(encoding="utf-8")
    plan = parse_adaptation_brief(text)
    assert not plan["is_single_season_finale"]
    assert plan["season_count"] == 5
    report = check_adaptation_brief(text, total_chapters=132)
    assert report.passed, report.issues

from __future__ import annotations

from pathlib import Path

import pytest

from novelscript.checkers.s2 import check_s2_season_map, parse_season_map_md
from novelscript.checkers.s3 import check_s3_episode_list, parse_episode_list_md
from novelscript.checkers.s5 import check_s5_script, parse_script_md
from novelscript.config import PROJECT_ROOT


SAMPLE = PROJECT_ROOT / "projects" / "full-run"


@pytest.fixture
def s2_md() -> str:
    return (SAMPLE / "S2_season_map.md").read_text(encoding="utf-8")


@pytest.fixture
def s3_md() -> str:
    path = SAMPLE / "seasons" / "s1" / "episode_list.md"
    if not path.exists():
        path = SAMPLE / "S3_episode_list_s1.md"
    return path.read_text(encoding="utf-8")


@pytest.fixture
def s5_md() -> str:
    return (SAMPLE / "seasons" / "s1" / "ep01" / "script.md").read_text(encoding="utf-8")


def test_s0_checker_passes_sample() -> None:
    from novelscript.checkers.s0 import check_s0_story_engine

    md = (PROJECT_ROOT / "projects" / "full-run" / "S0_story_engine.md").read_text(encoding="utf-8")
    report = check_s0_story_engine(md)
    assert report.passed, report.issues


def test_s1_checker_passes_sample() -> None:
    from novelscript.checkers.s1 import check_s1_bible, check_s1_premise

    sample = PROJECT_ROOT / "projects" / "full-run"
    assert check_s1_premise((sample / "S1_series_premise.md").read_text(encoding="utf-8")).passed
    assert check_s1_bible((sample / "S1_character_bible.md").read_text(encoding="utf-8")).passed


def test_parse_s2_seasons(s2_md: str) -> None:
    seasons = parse_season_map_md(s2_md)
    assert len(seasons) == 5
    assert seasons[0]["season_id"] == "S1"


def test_check_s2(s2_md: str) -> None:
    seasons = parse_season_map_md(s2_md)
    report = check_s2_season_map(seasons, total_chapters=132, expected_seasons=5)
    assert report.passed, report.issues


def test_parse_s3_episodes(s3_md: str) -> None:
    episodes = parse_episode_list_md(s3_md)
    assert len(episodes) == 26
    assert episodes[0]["episode_id"] == "S1E01"


def test_check_s3(s3_md: str) -> None:
    episodes = parse_episode_list_md(s3_md)
    report = check_s3_episode_list(episodes, season_chapters=list(range(1, 31)))
    assert report.passed, report.issues


def test_parse_and_check_s5(s5_md: str) -> None:
    script = parse_script_md(s5_md, episode_id="S1E01", global_episode_id="EP001")
    assert len(script["scenes"]) >= 5
    report = check_s5_script(script, episode_chapters=[1])
    assert report.passed, report.issues


def test_s0_checker_accepts_scene_list_format() -> None:
    from novelscript.checkers.s0 import check_s0_story_engine

    path = PROJECT_ROOT / "projects" / "dragons-ice" / "S0_story_engine.md"
    if not path.exists():
        pytest.skip("dragons-ice fixture missing")
    report = check_s0_story_engine(path.read_text(encoding="utf-8"))
    assert report.passed, report.issues


def test_parse_s2_seasons_compact_table() -> None:
    path = PROJECT_ROOT / "projects" / "dragons-ice" / "S2_season_map.md"
    if not path.exists():
        pytest.skip("dragons-ice fixture missing")
    seasons = parse_season_map_md(path.read_text(encoding="utf-8"))
    assert len(seasons) == 5
    assert seasons[0]["season_id"] == "S1"
    assert seasons[0]["chapter_range"][0] == 1


def test_check_s2_dragons_ice_reports_chapter_gap() -> None:
    path = PROJECT_ROOT / "projects" / "dragons-ice" / "S2_season_map.md"
    if not path.exists():
        pytest.skip("dragons-ice fixture missing")
    seasons = parse_season_map_md(path.read_text(encoding="utf-8"))
    report = check_s2_season_map(seasons, total_chapters=132, expected_seasons=5)
    assert not report.passed
    assert any("131" in issue or "coverage gap" in issue for issue in report.issues)


def test_s2_multi_line_table_accepts_bold_line_labels() -> None:
    from novelscript.checkers.s2 import check_s2_season_map_md

    md = """\
# 季图谱

## 5季总表

| 季 | 标题 | 章节 | 季命题（主角变成谁）| 季首危机 | 季中不可回头的选择 | 季末大事件 + 下一季钩子 | 本季反派压力线 |
|---|---|---|---|---|---|---|---|
| **S1** | t | 1–30 | 从a→b | c | d | e hook here | f |
| **S2** | t | 31–60 | 从a→b | c | d | e hook here | f |
| **S3** | t | 61–90 | 从a→b | c | d | e hook here | f |
| **S4** | t | 91–120 | 从a→b | c | d | e hook here | f |
| **S5** | t | 121–132 | 从a→b | c | d | finale | f |

## 各季断点理由
- **S1|S2 断点（Ch30）**：渴望被满足后更大威胁打开，钩子升级

## 时间线鱼骨图
中心骨：EP01 → EP02

## 多线推进表

### S1 多线推进
| 线 | 本季起点 | 本季关键拐点 | 本季终点 |
|---|---|---|---|
| **A 主角成长** | s | k | e |
| **B 爱情/关系** | s | k | e |
| **C 反派/谜题** | s | k | e |
| **D 配角/情绪** | s | k | e |

## 名场面落点
| 名场面 | 原著位置 | 落点季 | 落点集（预估）| 情绪功能 |
|---|---|---|---|---|
| x | Ch1 | S1 | EP01 | y |
"""
    report = check_s2_season_map_md(md, total_chapters=132, expected_seasons=5)
    assert not any("多线推进表需 A/B/C/D" in issue for issue in report.issues), report.issues

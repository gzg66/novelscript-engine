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

from __future__ import annotations

from novelscript.checkers.adaptation import check_adaptation_notes, parse_adaptation_notes_md
from novelscript.checkers.s3 import check_s3_episode_list, parse_episode_list_md
from novelscript.index.episode_spec import (
    build_episode_spec,
    parse_episode_duration_from_brief,
    resolve_episode_spec,
)
from novelscript.pipeline.context import load_project
from novelscript.quality.rubric import check_script_quality
from novelscript.stages.source import format_adaptation_input_bundle, format_chapter_source_block


def test_parse_episode_duration_from_brief() -> None:
    brief = """## 目标形态硬约束
| 单集时长 | 2–3 分钟 / 目标 150 秒 |
"""
    assert parse_episode_duration_from_brief(brief) == 150


def test_build_episode_spec_tolerance() -> None:
    spec = build_episode_spec(duration_sec=150, tolerance_pct=15)
    assert spec["min_sec"] == 128
    assert spec["max_sec"] == 172


def test_parse_s3_eight_column_format() -> None:
    md = """
| 集 | 一句话集情 | 覆盖 | 核心冲突 | 主角的选择 | 本集变化 | 时长目标 | 集尾钩子 |
| **EP01** | 雨夜坠河 | Ch1–Ch2 | 生死 | 拼命游 | 身份从安全到濒死 | 150s | 冰晶特写入画 |
"""
    eps = parse_episode_list_md(md, season_id="S1")
    assert len(eps) == 1
    assert eps[0]["episode_change"] == "身份从安全到濒死"
    assert eps[0]["duration_target_sec"] == 150
    assert eps[0]["source_chapters"] == [1, 2]


def test_check_s3_rejects_chapter_slice_pattern() -> None:
    rows = []
    for i in range(1, 11):
        rows.append(
            f"| **EP{i:02d}** | 集情{i} | Ch{i} | 冲突 | 选择 | 关系发生不可逆改变 | 150s | 特写入画 |"
        )
    md = "\n".join(
        [
            "| 集 | 一句话集情 | 覆盖 | 核心冲突 | 主角的选择 | 本集变化 | 时长目标 | 集尾钩子 |",
            "|---|---|---|---|---|---|---|---|",
            *rows,
        ]
    )
    eps = parse_episode_list_md(md, season_id="S1")
    report = check_s3_episode_list(eps, season_chapters=list(range(1, 11)), episode_spec=build_episode_spec())
    assert not report.passed
    assert any("single-chapter" in i.lower() or "一章" in i for i in report.issues)


def test_check_s3_accepts_merged_episodes() -> None:
    md = """
| 集 | 一句话集情 | 覆盖 | 核心冲突 | 主角的选择 | 本集变化 | 时长目标 | 集尾钩子 |
|---|---|---|---|---|---|---|---|
| **EP01** | 开篇 | Ch1–Ch3 | 冲突 | 选择 | 处境彻底翻转不可逆 | 150s | 新威胁入画 |
| **EP02** | 续 | Ch4–Ch5 | 冲突 | 选择 | 信任链断裂不可逆 | 150s | 手攥紧特写 |
"""
    eps = parse_episode_list_md(md, season_id="S1")
    report = check_s3_episode_list(eps, season_chapters=list(range(1, 6)), episode_spec=build_episode_spec())
    assert report.passed, report.issues


def test_format_chapter_source_block_layered_fidelity() -> None:
    block = format_chapter_source_block("### Chapter 1\nbody", title="参考摘录")
    assert "必保锚点保真" in block
    assert "非锚点精编许可" in block


def test_format_adaptation_input_bundle() -> None:
    ctx = load_project(__import__("novelscript.config", fromlist=["PROJECT_ROOT"]).PROJECT_ROOT / "projects" / "dragon-ice-132")
    bundle = format_adaptation_input_bundle(
        ctx,
        excerpt="### Chapter 1\nx",
        excerpt_title="参考",
        season_id="S1",
        chapter_numbers=[1],
    )
    assert "参考" in bundle


def test_adaptation_notes_checker() -> None:
    md = """
## 改编决策记录
| 原著依据 | 改编动作 | 戏剧理由 | 服务引擎 |
|---|---|---|---|
| Ch3 独白 | 删除 | 不可外化 | 引擎1 |
"""
    notes = parse_adaptation_notes_md(md)
    report = check_adaptation_notes(notes)
    assert report.passed, report.issues


def test_script_quality_uses_episode_spec() -> None:
    script = {
        "episode_id": "S1E01",
        "cliffhanger": "冰晶特写",
        "scenes": [
            {
                "scene_id": "S1",
                "duration_target_sec": 50,
                "emotion_arc": "A→B",
                "beats": [
                    {
                        "beat_id": 1,
                        "action": "她转身推门冲进雨里",
                        "presentation_hint": "中景跟拍，冷蓝侧光",
                        "source_index": "Ch1",
                    },
                    {
                        "beat_id": 2,
                        "action": "她抓住栏杆撑住身体",
                        "presentation_hint": "近景，雨丝划过镜头",
                        "source_index": "Ch1",
                    },
                ],
            }
        ],
    }
    spec = build_episode_spec(duration_sec=150)
    report = check_script_quality(script, tier="production", episode_spec=spec)
    assert not report.passed
    assert any("outside" in i for i in report.issues)


def test_resolve_episode_spec_default() -> None:
    from novelscript.config import PROJECT_ROOT

    ctx = load_project(PROJECT_ROOT / "projects" / "dragon-ice-132")
    spec = resolve_episode_spec(ctx)
    assert spec["duration_sec"] == 150

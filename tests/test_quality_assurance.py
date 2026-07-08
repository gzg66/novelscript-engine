from __future__ import annotations

from novelscript.checkers.adaptation import check_adaptation_notes, parse_adaptation_notes_md
from novelscript.checkers.cross_episode import check_chapter_coverage_gap, run_season_cross_checks
from novelscript.checkers.dialogue import check_causal_chain, check_narrative_clarity
from novelscript.checkers.info_ledger import check_info_ledger, parse_info_ledger_md
from novelscript.checkers.s3 import check_episode_progression_chain, parse_episode_list_md
from novelscript.checkers.s5 import check_s5_script
from novelscript.quality.rubric import check_script_quality
from novelscript.index.episode_spec import build_episode_spec


# --- EP01 ring scene regression (砍因果、留台词) ---


def test_ep01_ring_without_bridge_fails_causal_chain() -> None:
    """Cut bridge dialogue but keep payoff line — must fail."""
    beats = [
        {"beat_id": 1, "dialogue": 'Eliza: "Did you find the ring? Get up and walk home!"', "action": "runs in"},
    ]
    report = check_causal_chain(beats)
    assert not report.passed
    assert any("ring" in i for i in report.issues)


def test_ep01_ring_with_bridge_passes() -> None:
    beats = [
        {
            "beat_id": 1,
            "dialogue": 'SFX: distant "Freya! Freya!"',
            "action": "lantern lights approach through trees",
        },
        {"beat_id": 2, "dialogue": 'Freya: "What ring?"', "action": "looks up confused"},
        {
            "beat_id": 3,
            "dialogue": 'Eliza: "Did you find the ring?"',
            "action": "grabs Freya's arm",
        },
    ]
    report = check_causal_chain(beats)
    assert report.passed, report.issues


def test_ep01_ring_defer_in_notes_passes_s5_checker() -> None:
    beats = [
        {"beat_id": 1, "dialogue": 'Eliza: "Did you find the ring?"', "action": "runs in"},
    ]
    notes = [{"source_ref": "Ch1 ring", "action": "adapt:defer → EP02", "dramatic_reason": "ring deferred"}]
    report = check_narrative_clarity(beats, adaptation_notes=notes)
    assert report.passed, report.issues

    script = {
        "episode_id": "S1E01",
        "cliffhanger": "银发倒影特写",
        "source_chapters": [1],
        "scenes": [
            {
                "scene_id": "Scene 1",
                "location": "lake",
                "characters": ["Freya"],
                "scene_goal": "survive",
                "conflict_resistance": "attack",
                "emotion_arc": "A→B",
                "duration_target_sec": 150,
                "beats": beats,
            }
        ],
    }
    s5 = check_s5_script(script, adaptation_notes=notes)
    assert s5.passed or not any("ring" in i for i in s5.issues), s5.issues


# --- EP08→EP09 chapter gap regression ---


def _ep08_ep09_episode_list_md() -> str:
    """EP08 ends at Ch7, EP09 jumps to Ch9 with Desmond — skips Ch8 setup (audit pattern)."""
    return """
| 集 | 一句话集情 | 覆盖 | 核心冲突 | 主角的选择 | 本集变化 | 时长目标 | 集尾钩子 |
|---|---|---|---|---|---|---|---|
| **EP08** | 集市购书遇雷根 | Ch7 | 阶级压迫 | 接受赠书 | 欠下人情债 | 150s | 雷根阴冷回头 |
| **EP09** | 戴斯蒙德献金冠 | Ch9 | 骑士大赛 | 拒绝丝带 | 名声初显 | 150s | 暗甲骑士入画 |
"""


def test_ep08_ep09_chapter_gap_with_desmond_reference_fails() -> None:
    eps = parse_episode_list_md(_ep08_ep09_episode_list_md(), season_id="S1")
    report = check_chapter_coverage_gap(eps)
    assert not report.passed
    assert any("gap" in i.lower() or "Ch8" in i or "skipped" in i for i in report.issues)


def test_ep08_ep09_progression_chain_flags_sensitive_gap() -> None:
    eps = parse_episode_list_md(_ep08_ep09_episode_list_md(), season_id="S1")
    report = check_episode_progression_chain(eps)
    assert any("EP08" in i and "EP09" in i for i in report.issues)


def test_ep08_ep09_merged_chapters_pass_gap_check() -> None:
    md = """
| 集 | 一句话集情 | 覆盖 | 核心冲突 | 主角的选择 | 本集变化 | 时长目标 | 集尾钩子 |
|---|---|---|---|---|---|---|---|
| **EP08** | 集市购书遇雷根 | Ch8 | 阶级压迫 | 接受赠书 | 欠下人情债 | 150s | 雷根阴冷回头 |
| **EP09** | 戴斯蒙德献金冠 | Ch8–Ch9 | 骑士大赛 | 拒绝丝带 | 名声初显 | 150s | 暗甲骑士入画 |
"""
    eps = parse_episode_list_md(md, season_id="S1")
    report = check_chapter_coverage_gap(eps)
    assert report.passed, report.issues


# --- EP05 benchmark (精简但不丢) ---


def _ep05_quality_script() -> dict:
    """Synthetic EP05-like script: 155s, multiple scenes, active beats, key line."""
    scenes = []
    for i in range(1, 6):
        scenes.append(
            {
                "scene_id": f"Scene {i}",
                "location": "camp",
                "characters": ["Freya", "Troy"],
                "scene_goal": f"goal {i}",
                "conflict_resistance": "Troy blocks",
                "emotion_arc": "屈辱→反抗",
                "duration_target_sec": 31,
                "beats": [
                    {
                        "beat_id": f"{i}.1",
                        "action": "她转身推开特洛伊的手，火星从掌心溅出",
                        "presentation_hint": "中景跟拍，营地火光在侧脸打出明暗分界",
                        "source_index": "Ch5",
                        "dialogue": 'Freya: "In your dreams!"',
                        "dramatic_function": "Climax",
                    },
                    {
                        "beat_id": f"{i}.2",
                        "action": "她攥紧拳头冲出去，裙摆掠过篝火",
                        "presentation_hint": "近景推至面部，火焰在瞳孔中跳动反射",
                        "source_index": "Ch5",
                        "dialogue": "",
                        "dramatic_function": "Hook",
                    },
                ],
            }
        )
    return {
        "episode_id": "S1E05",
        "cliffhanger": "营地远处号角响起，暗色帐篷入画",
        "source_chapters": [5],
        "scenes": scenes,
    }


def test_ep05_benchmark_passes_production_quality() -> None:
    script = _ep05_quality_script()
    spec = build_episode_spec(duration_sec=150)
    report = check_script_quality(script, tier="production", episode_spec=spec)
    assert report.passed, report.issues


# --- adaptation notes 5-column + info ledger ---


def test_adaptation_notes_accepts_defer() -> None:
    md = """
## 改编决策记录
| 原著依据 | 改编动作 | 戏剧理由 | 观众替代获知 | 服务引擎 |
|---|---|---|---|---|
| Ch1 戒指 | adapt:defer → EP02 | 首集不需理解戒指 | EP02 建立 | 引擎1 |
"""
    notes = parse_adaptation_notes_md(md)
    report = check_adaptation_notes(notes)
    assert report.passed, report.issues


def test_adaptation_notes_compress_requires_viewer_substitute() -> None:
    md = """
## 改编决策记录
| 原著依据 | 改编动作 | 戏剧理由 | 观众替代获知 | 服务引擎 |
|---|---|---|---|---|
| Ch3 独白 | adapt:compress | 保留屈辱到爆发情绪功能 | Beat 3 外化动作 | 引擎1 |
"""
    notes = parse_adaptation_notes_md(md)
    report = check_adaptation_notes(notes)
    assert report.passed, report.issues

    bad_md = """
## 改编决策记录
| 原著依据 | 改编动作 | 戏剧理由 | 服务引擎 |
|---|---|---|---|
| Ch3 独白 | adapt:compress | 短 | 引擎1 |
"""
    bad_notes = parse_adaptation_notes_md(bad_md)
    bad_report = check_adaptation_notes(bad_notes)
    assert not bad_report.passed


def test_info_ledger_parser_and_checker() -> None:
    md = """
## 本集信息账本
| 观众本集必须获知 | 来源 beat | 前置依赖（上集/本集前段） |
|---|---|---|
| 她穿越到湖畔 | Beat 2 | 无 |
| 冰刺是自卫魔法 | Beat 4 | Beat 3 |
| 银发是异变信号 | Beat 6 | Beat 5 |
"""
    rows = parse_info_ledger_md(md)
    assert len(rows) == 3
    report = check_info_ledger(rows, beat_ids={"2", "4", "6"})
    assert report.passed, report.issues


def test_run_season_cross_checks_missing_list() -> None:
    from pathlib import Path
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        report = run_season_cross_checks(Path(tmp), season_id="S1")
        assert not report.passed

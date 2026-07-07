from __future__ import annotations

from pathlib import Path

from novelscript.checkers.s4 import check_s4_beat_sheet, parse_beat_sheet_md
from novelscript.config import PROJECT_ROOT


def test_parse_scene_style_beat_sheet() -> None:
    md = """# S1E01

**集情**：穿越醒来
**集尾钩子**：冰眸

## Scene 1：湖畔

| Beat | 来源索引 | 画面动作 | 对白/声音 | 戏剧功能 | 呈现提示 |
| :--- | :--- | :--- | :--- | :--- | :--- |
| Beat 1 | Ch1-1 | 睁眼挣扎 | 喘息 | Setup | 低机位 |
| Beat 2 | Ch1-2 | 冰环爆发 | blondie | Climax | 特写 |
| Beat 3 | Ch1-3 | 火焰离去 | 咒语 | Hook | 逆光 |
| Beat 4 | Ch1-4 | 昏倒 | 无声 | Resolution | 定格 |
"""
    data = parse_beat_sheet_md(md, episode_id="S1E01")
    report = check_s4_beat_sheet(data)
    assert len(data["beats"]) == 4
    assert report.passed, report.issues


def test_parse_full_run_combined_ep01_section() -> None:
    md = Path(PROJECT_ROOT / "projects/full-run/seasons/s1/ep01/beat_sheet.md").read_text(encoding="utf-8")
    data = parse_beat_sheet_md(md, episode_id="S1E01")
    report = check_s4_beat_sheet(data)
    assert len(data["beats"]) >= 4
    assert report.passed, report.issues

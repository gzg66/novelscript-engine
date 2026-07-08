from __future__ import annotations

from pathlib import Path

from novelscript.checkers.s4 import check_s4_beat_sheet, parse_beat_sheet_md
from novelscript.config import PROJECT_ROOT


def test_parse_scene_style_beat_sheet() -> None:
    md = """# S1E01

**集情**：雨夜坠河获救，岸上失控
**集尾钩子**：手心薄冰

## Scene 1：雨夜坠河

| Beat | 来源索引 | 画面动作 | 对白/声音 | 戏剧功能 | 呈现提示 |
| :--- | :--- | :--- | :--- | :--- | :--- |
| Beat 1 | Ch1-1 | 车辆失控冲下桥 | 撞击声 | Setup | 主观急坠 |
| Beat 2 | Ch1-2 | 水下推门上游 | 气泡 | Rising | 冷色水下 |
| Beat 3 | Ch1-3 | 力竭下沉，一只手抓住腰 | 喘息 | Climax | 手入画 |

## Scene 2：湖岸

| Beat | 来源索引 | 画面动作 | 对白/声音 | 戏剧功能 | 呈现提示 |
| :--- | :--- | :--- | :--- | :--- | :--- |
| Beat 4 | Ch1-4 | 呛醒，黑影立于身后 | blondie | Rising | 逆光轮廓 |
| Beat 5 | Ch1-5 | 恐慌中冰刺环身 | Easy there | Hook | 冰刺特写 |
"""
    data = parse_beat_sheet_md(md, episode_id="S1E01")
    report = check_s4_beat_sheet(data)
    assert len(data["beats"]) == 5
    assert report.passed, report.issues


def test_parse_full_run_combined_ep01_section() -> None:
    md = Path(PROJECT_ROOT / "projects/full-run/seasons/s1/ep01/beat_sheet.md").read_text(encoding="utf-8")
    data = parse_beat_sheet_md(md, episode_id="S1E01")
    report = check_s4_beat_sheet(data)
    assert len(data["beats"]) >= 4
    assert report.passed, report.issues

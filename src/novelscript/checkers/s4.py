from __future__ import annotations

import re
from typing import Any

from novelscript.checkers.base import CheckerReport


def parse_beat_sheet_md(md_text: str, *, episode_id: str = "S1E01") -> dict[str, Any]:
    beats: list[dict[str, Any]] = []
    episode_goal = ""
    emotion_curve = ""
    hook_landing = ""

    for line in md_text.splitlines():
        if line.startswith("**集情**"):
            episode_goal = line.split("：", 1)[-1].strip().strip("*")
        if "情绪弧线" in line and "整集" in line:
            emotion_curve = line.split("：", 1)[-1].strip()
        if "钩子落点" in line or "集尾钩子" in line:
            hook_landing = line.split("：", 1)[-1].strip().strip("*")

    in_table = False
    beat_id = 0
    for line in md_text.splitlines():
        if re.match(rf"##\s+EP\d+.*{episode_id[-2:]}", line, re.I) or f"EP{episode_id[-2:]}" in line:
            in_table = True
        if line.strip().startswith("|") and in_table:
            if re.match(r"^\|\s*Beat\s*\|", line, re.I) or re.match(r"^\|[-\s|]+\|$", line):
                continue
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            if len(cells) < 5:
                continue
            try:
                beat_id = int(cells[0])
            except ValueError:
                continue
            beats.append(
                {
                    "beat_id": beat_id,
                    "dramatic_function": cells[4] if len(cells) > 4 else "",
                    "info_gap": "",
                    "externalization": cells[2] if len(cells) > 2 else "",
                    "hook_anchor": cells[5] if "钩" in (cells[4] if len(cells) > 4 else "") else None,
                }
            )

    return {
        "episode_id": episode_id,
        "episode_goal": episode_goal,
        "emotion_curve": emotion_curve,
        "hook_landing": hook_landing,
        "beats": beats,
    }


def check_s4_beat_sheet(data: dict[str, Any]) -> CheckerReport:
    report = CheckerReport(stage="S4", passed=True)
    beats = data.get("beats") or []
    n = len(beats)
    if n < 4 or n > 8:
        report.add_issue(f"Beat count {n} not in range 4-8")
    for beat in beats:
        if not beat.get("externalization"):
            report.add_issue(f"Beat {beat.get('beat_id')}: missing externalization")
        if not beat.get("dramatic_function"):
            report.add_issue(f"Beat {beat.get('beat_id')}: missing dramatic_function")
    if not report.hard_fail:
        report.passed = True
    return report

from __future__ import annotations

import re
from typing import Any

from novelscript.checkers.base import CheckerReport


def parse_episode_list_md(md_text: str) -> list[dict[str, Any]]:
    episodes: list[dict[str, Any]] = []
    for line in md_text.splitlines():
        if not line.strip().startswith("|"):
            continue
        if "**EP" not in line and not re.search(r"\|\s*\*?\*?EP\d+", line):
            continue
        if re.match(r"^\|[-\s|]+\|$", line):
            continue
        cells = [c.strip().strip("*") for c in line.strip().strip("|").split("|")]
        if len(cells) < 6:
            continue
        ep_match = re.search(r"EP(\d+)", cells[0])
        if not ep_match:
            continue
        ep_num = int(ep_match.group(1))
        episodes.append(
            {
                "episode_id": f"S1E{ep_num:02d}",
                "global_episode_id": f"EP{ep_num:03d}",
                "logline": cells[1],
                "source_chapters": _parse_chapters(cells[2]),
                "core_conflict": cells[3],
                "protagonist_choice": cells[4],
                "cliffhanger": cells[5],
                "serves_engines": _infer_engines(cells[1] + cells[3]),
            }
        )
    return episodes


def _parse_chapters(text: str) -> list[int]:
    chapters: set[int] = set()
    for m in re.finditer(r"Ch\s*(\d+)", text, re.IGNORECASE):
        chapters.add(int(m.group(1)))
    ranges = re.findall(r"(\d+)\s*[–\-]\s*(\d+)", text)
    for start, end in ranges:
        chapters.update(range(int(start), int(end) + 1))
    if not chapters:
        for m in re.finditer(r"(\d+)", text):
            chapters.add(int(m.group(1)))
    return sorted(chapters)


def _infer_engines(text: str) -> list[str]:
    engines = []
    for name in ("逆袭", "双男主拉扯", "命定之恋", "身世之谜"):
        if name in text or any(k in text for k in ("丝带", "龙", "冰", "穿越")):
            engines.append(name)
    return engines[:2] if engines else ["逆袭"]


def check_s3_episode_list(
    episodes: list[dict[str, Any]],
    *,
    season_chapters: list[int],
    must_keep: list[dict[str, Any]] | None = None,
) -> CheckerReport:
    report = CheckerReport(stage="S3", passed=True)
    season_set = set(season_chapters)

    if not episodes:
        report.add_issue("No episodes parsed")
        return report

    covered: set[int] = set()
    for ep in episodes:
        required = ("episode_id", "logline", "source_chapters", "core_conflict", "protagonist_choice", "cliffhanger")
        for field in required:
            if not ep.get(field):
                report.add_issue(f"{ep.get('episode_id')}: missing {field}")
        chs = ep.get("source_chapters") or []
        season_max = max(season_set) if season_set else 0
        for ch in chs:
            if ch not in season_set:
                if ch == season_max + 1:
                    report.add_warning(f"{ep.get('episode_id')}: chapter {ch} is next-season preview")
                else:
                    report.add_issue(f"{ep.get('episode_id')}: chapter {ch} outside season range")
        covered.update(chs)
        if not ep.get("serves_engines"):
            report.add_issue(f"{ep.get('episode_id')}: no engine hit", hard=False)

    if must_keep:
        season_set = set(season_chapters)
        for scene in must_keep:
            scene_chs = set(scene.get("source_chapters") or [])
            if not (scene_chs & season_set):
                continue
            if scene.get("season_id") and not scene.get("episode_id"):
                report.add_issue(f"must_keep #{scene.get('id')}: missing episode_id")

    if not report.hard_fail:
        report.passed = True
    return report

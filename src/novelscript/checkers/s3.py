from __future__ import annotations

import re
from typing import Any

from novelscript.checkers.base import CheckerReport
from novelscript.index.episode_spec import build_episode_spec, duration_in_spec

_SINGLE_CHAPTER_RATIO_THRESHOLD = 0.6
_VISUAL_HOOK_KEYWORDS = (
    "特写",
    "入画",
    "异变",
    "镜头",
    "手",
    "眼",
    "转身",
    "定格",
    "慢镜",
    "逼近",
    "裂缝",
    "血",
    "冰",
    "火",
    "影",
    "门",
    "屏",
    "close",
    "freeze",
    "zoom",
)


def parse_episode_list_md(md_text: str, *, season_id: str = "S1") -> list[dict[str, Any]]:
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

        if len(cells) >= 8:
            episode_change = cells[5]
            duration_raw = cells[6]
            cliffhanger = cells[7]
        else:
            episode_change = ""
            duration_raw = ""
            cliffhanger = cells[5]
            if len(cells) > 6:
                duration_raw = cells[6]

        duration_target_sec = _parse_duration_sec(duration_raw)

        episodes.append(
            {
                "episode_id": f"{season_id}E{ep_num:02d}",
                "global_episode_id": f"EP{ep_num:03d}",
                "logline": cells[1],
                "source_chapters": _parse_chapters(cells[2]),
                "core_conflict": cells[3],
                "protagonist_choice": cells[4],
                "episode_change": episode_change,
                "duration_target_sec": duration_target_sec,
                "cliffhanger": cliffhanger,
                "serves_engines": _infer_engines(cells[1] + cells[3]),
            }
        )
    return episodes


def _parse_duration_sec(text: str) -> int | None:
    if not text:
        return None
    match = re.search(r"(\d+)", text)
    return int(match.group(1)) if match else None


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


def _has_visual_hook(text: str) -> bool:
    lowered = text.lower()
    return any(kw in text or kw in lowered for kw in _VISUAL_HOOK_KEYWORDS)


_PASSIVE_CHOICE_RE = re.compile(r"被(救|发现|安排|逼|迫)|被迫|无意间发现")


def check_s3_episode_list(
    episodes: list[dict[str, Any]],
    *,
    season_chapters: list[int],
    must_keep: list[dict[str, Any]] | None = None,
    episode_spec: dict[str, Any] | None = None,
    single_chapter_ratio_threshold: float = _SINGLE_CHAPTER_RATIO_THRESHOLD,
) -> CheckerReport:
    report = CheckerReport(stage="S3", passed=True)
    season_set = set(season_chapters)
    spec = episode_spec or build_episode_spec()

    if not episodes:
        report.add_issue("No episodes parsed")
        return report

    covered: set[int] = set()
    single_chapter_eps = 0
    merged_eps = 0

    for ep in episodes:
        required = ("episode_id", "logline", "source_chapters", "core_conflict", "protagonist_choice", "cliffhanger")
        for field in required:
            if not ep.get(field):
                report.add_issue(f"{ep.get('episode_id')}: missing {field}")

        change = str(ep.get("episode_change") or "")
        if len(change) < 8:
            report.add_issue(f"{ep.get('episode_id')}: episode_change too short or missing (need >=8 chars)")

        dur = ep.get("duration_target_sec")
        if dur is None:
            report.add_issue(f"{ep.get('episode_id')}: missing duration_target_sec")
        elif not duration_in_spec(int(dur), spec):
            report.add_issue(
                f"{ep.get('episode_id')}: duration {dur}s outside {spec['min_sec']}-{spec['max_sec']}s"
            )

        cliff = str(ep.get("cliffhanger") or "")
        if cliff and not _has_visual_hook(cliff):
            report.add_issue(f"{ep.get('episode_id')}: cliffhanger lacks visual hook markers", hard=False)

        chs = ep.get("source_chapters") or []
        if len(chs) == 1:
            single_chapter_eps += 1
        elif len(chs) > 1:
            merged_eps += 1

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
        choice = str(ep.get("protagonist_choice") or "")
        if choice and _PASSIVE_CHOICE_RE.search(choice):
            report.add_issue(f"{ep.get('episode_id')}: passive protagonist choice", hard=False)

    total = len(episodes)
    if total > 0 and single_chapter_eps / total > single_chapter_ratio_threshold:
        report.add_issue(
            f"Too many single-chapter episodes ({single_chapter_eps}/{total}); "
            "merge by conflict density instead of 1:1 chapter slicing"
        )

    season_span = len(season_set)
    if season_span > 0 and total >= season_span * 0.9 and merged_eps == 0:
        report.add_issue(
            f"Episode count {total} ≈ chapter span {season_span} with no merged episodes; "
            "likely chapter-slice division"
        )

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

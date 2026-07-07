from __future__ import annotations

import re
from typing import Any

from novelscript.checkers.base import CheckerReport

EPISODES_PER_SEASON_RANGE = (20, 30)
SEASON_COUNT_RANGE_100_PLUS = (4, 6)

_SINGLE_SEASON_MARKERS = ("单季完结", "单季完結", "一季完结", "一季完結")
_MULTI_SEASON_MARKERS = ("多季", "共", "季连载", "分季")


def infer_season_count(total_chapters: int) -> int:
    """PRD: 百章量级约 4–6 季；按篇幅与 20–30 集/季推算。"""
    if total_chapters <= 40:
        return 2
    if total_chapters <= 70:
        return 3
    if total_chapters <= 100:
        return 4
    if total_chapters <= 140:
        return 5
    if total_chapters <= 180:
        return 6
    return max(4, min(8, round(total_chapters / 26)))


def _parse_int_range(text: str) -> tuple[int | None, int | None]:
    match = re.search(r"(\d+)\s*[–\-—~至]\s*(\d+)", text)
    if match:
        lo, hi = int(match.group(1)), int(match.group(2))
        return (lo, hi) if lo <= hi else (hi, lo)
    nums = [int(n) for n in re.findall(r"\d+", text)]
    if len(nums) == 1:
        return nums[0], nums[0]
    return None, None


def _extract_season_count_from_scale(scale_text: str) -> int | None:
    patterns = (
        r"(\d+)\s*季",
        r"共\s*(\d+)\s*季",
        r"(\d+)\s*seasons?",
    )
    for pattern in patterns:
        match = re.search(pattern, scale_text, re.I)
        if match:
            return int(match.group(1))
    return None


def parse_adaptation_brief(md_text: str) -> dict[str, Any]:
    """Parse S0_adaptation_brief.md for season plan fields."""
    result: dict[str, Any] = {
        "season_count": None,
        "episodes_per_season_min": None,
        "episodes_per_season_max": None,
        "is_single_season_finale": False,
        "has_multi_season_scale": False,
        "has_inter_season_principle": False,
        "scale_text": "",
        "episodes_text": "",
    }

    if "季间叙事原则" in md_text or "季間敘事原則" in md_text:
        result["has_inter_season_principle"] = True

    in_constraints = False
    scale_text = ""
    for line in md_text.splitlines():
        if "## 目标形态硬约束" in line:
            in_constraints = True
            continue
        if in_constraints and line.startswith("## "):
            break
        if not in_constraints:
            continue

        row = line.strip()
        if not row.startswith("|"):
            continue
        cells = [c.strip().strip("*") for c in row.strip().strip("|").split("|")]
        if len(cells) < 2:
            continue
        key, value = cells[0].lower(), cells[1]
        if "全剧规模" in key or "全劇規模" in key:
            scale_text = value
            result["scale_text"] = value
            result["has_multi_season_scale"] = (
                any(m in value for m in _MULTI_SEASON_MARKERS)
                or bool(re.search(r"[2-9]\d*\s*季", value))
            )
            result["season_count"] = _extract_season_count_from_scale(value)
        if "单季集数" in key or "單季集數" in key:
            result["episodes_text"] = value
            lo, hi = _parse_int_range(value)
            result["episodes_per_season_min"] = lo
            result["episodes_per_season_max"] = hi

    if scale_text and any(marker in scale_text for marker in _SINGLE_SEASON_MARKERS):
        result["is_single_season_finale"] = True

    if result["season_count"] is None and result["scale_text"]:
        if result["has_multi_season_scale"] and not result["is_single_season_finale"]:
            nums = [int(n) for n in re.findall(r"\d+", result["scale_text"])]
            if nums:
                result["season_count"] = max(nums)

    return result


def count_s1_season_arc_rows(md_text: str) -> int:
    seen: set[str] = set()
    for pattern in (r"\|\s*\*{0,2}(S\d+)\*{0,2}\s*\|", r"\|\s*\*{0,2}Season\s+(\d+)\*{0,2}\s*\|"):
        for match in re.finditer(pattern, md_text, re.I):
            sid = f"S{int(match.group(1).lstrip('Ss'))}" if match.group(1)[0].isdigit() else match.group(1).upper()
            if not sid.startswith("S"):
                sid = f"S{sid}"
            seen.add(sid)
    return len(seen)


def resolve_season_count(
    *,
    brief_md: str | None = None,
    total_chapters: int | None = None,
) -> int:
    if brief_md:
        plan = parse_adaptation_brief(brief_md)
        if plan.get("season_count"):
            return int(plan["season_count"])
    if total_chapters:
        return infer_season_count(total_chapters)
    return 5


def check_adaptation_brief(md_text: str, *, total_chapters: int) -> CheckerReport:
    report = CheckerReport(stage="S0_brief", passed=True)
    plan = parse_adaptation_brief(md_text)

    if plan["is_single_season_finale"]:
        report.add_issue("全剧规模不得为「单季完结」；长篇须规划多季")

    if not plan["scale_text"]:
        report.add_issue("目标形态硬约束缺少「全剧规模」行")
    elif not plan["has_multi_season_scale"] and not plan["season_count"]:
        report.add_issue("全剧规模须标明多季（如「5 季 × 24 集」），不可单季大包大揽")

    if not plan["has_inter_season_principle"]:
        report.add_issue("缺少「季间叙事原则」节（每季末强钩子/危机升级）")

    ep_lo, ep_hi = plan["episodes_per_season_min"], plan["episodes_per_season_max"]
    if ep_lo is None:
        report.add_issue("目标形态硬约束缺少「单季集数」行")
    elif ep_lo < EPISODES_PER_SEASON_RANGE[0] or (ep_hi or ep_lo) > EPISODES_PER_SEASON_RANGE[1]:
        report.add_issue(
            f"单季集数 {plan['episodes_text'] or ep_lo} 须在 {EPISODES_PER_SEASON_RANGE[0]}–{EPISODES_PER_SEASON_RANGE[1]} 范围内"
        )

    season_count = plan["season_count"] or infer_season_count(total_chapters)
    if total_chapters >= 100:
        lo, hi = SEASON_COUNT_RANGE_100_PLUS
        if season_count < lo or season_count > hi:
            report.add_issue(f"百章量级全书季数 {season_count} 须在 {lo}–{hi} 季范围内")

    if not report.hard_fail:
        report.passed = True
    return report


def check_cross_stage_season_consistency(
    *,
    brief_md: str,
    s1_md: str,
    s2_md: str,
    total_chapters: int,
) -> CheckerReport:
    from novelscript.checkers.s2 import parse_season_map_md

    report = CheckerReport(stage="season_consistency", passed=True)
    brief_plan = parse_adaptation_brief(brief_md)
    brief_count = brief_plan.get("season_count") or infer_season_count(total_chapters)
    s1_count = count_s1_season_arc_rows(s1_md)
    s2_count = len(parse_season_map_md(s2_md))

    if s1_count != brief_count:
        report.add_issue(f"S1 蜕变表行数 {s1_count} != 简报季数 {brief_count}")
    if s2_count != brief_count:
        report.add_issue(f"S2 季表行数 {s2_count} != 简报季数 {brief_count}")
    if s1_count != s2_count:
        report.add_issue(f"S1 蜕变表行数 {s1_count} != S2 季表行数 {s2_count}")

    if not report.hard_fail:
        report.passed = True
    return report

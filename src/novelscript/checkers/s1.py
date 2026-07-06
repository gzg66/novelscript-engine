from __future__ import annotations

import re

from novelscript.checkers.base import CheckerReport

LEAD_FIELD_ALIASES: dict[str, tuple[str, ...]] = {
    "想要": ("想要", "want", "她想要什么", "想要什么"),
    "不愿承认": ("不愿承认", "deny", "她不愿承认", "不愿承认什么"),
    "会改变": ("会改变", "本剧会改变", "will change", "will_change", "本剧/本季会失去或改变"),
}


def _has_lead_field(md_text: str, aliases: tuple[str, ...]) -> bool:
    lowered = md_text.lower()
    for alias in aliases:
        if alias.lower() in lowered:
            return True
    return False


def check_s1_premise(md_text: str, *, expected_seasons: int = 5) -> CheckerReport:
    report = CheckerReport(stage="S1_premise", passed=True)
    has_one_liner = (
        "一句话" in md_text
        or "one_liner" in md_text.lower()
        or "one-liner" in md_text.lower()
        or "one liner" in md_text.lower()
    )
    if not has_one_liner:
        report.add_issue("Missing one-liner premise")

    season_rows = len(re.findall(r"\|\s*\*{0,2}S\d+\*{0,2}\s*\|", md_text, re.I))
    season_rows += len(re.findall(r"\|\s*\*{0,2}Season\s+\d+\*{0,2}\s*\|", md_text, re.I))
    if season_rows < expected_seasons:
        report.add_issue(f"season arc rows {season_rows} < {expected_seasons}", hard=False)
    if not report.hard_fail:
        report.passed = True
    return report


def check_s1_bible(md_text: str) -> CheckerReport:
    report = CheckerReport(stage="S1_bible", passed=True)
    for field, aliases in LEAD_FIELD_ALIASES.items():
        if not _has_lead_field(md_text, aliases):
            report.add_issue(f"Missing lead field: {field}")
    if "配角合并" not in md_text and "合并" not in md_text:
        report.add_issue("Missing supporting cast merge section", hard=False)
    if not report.hard_fail:
        report.passed = True
    return report

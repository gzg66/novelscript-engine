from __future__ import annotations

import re

from novelscript.checkers.base import CheckerReport

CORE_ENGINE_ALIASES = ("核心爽点", "故事发动机", "四台故事发动机", "四台核心发动机")
MUST_KEEP_ALIASES = ("名场面必保清单", "必保名场面清单")
OPTIONAL_SECTION_ALIASES = ("可删支线", "可删", "可合并")
MIN_MUST_KEEP = 10

_ENGINE_PATTERNS = (
    re.compile(r"引擎\s*\d+", re.I),
    re.compile(r"发动机\s*[IVX\d]+", re.I),
    re.compile(r"Engine\s*\d+", re.I),
)


def _has_section(md_text: str, aliases: tuple[str, ...]) -> bool:
    return any(alias in md_text for alias in aliases)


def _count_engines(md_text: str) -> int:
    seen: set[str] = set()
    for pattern in _ENGINE_PATTERNS:
        for match in pattern.finditer(md_text):
            seen.add(match.group(0).lower())
    return len(seen)


def _count_must_keep_rows(md_text: str) -> tuple[int, list[str]]:
    issues: list[str] = []
    rows = 0

    section_aliases = MUST_KEEP_ALIASES
    in_table = False
    for line in md_text.splitlines():
        if any(alias in line for alias in section_aliases):
            in_table = True
            continue
        if in_table and line.startswith("## ") and not any(alias in line for alias in section_aliases):
            break
        if not in_table or not line.strip().startswith("|"):
            continue
        if re.match(r"^\|\s*#?\s*\|", line) or re.match(r"^\|[-\s|]+\|$", line):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) < 4:
            continue
        try:
            int(cells[0].lstrip("#").strip())
        except ValueError:
            continue
        rows += 1
        if not cells[3]:
            issues.append(f"must_keep row {cells[0]}: missing why_irreducible")

    scene_rows = len(re.findall(r"(?:^|\n)#{1,3}\s*Scene\s*\d+", md_text, re.I))
    scene_rows += len(re.findall(r"(?:^|\n)\*\*Scene\s*\d+", md_text, re.I))
    rows = max(rows, scene_rows)

    return rows, issues


def check_s0_story_engine(md_text: str) -> CheckerReport:
    report = CheckerReport(stage="S0", passed=True)
    if not _has_section(md_text, CORE_ENGINE_ALIASES):
        report.add_issue("Missing section: 核心爽点")
    if not _has_section(md_text, MUST_KEEP_ALIASES):
        report.add_issue("Missing section: 名场面必保清单")
    if not any(alias in md_text for alias in OPTIONAL_SECTION_ALIASES):
        report.add_warning("Missing deletable subplot section")

    must_keep_rows, row_issues = _count_must_keep_rows(md_text)
    for issue in row_issues:
        report.add_issue(issue)
    if must_keep_rows < MIN_MUST_KEEP:
        report.add_issue(f"must_keep rows {must_keep_rows} < {MIN_MUST_KEEP}")

    engine_count = _count_engines(md_text)
    if engine_count < 4:
        report.add_issue(f"story engines {engine_count} < 4")

    if not report.hard_fail:
        report.passed = True
    return report

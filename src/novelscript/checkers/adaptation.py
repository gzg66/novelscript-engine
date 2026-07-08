from __future__ import annotations

import re
from typing import Any

from novelscript.checkers.base import CheckerReport

_ADAPTATION_ACTIONS = ("删除", "合并", "压缩", "前置", "后置", "重写", "adapt:compress", "adapt:merge")


def parse_adaptation_notes_md(md_text: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    in_table = False
    for line in md_text.splitlines():
        if "改编决策" in line or "改编动作" in line:
            in_table = False
        if not line.strip().startswith("|"):
            continue
        if re.match(r"^\|[-\s|]+\|$", line):
            in_table = True
            continue
        if not in_table:
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) < 4:
            continue
        if cells[0] in ("原著依据", "来源", "章节"):
            continue
        rows.append(
            {
                "source_ref": cells[0],
                "action": cells[1],
                "dramatic_reason": cells[2],
                "serves_engine": cells[3] if len(cells) > 3 else "",
            }
        )
    return rows


def check_adaptation_notes(
    notes: list[dict[str, Any]],
    *,
    require_edit: bool = True,
) -> CheckerReport:
    report = CheckerReport(stage="adaptation_notes", passed=True)
    if not notes:
        report.add_issue("adaptation_notes: no rows parsed")
        return report

    has_edit = False
    for row in notes:
        action = str(row.get("action") or "")
        if any(tok in action for tok in _ADAPTATION_ACTIONS):
            has_edit = True
        if not row.get("source_ref"):
            report.add_issue("adaptation_notes: row missing source_ref")
        if not row.get("dramatic_reason"):
            report.add_issue("adaptation_notes: row missing dramatic_reason", hard=False)

    if require_edit and not has_edit:
        report.add_issue(
            "adaptation_notes: need at least one 删除/合并/压缩/adapt:* edit (balanced adaptation mode)"
        )

    if not report.hard_fail:
        report.passed = True
    return report


def extract_adaptation_section(md_text: str) -> str:
    """Extract ## 改编决策记录 section from beat_sheet or standalone notes."""
    lines = md_text.splitlines()
    start = None
    for i, line in enumerate(lines):
        if re.match(r"##\s+改编决策", line):
            start = i
            break
    if start is None:
        return md_text if "改编动作" in md_text else ""
    end = len(lines)
    for i in range(start + 1, len(lines)):
        if lines[i].startswith("## ") and "改编" not in lines[i]:
            end = i
            break
    return "\n".join(lines[start:end])

from __future__ import annotations

import re
from typing import Any

from novelscript.checkers.base import CheckerReport

_ADAPTATION_ACTIONS = (
    "删除",
    "合并",
    "压缩",
    "前置",
    "后置",
    "重写",
    "adapt:compress",
    "adapt:merge",
    "adapt:defer",
)
_COMPRESS_ACTIONS = ("删除", "压缩", "adapt:compress", "adapt:merge")


def parse_adaptation_notes_md(md_text: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    in_table = False
    for line in md_text.splitlines():
        # Section headings only — not table header cells containing「改编动作」
        if re.match(r"##\s+改编", line.strip()):
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
        row: dict[str, Any] = {
            "source_ref": cells[0],
            "action": cells[1],
            "dramatic_reason": cells[2],
            "serves_engine": cells[3] if len(cells) > 3 else "",
        }
        if len(cells) >= 5:
            row["viewer_substitute"] = cells[3]
            row["serves_engine"] = cells[4]
        rows.append(row)
    return rows


def _is_compress_action(action: str) -> bool:
    return any(tok in action for tok in _COMPRESS_ACTIONS)


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
        reason = str(row.get("dramatic_reason") or "")
        if not reason:
            report.add_issue("adaptation_notes: row missing dramatic_reason", hard=False)
        elif _is_compress_action(action) and len(reason) < 8:
            report.add_issue(
                f"adaptation_notes: compress row '{row.get('source_ref')}' needs dramatic_reason "
                "explaining retained emotion function (>=8 chars)"
            )
        if _is_compress_action(action) and row.get("viewer_substitute") is not None:
            substitute = str(row.get("viewer_substitute") or "")
            if len(substitute) < 4:
                report.add_issue(
                    f"adaptation_notes: compress row '{row.get('source_ref')}' missing "
                    "viewer_substitute (how audience still learns this)"
                )

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

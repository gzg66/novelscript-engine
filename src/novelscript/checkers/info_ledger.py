from __future__ import annotations

import re
from typing import Any

from novelscript.checkers.base import CheckerReport

_MIN_LEDGER_ROWS = 3
_MAX_LEDGER_ROWS = 6


def parse_info_ledger_md(md_text: str) -> list[dict[str, Any]]:
    """Parse ## 本集信息账本 table from beat_sheet.md."""
    rows: list[dict[str, Any]] = []
    in_section = False
    in_table = False
    for line in md_text.splitlines():
        if re.match(r"##\s+本集信息账本", line):
            in_section = True
            continue
        if in_section and line.startswith("## "):
            break
        if not in_section:
            continue
        if not line.strip().startswith("|"):
            continue
        if re.match(r"^\|[-\s|]+\|$", line):
            in_table = True
            continue
        if not in_table:
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) < 3:
            continue
        if cells[0] in ("观众本集必须获知", "必须获知", "信息"):
            continue
        rows.append(
            {
                "must_know": cells[0],
                "source_beat": cells[1],
                "prerequisite": cells[2] if len(cells) > 2 else "",
            }
        )
    return rows


def extract_info_ledger_section(md_text: str) -> str:
    lines = md_text.splitlines()
    start = None
    for i, line in enumerate(lines):
        if re.match(r"##\s+本集信息账本", line):
            start = i
            break
    if start is None:
        return ""
    end = len(lines)
    for i in range(start + 1, len(lines)):
        if lines[i].startswith("## "):
            end = i
            break
    return "\n".join(lines[start:end])


def check_info_ledger(
    rows: list[dict[str, Any]],
    *,
    beat_ids: set[str] | None = None,
) -> CheckerReport:
    report = CheckerReport(stage="info_ledger", passed=True)
    if not rows:
        report.add_issue("info_ledger: missing ## 本集信息账本 section")
        return report

    n = len(rows)
    if n < _MIN_LEDGER_ROWS or n > _MAX_LEDGER_ROWS:
        report.add_issue(f"info_ledger: need {_MIN_LEDGER_ROWS}-{_MAX_LEDGER_ROWS} rows, got {n}")

    for row in rows:
        must_know = str(row.get("must_know") or "")
        source_beat = str(row.get("source_beat") or "")
        if len(must_know) < 4:
            report.add_issue("info_ledger: row missing must_know (>=4 chars)")
        if not source_beat:
            report.add_issue(f"info_ledger: '{must_know[:20]}' missing source_beat")
        elif beat_ids is not None:
            beat_num = re.search(r"(\d+)", source_beat)
            if beat_num and beat_num.group(1) not in beat_ids:
                report.add_issue(
                    f"info_ledger: '{must_know[:20]}' references beat {beat_num.group(1)} not in beat sheet"
                )

    if not report.hard_fail:
        report.passed = True
    return report


def _moved_to_episode(text: str) -> str | None:
    match = re.search(r"(?:moved_to|移至|延后至|defer\s*→?)\s*:?\s*EP(\d+)", text, re.I)
    if match:
        return f"EP{int(match.group(1)):02d}"
    match = re.search(r"EP(\d+)", text, re.I)
    if match and any(tok in text.lower() for tok in ("moved", "defer", "移至", "延后")):
        return f"EP{int(match.group(1)):02d}"
    return None


def check_cross_episode_info_chain(
    episode_ledgers: list[tuple[str, list[dict[str, Any]]]],
) -> CheckerReport:
    """Verify moved_to/deferred info appears in the target episode ledger."""
    report = CheckerReport(stage="cross_episode_info", passed=True)
    ledger_by_ep: dict[str, list[str]] = {}
    for ep_id, rows in episode_ledgers:
        ep_tag = ep_id.split("E")[-1] if "E" in ep_id else ep_id
        ep_key = f"EP{int(ep_tag):02d}"
        ledger_by_ep[ep_key] = [str(r.get("must_know") or "").lower() for r in rows]

    for ep_id, rows in episode_ledgers:
        ep_tag = ep_id.split("E")[-1] if "E" in ep_id else ep_id
        ep_key = f"EP{int(ep_tag):02d}"
        for row in rows:
            prereq = str(row.get("prerequisite") or "")
            target = _moved_to_episode(prereq)
            if not target:
                continue
            must_know = str(row.get("must_know") or "")
            target_rows = ledger_by_ep.get(target, [])
            if not target_rows:
                report.add_issue(
                    f"{ep_key}: info '{must_know[:30]}' moved_to {target} but target has no info ledger"
                )
                continue
            keywords = [w for w in re.split(r"\s+", must_know.lower()) if len(w) >= 2]
            if keywords and not any(any(kw in tr for kw in keywords[:3]) for tr in target_rows):
                report.add_issue(
                    f"{ep_key}: info '{must_know[:30]}' moved_to {target} but not found in target ledger"
                )

    if not report.hard_fail:
        report.passed = True
    return report

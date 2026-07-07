from __future__ import annotations

import re
from typing import Any

from novelscript.checkers.base import CheckerReport

REQUIRED_SEASON_FIELDS = (
    "season_id",
    "chapter_range",
    "season_proposition",
    "opening_crisis",
    "irreversible_choice",
    "season_finale",
    "next_season_hook",
    "villain_pressure_line",
)

_HEADER_MARKERS = ("章节", "chapter range", "season id", "季 |", "季|")


def _normalize_season_id(text: str) -> str | None:
    cleaned = text.strip().strip("*").strip()
    if re.fullmatch(r"S\d+", cleaned, re.I):
        return f"S{int(cleaned[1:])}"
    match = re.fullmatch(r"Season\s+(\d+)", cleaned, re.I)
    if match:
        return f"S{int(match.group(1))}"
    return None


def _parse_range(text: str) -> list[int]:
    match = re.search(r"(\d+)\s*[–\-—~至]\s*(\d+)", text)
    if not match:
        return []
    start, end = int(match.group(1)), int(match.group(2))
    if start > end:
        start, end = end, start
    return list(range(start, end + 1))


def _is_table_header(cells: list[str]) -> bool:
    joined = " | ".join(cells).lower()
    return any(marker in joined for marker in _HEADER_MARKERS)


def _season_from_canonical_row(cells: list[str]) -> dict[str, Any] | None:
    if len(cells) < 8:
        return None
    season_id = _normalize_season_id(cells[0])
    if not season_id:
        return None
    chapter_range = _parse_range(cells[2])
    if not chapter_range:
        return None
    return {
        "season_id": season_id,
        "title": cells[1],
        "chapter_range": chapter_range,
        "season_proposition": cells[3],
        "opening_crisis": cells[4],
        "irreversible_choice": cells[5],
        "season_finale": cells[6],
        "next_season_hook": cells[6],
        "villain_pressure_line": cells[7],
    }


def _season_from_compact_row(cells: list[str]) -> dict[str, Any] | None:
    if len(cells) < 7:
        return None
    season_id = _normalize_season_id(cells[0])
    if not season_id:
        return None
    chapter_range = _parse_range(cells[1])
    if not chapter_range:
        return None
    return {
        "season_id": season_id,
        "title": cells[2],
        "chapter_range": chapter_range,
        "season_proposition": cells[3],
        "opening_crisis": cells[3],
        "irreversible_choice": cells[4],
        "season_finale": cells[4],
        "next_season_hook": cells[6],
        "villain_pressure_line": cells[5] or cells[6],
    }


def parse_season_map_md(md_text: str) -> list[dict[str, Any]]:
    seasons: list[dict[str, Any]] = []
    seen: set[str] = set()

    for line in md_text.splitlines():
        if not line.strip().startswith("|"):
            continue
        if re.match(r"^\|[-\s|]+\|$", line):
            continue
        cells = [c.strip().strip("*") for c in line.strip().strip("|").split("|")]
        if _is_table_header(cells):
            continue

        season = _season_from_canonical_row(cells) or _season_from_compact_row(cells)
        if not season:
            continue
        if season["season_id"] in seen:
            continue
        seen.add(season["season_id"])
        seasons.append(season)

    seasons.sort(key=lambda item: int(item["season_id"][1:]))
    return seasons


_MECHANICAL_BREAKPOINT_RE = re.compile(
    r"^(?:ch)?\d+\s*[–\-—~至]\s*(?:ch)?\d+$|均分|平均|机械",
    re.I,
)
_BREAKPOINT_QUALITY_MARKERS = ("渴望", "威胁", "危機", "危机", "钩子", "打开", "升级", "满足", "开启")
_FOUR_LINE_LABELS = ("A", "B", "C", "D")


def _season_multi_line_section(md_text: str, season_id: str) -> str:
    pattern = re.compile(rf"###\s*{re.escape(season_id)}\s*多线推进", re.I)
    lines: list[str] = []
    capturing = False
    for line in md_text.splitlines():
        if pattern.search(line):
            capturing = True
            continue
        if capturing:
            if line.startswith("### ") or line.startswith("## "):
                break
            lines.append(line)
    return "\n".join(lines)


def _line_label_letter(cell: str) -> str | None:
    """First table column: A/B/C/D (LLM often wraps as **A 主角成长**)."""
    label = cell.strip().strip("*").strip().upper()
    if label in ("线", "LINE"):
        return None
    match = re.match(r"^([ABCD])\b", label)
    return match.group(1) if match else None


def _count_four_lines(section: str) -> int:
    found: set[str] = set()
    for line in section.splitlines():
        if not line.strip().startswith("|"):
            continue
        if re.match(r"^\|[-\s|]+\|$", line):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if not cells:
            continue
        letter = _line_label_letter(cells[0])
        if letter:
            found.add(letter)
    return len(found)


def _check_multi_line_progression(md_text: str, seasons: list[dict[str, Any]], report: CheckerReport) -> None:
    """Workflow v2 §S2 方法 B：每季四线推进表（A/B/C/D）。"""
    if "多线推进" not in md_text:
        report.add_warning("Missing blueprint section: 多线推进")
        return
    for season in seasons:
        sid = season.get("season_id", "")
        section = _season_multi_line_section(md_text, sid)
        if not section.strip():
            if sid == "S1":
                report.add_issue(f"{sid}: missing 多线推进表（四线 A/B/C/D）")
            else:
                report.add_warning(f"{sid}: missing 多线推进表")
            continue
        line_count = _count_four_lines(section)
        if line_count < 4:
            report.add_issue(f"{sid}: 多线推进表需 A/B/C/D 四行，仅解析到 {line_count} 行")


def _check_breakpoint_reasons(md_text: str, seasons: list[dict[str, Any]], report: CheckerReport) -> None:
    section = ""
    in_section = False
    for line in md_text.splitlines():
        if "各季断点理由" in line:
            in_section = True
            continue
        if in_section and line.startswith("## "):
            break
        if in_section:
            section += line + "\n"

    if not section.strip():
        report.add_issue("Missing section: 各季断点理由")
        return

    for season in seasons[:-1]:
        sid = season.get("season_id", "")
        hook = str(season.get("next_season_hook") or "").strip()
        if not hook or len(hook) < 8:
            report.add_issue(f"{sid}: next_season_hook empty or too short")

    for line in section.splitlines():
        stripped = line.strip()
        if not stripped.startswith("-") and not stripped.startswith("*"):
            continue
        body = re.sub(r"^[-*•]\s*", "", stripped)
        body = re.sub(r"\*\*[^*]+\*\*[：:]\s*", "", body)
        if _MECHANICAL_BREAKPOINT_RE.match(body.strip()):
            report.add_issue(f"Breakpoint reason too mechanical: {body[:60]}")
        elif len(body) < 12:
            report.add_issue(f"Breakpoint reason too short: {body[:60]}")
        elif not any(marker in body for marker in _BREAKPOINT_QUALITY_MARKERS):
            report.add_warning(f"Breakpoint reason may lack 渴望满足/威胁打开: {body[:50]}…")


def _check_season_propositions(seasons: list[dict[str, Any]], report: CheckerReport) -> None:
    """Workflow v2 Gate：每季末主角须「变成不同的人」——季命题含蜕变表述。"""
    transform_markers = ("→", "->", "变成", "成为", "从", "到")
    for season in seasons:
        prop = str(season.get("season_proposition") or "")
        if len(prop) < 8:
            continue
        if not any(marker in prop for marker in transform_markers):
            report.add_warning(f"{season.get('season_id')}: season_proposition may lack 季末蜕变（→/变成）")


def check_s2_season_map(
    seasons: list[dict[str, Any]],
    *,
    total_chapters: int,
    must_keep: list[dict[str, Any]] | None = None,
    expected_seasons: int | None = None,
    md_text: str | None = None,
) -> CheckerReport:
    report = CheckerReport(stage="S2", passed=True)

    if not seasons:
        report.add_issue("No seasons parsed from S2 season map")
        return report

    if expected_seasons is not None and len(seasons) != expected_seasons:
        report.add_issue(f"Season count {len(seasons)} != expected {expected_seasons}")

    covered: set[int] = set()
    for season in seasons:
        for field in REQUIRED_SEASON_FIELDS:
            val = season.get(field)
            if not val:
                report.add_issue(f"{season.get('season_id')}: missing field {field}")
        ch_range = season.get("chapter_range") or []
        if not ch_range:
            report.add_issue(f"{season.get('season_id')}: empty chapter_range")
            continue
        overlap = covered & set(ch_range)
        if overlap:
            report.add_issue(f"{season.get('season_id')}: chapter overlap {sorted(overlap)[:5]}")
        covered.update(ch_range)

    expected = set(range(1, total_chapters + 1))
    missing = expected - covered
    extra = covered - expected
    if missing:
        report.add_issue(f"Chapter coverage gap: missing {sorted(missing)[:10]}...")
    if extra:
        report.add_issue(f"Chapter coverage overflow: extra {sorted(extra)[:10]}...")

    if must_keep and any(s.get("season_id") for s in must_keep):
        for scene in must_keep:
            if not scene.get("season_id"):
                report.add_issue(f"must_keep #{scene.get('id')}: missing season_id mapping")

    if md_text:
        _check_breakpoint_reasons(md_text, seasons, report)
        _check_multi_line_progression(md_text, seasons, report)
    _check_season_propositions(seasons, report)

    if not report.hard_fail:
        report.passed = True
    return report


def check_s2_season_map_md(md_text: str, **kwargs: Any) -> CheckerReport:
    """Parse + check with optional blueprint section warnings."""
    seasons = parse_season_map_md(md_text)
    report = check_s2_season_map(seasons, md_text=md_text, **kwargs)
    for marker in ("时间线鱼骨", "名场面落点"):
        if marker not in md_text:
            report.add_warning(f"Missing blueprint section: {marker}")
    return report

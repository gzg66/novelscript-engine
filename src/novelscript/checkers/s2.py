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


def check_s2_season_map(
    seasons: list[dict[str, Any]],
    *,
    total_chapters: int,
    must_keep: list[dict[str, Any]] | None = None,
    expected_seasons: int | None = None,
) -> CheckerReport:
    report = CheckerReport(stage="S2", passed=True)

    if not seasons:
        report.add_issue("No seasons parsed from S2 season map")
        return report

    if expected_seasons and len(seasons) != expected_seasons:
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

    if not report.hard_fail:
        report.passed = True
    return report

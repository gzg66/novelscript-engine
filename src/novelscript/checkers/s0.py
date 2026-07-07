from __future__ import annotations

import re
from typing import Any

from novelscript.checkers.base import CheckerReport
from novelscript.index.must_keep import parse_rulings_from_story_engine

CORE_ENGINE_ALIASES = ("核心爽点", "故事发动机", "四台故事发动机", "四台核心发动机")
RULING_ALIASES = ("素材裁决表",)
OPTIONAL_SECTION_ALIASES = ("可删支线", "可删", "可合并")
MIN_MUST_KEEP_RULINGS = 10

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


def _count_ruling_rows(md_text: str) -> tuple[int, list[str]]:
    issues: list[str] = []
    rulings = parse_rulings_from_story_engine(md_text)
    mk_rulings = {k: v for k, v in rulings.items() if k.startswith("mk_")}
    for card_id, data in mk_rulings.items():
        if not data.get("verdict"):
            issues.append(f"ruling {card_id}: missing verdict")
    return len(mk_rulings), issues


def _count_legacy_must_keep_rows(md_text: str) -> tuple[int, list[str]]:
    issues: list[str] = []
    rows = 0
    in_table = False
    for line in md_text.splitlines():
        if "名场面必保清单" in line:
            in_table = True
            continue
        if in_table and line.startswith("## ") and "必保" not in line:
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
    return rows, issues


def check_s0_story_engine(md_text: str, *, source_cards: dict[str, Any] | None = None) -> CheckerReport:
    report = CheckerReport(stage="S0", passed=True)
    if not _has_section(md_text, CORE_ENGINE_ALIASES):
        report.add_issue("Missing section: 核心爽点 / 四台核心发动机")

    has_rulings = _has_section(md_text, RULING_ALIASES)
    has_legacy_mk = _has_section(md_text, ("名场面必保清单", "必保名场面清单"))

    if not has_rulings and not has_legacy_mk:
        report.add_issue("Missing section: 素材裁决表")
    if not any(alias in md_text for alias in OPTIONAL_SECTION_ALIASES):
        report.add_warning("Missing deletable subplot section")

    if has_rulings:
        ruling_rows, row_issues = _count_ruling_rows(md_text)
        for issue in row_issues:
            report.add_issue(issue)

        if source_cards and source_cards.get("must_keep"):
            mk_cards = source_cards["must_keep"]
            rulings = parse_rulings_from_story_engine(md_text)
            for card in mk_cards:
                card_id = str(card.get("id", "")).lower()
                if not card_id:
                    continue
                if card_id not in rulings:
                    report.add_issue(f"must_keep card {card_id} missing from 素材裁决表")
                else:
                    verdict = rulings[card_id].get("verdict", "")
                    if not any(v in verdict for v in ("保留", "合并", "删除")):
                        report.add_issue(f"ruling {card_id}: invalid verdict '{verdict}'")
            if ruling_rows < len(mk_cards):
                report.add_issue(f"ruling rows {ruling_rows} < must_keep cards {len(mk_cards)}")
        elif ruling_rows < MIN_MUST_KEEP_RULINGS:
            report.add_issue(f"must_keep rulings {ruling_rows} < {MIN_MUST_KEEP_RULINGS}")
    elif has_legacy_mk:
        legacy_rows, _ = _count_legacy_must_keep_rows(md_text)
        if legacy_rows < MIN_MUST_KEEP_RULINGS:
            report.add_issue(f"must_keep rows {legacy_rows} < {MIN_MUST_KEEP_RULINGS}")

    engine_count = _count_engines(md_text)
    if engine_count < 4:
        report.add_issue(f"story engines {engine_count} < 4")

    summary_hits = len(re.findall(r"(然后|接着|之后|随后).{0,8}(然后|接着|之后)", md_text))
    if summary_hits >= 3:
        report.add_warning("Possible plot-summary tone (链式然后/接着); engines should explain why readers chase")

    if not report.hard_fail:
        report.passed = True
    return report

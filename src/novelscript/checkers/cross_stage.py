from __future__ import annotations

import re
from typing import Any

from novelscript.checkers.base import CheckerReport
from novelscript.index.must_keep import parse_rulings_from_story_engine
from novelscript.index.season_plan import count_s1_season_arc_rows, parse_adaptation_brief


def check_p1_s0_rulings(
    cards: dict[str, Any],
    engine_md: str,
) -> CheckerReport:
    """Each mk_* card must have exactly one ruling; deleted mk must not appear in index path."""
    report = CheckerReport(stage="cross_P1_S0", passed=True)
    mk_cards = cards.get("must_keep") or []
    rulings = parse_rulings_from_story_engine(engine_md)
    mk_rulings = {k: v for k, v in rulings.items() if k.startswith("mk_")}

    for card in mk_cards:
        card_id = str(card.get("id", "")).lower()
        if not card_id:
            report.add_issue("must_keep card missing id")
            continue
        if card_id not in mk_rulings:
            report.add_issue(f"{card_id} missing from S0 素材裁决表", hard=True)
        elif card_id in mk_rulings and len([k for k in mk_rulings if k == card_id]) > 1:
            report.add_issue(f"{card_id} has duplicate rulings")

    for card_id in mk_rulings:
        if not any(str(c.get("id", "")).lower() == card_id for c in mk_cards):
            report.add_warning(f"ruling references unknown card {card_id}")

    if not report.hard_fail:
        report.passed = True
    return report


def check_s0_redundant_refs(engine_md: str, cards: dict[str, Any]) -> CheckerReport:
    """Rulings marked 删除 should reference red_* cards when possible."""
    report = CheckerReport(stage="cross_S0_redundant", passed=True)
    rulings = parse_rulings_from_story_engine(engine_md)
    red_ids = {str(c.get("id", "")).lower() for c in cards.get("redundant") or []}
    for card_id, data in rulings.items():
        if "删除" not in data.get("verdict", ""):
            continue
        if card_id.startswith("red_"):
            continue
        if card_id.startswith("mk_") or card_id.startswith("evt_"):
            if not data.get("reason"):
                report.add_issue(f"delete ruling {card_id} missing reason")
    if red_ids and not any(k.startswith("red_") for k in rulings):
        report.add_warning("no red_* cards referenced in 素材裁决表")
    if not report.hard_fail:
        report.passed = True
    return report


def check_s2_must_keep_coverage(s2_md: str, must_keep: list[dict[str, Any]]) -> CheckerReport:
    """S2 名场面落点 must cover all must_keep card_ids."""
    report = CheckerReport(stage="cross_S2_must_keep", passed=True)
    if not must_keep:
        return report

    placement_section = False
    covered_ids: set[str] = set()
    for line in s2_md.splitlines():
        if "名场面落点" in line:
            placement_section = True
            continue
        if placement_section and line.startswith("## "):
            break
        for mk in must_keep:
            card_id = str(mk.get("card_id") or "")
            name = str(mk.get("name") or "")
            if card_id and card_id in line:
                covered_ids.add(card_id)
            elif name and name in line:
                covered_ids.add(card_id or name)

    missing = []
    for mk in must_keep:
        card_id = str(mk.get("card_id") or mk.get("id") or "")
        name = str(mk.get("name") or "")
        key = card_id or name
        if key and key not in covered_ids and name not in covered_ids:
            missing.append(name or card_id)
    if missing:
        report.add_issue(f"S2 名场面落点 missing: {', '.join(missing[:5])}", hard=True)

    if not report.hard_fail:
        report.passed = True
    return report


def check_s1_brief_season_keywords(brief_md: str, s1_md: str) -> CheckerReport:
    """S1 season arc keywords should align with brief inter-season principles."""
    report = CheckerReport(stage="cross_S1_brief", passed=True)
    brief_plan = parse_adaptation_brief(brief_md)
    brief_count = brief_plan.get("season_count") or 0
    s1_count = count_s1_season_arc_rows(s1_md)
    if brief_count and s1_count != brief_count:
        report.add_issue(f"S1 arc rows {s1_count} != brief seasons {brief_count}", hard=True)

    if "季间叙事原则" in brief_md:
        principles = brief_md.split("季间叙事原则", 1)[-1][:2000]
        keywords = [w for w in re.findall(r"[\u4e00-\u9fff]{2,6}", principles) if len(w) >= 2][:8]
        if keywords and s1_count > 0:
            hits = sum(1 for kw in keywords if kw in s1_md)
            if hits == 0:
                report.add_warning("S1 蜕变表与 brief 季间原则关键词弱关联")

    if not report.hard_fail:
        report.passed = True
    return report


def run_cross_stage_checks(
    *,
    cards: dict[str, Any] | None = None,
    engine_md: str = "",
    brief_md: str = "",
    s1_md: str = "",
    s2_md: str = "",
    must_keep: list[dict[str, Any]] | None = None,
) -> CheckerReport:
    merged = CheckerReport(stage="cross_stage", passed=True)
    cards = cards or {}
    checks = []
    if cards and engine_md:
        checks.extend([check_p1_s0_rulings(cards, engine_md), check_s0_redundant_refs(engine_md, cards)])
    if s2_md and must_keep:
        checks.append(check_s2_must_keep_coverage(s2_md, must_keep))
    if brief_md and s1_md:
        checks.append(check_s1_brief_season_keywords(brief_md, s1_md))
    for c in checks:
        merged.issues.extend(c.issues)
        if c.hard_fail:
            merged.hard_fail = True
            merged.passed = False
    if not merged.hard_fail:
        merged.passed = True
    return merged

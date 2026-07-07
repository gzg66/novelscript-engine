from __future__ import annotations

import re
from typing import Any

from novelscript.checkers.base import CheckerReport

MIN_EVENT_CARDS = 10
MIN_CHARACTER_CARDS = 3
CARD_ID_RE = re.compile(r"^(evt|mk|red|chr|rel|wb)_\d+$", re.I)

_SECTION_MAP = {
    "事件卡": "events",
    "名场面卡": "must_keep",
    "冗余卡": "redundant",
    "角色卡": "characters",
    "关系卡": "relationships",
    "世界观卡": "worldbuilding",
}


def _parse_table_row(cells: list[str], section: str) -> dict[str, Any] | None:
    if len(cells) < 2:
        return None
    first = cells[0].strip()
    if first in ("#", "标题", "名场面", "id", "ID", "卡id"):
        return None

    row: dict[str, Any] = {}
    if CARD_ID_RE.match(first):
        row["id"] = first.lower()
        cells = cells[1:]

    if section == "events":
        if len(cells) < 4:
            return None
        row.update({"title": cells[0], "source_ref": cells[1], "function": cells[2], "mobility": cells[3]})
    elif section == "must_keep":
        if len(cells) < 4:
            return None
        row.update(
            {
                "title": cells[0],
                "source_ref": cells[1],
                "emotion_function": cells[2],
                "why_irreducible": cells[3],
            }
        )
    elif section == "redundant":
        if len(cells) < 4:
            return None
        row.update({"title": cells[0], "source_ref": cells[1], "reason": cells[2], "suggestion": cells[3]})
    elif section == "characters":
        if len(cells) < 4:
            return None
        row.update({"name": cells[0], "role": cells[1], "desire": cells[2], "function": cells[3]})
    elif section == "relationships":
        if len(cells) < 3:
            return None
        pair_raw = cells[0]
        pair = [p.strip() for p in re.split(r"[,、/]", pair_raw) if p.strip()]
        row.update({"pair": pair, "arc": cells[1], "source_ref": cells[2] if len(cells) > 2 else ""})
    elif section == "worldbuilding":
        if len(cells) < 3:
            return None
        row.update({"rule": cells[0], "visual": cells[1], "first_seen": cells[2]})
    else:
        return None
    return row


def parse_source_cards_md(md_text: str) -> dict[str, list[dict[str, Any]]]:
    cards: dict[str, list[dict[str, Any]]] = {
        "events": [],
        "must_keep": [],
        "redundant": [],
        "characters": [],
        "relationships": [],
        "worldbuilding": [],
    }
    section = ""
    counters = {"evt": 0, "mk": 0, "red": 0, "chr": 0, "rel": 0, "wb": 0}

    for line in md_text.splitlines():
        for heading, key in _SECTION_MAP.items():
            if line.startswith(f"## {heading}"):
                section = key
                break
        else:
            if not line.strip().startswith("|") or not section:
                continue
            if re.match(r"^\|[-\s|]+\|$", line):
                continue
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            row = _parse_table_row(cells, section)
            if not row:
                continue
            if "id" not in row:
                prefix = {"events": "evt", "must_keep": "mk", "redundant": "red", "characters": "chr", "relationships": "rel", "worldbuilding": "wb"}[
                    section
                ]
                counters[prefix] += 1
                row["id"] = f"{prefix}_{counters[prefix]:03d}"
            cards[section].append(row)
    return cards


def check_source_cards(md_text: str) -> CheckerReport:
    report = CheckerReport(stage="P1", passed=True)
    cards = parse_source_cards_md(md_text)
    events = cards["events"]
    if len(events) < MIN_EVENT_CARDS:
        report.add_issue(f"event cards {len(events)} < {MIN_EVENT_CARDS}")
    for idx, card in enumerate(events[:20], start=1):
        if not card.get("source_ref") or not re.search(r"Ch\s*\d+", str(card["source_ref"]), re.I):
            report.add_issue(f"event card {idx}: missing source_ref (Ch…)")
        if not card.get("function"):
            report.add_issue(f"event card {idx}: missing dramatic function")
    for idx, card in enumerate(cards["must_keep"][:20], start=1):
        if not card.get("emotion_function") and not card.get("why_irreducible"):
            report.add_issue(f"must_keep card {idx}: missing emotion function")
        if not card.get("id", "").startswith("mk_"):
            report.add_issue(f"must_keep card {idx}: missing mk_* id")
    if len(cards["characters"]) < MIN_CHARACTER_CARDS:
        report.add_issue(f"character cards {len(cards['characters'])} < {MIN_CHARACTER_CARDS}")
    for section in ("events", "must_keep", "redundant", "characters", "relationships", "worldbuilding"):
        for card in cards[section]:
            cid = card.get("id", "")
            if cid and not CARD_ID_RE.match(str(cid)):
                report.add_issue(f"invalid card id: {cid}")
    if not report.hard_fail:
        report.passed = True
    return report


def cards_to_json(cards: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
    return cards

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

from novelscript.io.atomic import write_json


def parse_must_keep_from_story_engine(md_text: str) -> list[dict[str, Any]]:
    """Legacy: extract must_keep_scenes table from old S0_story_engine.md format."""
    scenes: list[dict[str, Any]] = []
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
            scene_id = int(cells[0].lstrip("#").strip())
        except ValueError:
            continue
        name = cells[1]
        source_raw = cells[2]
        why = cells[3] if len(cells) > 3 else ""
        chapters = _parse_chapter_refs(source_raw)
        scenes.append(
            {
                "id": scene_id,
                "card_id": f"mk_{scene_id:03d}",
                "name": name,
                "source_chapters": chapters,
                "engines": _infer_engines(name),
                "why_irreducible": why,
                "season_id": None,
                "episode_id": None,
                "scene_id": None,
                "key_dialogue_ids": [],
            }
        )
    return scenes


def parse_rulings_from_story_engine(md_text: str) -> dict[str, dict[str, str]]:
    """Parse 素材裁决表 from S0_story_engine.md → {card_id: {verdict, reason, engine}}."""
    rulings: dict[str, dict[str, str]] = {}
    in_table = False
    for line in md_text.splitlines():
        if "素材裁决表" in line:
            in_table = True
            continue
        if in_table and line.startswith("## ") and "裁决" not in line:
            break
        if not in_table or not line.strip().startswith("|"):
            continue
        if re.match(r"^\|[-\s|]+\|$", line):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) < 2:
            continue
        card_id = cells[0].strip()
        if not re.match(r"^(mk|evt|red|chr|rel|wb)_\d+", card_id, re.I):
            if card_id.lower() in ("card_id", "卡id", "素材卡"):
                continue
            continue
        verdict = cells[1] if len(cells) > 1 else ""
        reason = cells[2] if len(cells) > 2 else ""
        engine = cells[3] if len(cells) > 3 else ""
        rulings[card_id.lower()] = {
            "verdict": verdict,
            "reason": reason,
            "engine": engine,
        }
    return rulings


def parse_strategy_must_keep_revisions(md_text: str) -> dict[str, str]:
    """Parse P3 策略修订: mk_* → 降级|升保|保留."""
    revisions: dict[str, str] = {}
    in_section = False
    for line in md_text.splitlines():
        if "策略修订" in line:
            in_section = True
            continue
        if in_section and line.startswith("## "):
            break
        if not in_section:
            continue
        if line.strip().startswith("|"):
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            if len(cells) < 2:
                continue
            card_id = cells[0].strip().lower()
            if re.match(r"^mk_\d+", card_id):
                revisions[card_id] = cells[1]
        else:
            m = re.search(r"(mk_\d+)\s*[：:]\s*(降级|升保|保留|删除)", line, re.I)
            if m:
                revisions[m.group(1).lower()] = m.group(2)
    return revisions


_KEEP_VERDICTS = ("保留", "合并", "升保")
_DROP_VERDICTS = ("删除", "降级")


def build_must_keep_from_cards(
    cards: dict[str, Any],
    rulings: dict[str, dict[str, str]],
    *,
    strategy_revisions: dict[str, str] | None = None,
) -> list[dict[str, Any]]:
    """P1 must_keep cards + S0 rulings (+ optional P3 revisions) → must_keep_scenes.json."""
    strategy_revisions = strategy_revisions or {}
    scenes: list[dict[str, Any]] = []
    seq = 1
    for card in cards.get("must_keep") or []:
        card_id = str(card.get("id") or "").lower()
        if not card_id:
            card_id = f"mk_{seq:03d}"
        ruling = rulings.get(card_id, {})
        verdict = strategy_revisions.get(card_id) or ruling.get("verdict", "保留")
        if any(v in verdict for v in _DROP_VERDICTS):
            continue
        if ruling and not any(v in verdict for v in _KEEP_VERDICTS):
            if "删除" in verdict:
                continue
        engine_raw = ruling.get("engine", "")
        engines = [e.strip() for e in re.split(r"[,、/]", engine_raw) if e.strip()] or _infer_engines(
            str(card.get("title") or "")
        )
        chapters = _parse_chapter_refs(str(card.get("source_ref") or ""))
        scenes.append(
            {
                "id": seq,
                "card_id": card_id,
                "name": card.get("title") or card.get("name") or "",
                "source_chapters": chapters,
                "engines": engines,
                "why_irreducible": card.get("why_irreducible") or card.get("emotion_function") or ruling.get("reason", ""),
                "season_id": None,
                "episode_id": None,
                "scene_id": None,
                "key_dialogue_ids": [],
            }
        )
        seq += 1
    return scenes


def _parse_chapter_refs(text: str) -> list[int]:
    chapters: set[int] = set()
    for start, end in re.findall(r"Ch\s*(\d+)\s*[–\-]\s*(\d+)", text, re.IGNORECASE):
        chapters.update(range(int(start), int(end) + 1))
    for m in re.finditer(r"Ch\s*(\d+)", text, re.IGNORECASE):
        chapters.add(int(m.group(1)))
    if not chapters:
        for start, end in re.findall(r"(\d+)\s*[–\-]\s*(\d+)", text):
            chapters.update(range(int(start), int(end) + 1))
        for m in re.finditer(r"(\d+)", text):
            chapters.add(int(m.group(1)))
    return sorted(chapters)


def _infer_engines(name: str) -> list[str]:
    engines: list[str] = []
    keywords = {
        "逆袭": ["逆袭", "冻", "igloo", "立威", "分院"],
        "双男主拉扯": ["丝带", "特洛伊", "王储", "舞会"],
        "命定之恋": ["定情", "求婚", "ribbon", "龙巢", "mate"],
        "身世之谜": ["穿越", "灵魂", "神之", "裂隙", "四神"],
    }
    for engine, kws in keywords.items():
        if any(kw in name for kw in kws):
            engines.append(engine)
    return engines or ["逆袭"]


def load_must_keep(path: Path) -> list[dict[str, Any]]:
    return json.loads(path.read_text(encoding="utf-8"))


def save_must_keep(path: Path, scenes: list[dict[str, Any]]) -> None:
    write_json(path, scenes)


def load_source_cards(cards_path: Path) -> dict[str, Any]:
    if cards_path.exists():
        return json.loads(cards_path.read_text(encoding="utf-8"))
    return {}


def build_must_keep_index(
    story_engine_path: Path,
    index_dir: Path,
    *,
    cards_path: Path | None = None,
    strategy_path: Path | None = None,
) -> list[dict[str, Any]]:
    """Build must_keep_scenes.json from P1+S0 merge, with legacy fallback."""
    index_dir.mkdir(parents=True, exist_ok=True)
    out_path = index_dir / "must_keep_scenes.json"

    cards_json = cards_path or story_engine_path.parent / "source_cards" / "index.json"
    if cards_json.exists():
        cards = load_source_cards(cards_json)
        if cards.get("must_keep"):
            md = story_engine_path.read_text(encoding="utf-8") if story_engine_path.exists() else ""
            rulings = parse_rulings_from_story_engine(md)
            revisions: dict[str, str] = {}
            if strategy_path and strategy_path.exists():
                revisions = parse_strategy_must_keep_revisions(strategy_path.read_text(encoding="utf-8"))
            scenes = build_must_keep_from_cards(cards, rulings, strategy_revisions=revisions)
            if scenes:
                save_must_keep(out_path, scenes)
                return scenes

    if story_engine_path.exists():
        scenes = parse_must_keep_from_story_engine(story_engine_path.read_text(encoding="utf-8"))
        if scenes:
            save_must_keep(out_path, scenes)
            return scenes

    return []


def extract_must_keep_section(md_text: str) -> str:
    """Return must_keep markdown section (legacy table or rulings summary)."""
    lines: list[str] = []
    capturing = False
    for line in md_text.splitlines():
        if "名场面必保清单" in line or "素材裁决表" in line:
            capturing = True
        if capturing:
            if line.startswith("## ") and "必保" not in line and "裁决" not in line and lines:
                break
            lines.append(line)
    return "\n".join(lines).strip()


def parse_story_engine_names(md_text: str) -> list[str]:
    """Extract the four core engine names from S0_story_engine.md."""
    names: list[str] = []
    for line in md_text.splitlines():
        m = re.match(r"^###\s+引擎\s*\d+\s*[：:]\s*(.+)$", line.strip())
        if m:
            names.append(m.group(1).strip())
    if len(names) >= 4:
        return names[:4]
    for m in re.finditer(r"引擎\s*\d+\s*[：:]\s*([^\n|]+)", md_text):
        name = m.group(1).strip()
        if name and name not in names:
            names.append(name)
    return names

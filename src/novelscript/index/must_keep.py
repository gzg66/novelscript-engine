from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from novelscript.io.atomic import write_json


def parse_must_keep_from_story_engine(md_text: str) -> list[dict[str, Any]]:
    """Extract must_keep_scenes table from S0_story_engine.md."""
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


def _parse_chapter_refs(text: str) -> list[int]:
    chapters: set[int] = set()
    for m in re.finditer(r"Ch\s*(\d+)", text, re.IGNORECASE):
        chapters.add(int(m.group(1)))
    if not chapters:
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
    import json

    return json.loads(path.read_text(encoding="utf-8"))


def save_must_keep(path: Path, scenes: list[dict[str, Any]]) -> None:
    write_json(path, scenes)


def build_must_keep_index(story_engine_path: Path, index_dir: Path) -> list[dict[str, Any]]:
    md = story_engine_path.read_text(encoding="utf-8")
    scenes = parse_must_keep_from_story_engine(md)
    index_dir.mkdir(parents=True, exist_ok=True)
    save_must_keep(index_dir / "must_keep_scenes.json", scenes)
    return scenes

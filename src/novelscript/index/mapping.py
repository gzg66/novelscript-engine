from __future__ import annotations

import json
import re
from typing import Any

from novelscript.checkers.s2 import parse_season_map_md

# Keywords to map must_keep names → script content (better than naive token overlap)
MUST_KEEP_HINTS: dict[str, list[str]] = {
    "雨夜": ["雨", "溺", "桥", "车", "河", "水"],
    "结冰": ["冰", "冰晶", "冰刺", "掌心"],
    "教授": ["教授", "天赋", "测试", "罕见"],
    "冰封": ["冰", "客厅", "冰痕", "冰封"],
    "冻": ["冻", "冰", "凯"],
    "晚宴": ["晚宴", "dinner", "托伊", "troy", "餐桌", "座位"],
    "舞会": ["舞会", "ball", "共舞", "dance", "舞池"],
    "丝带": ["丝带", "ribbon", "骑士", "比武"],
    "igloo": ["igloo", "冰屋", "冰门"],
    "十二箱": ["十二", "礼物", "箱"],
    "暗血龙": ["暗血", "龙", "德斯蒙德", "舞会"],
    "冰霜暴走": ["走廊", "冰封", "暴走"],
    "分院": ["分院", "战斗系", "拱门"],
    "龙形": ["龙", "真身", "悬崖"],
    "定情": ["龙巢", "mate", "定情"],
    "求婚": ["求婚", "戒指", "雪夜"],
    "四神": ["神", "拱门", "四神"],
    "裂隙": ["裂隙", "决战", "恶魔"],
}


def map_must_keep_to_seasons(
    must_keep: list[dict[str, Any]],
    season_map_md: str,
) -> list[dict[str, Any]]:
    seasons = parse_season_map_md(season_map_md)
    updated = []
    for scene in must_keep:
        item = dict(scene)
        chapters = set(scene.get("source_chapters") or [])
        for season in seasons:
            if chapters & set(season.get("chapter_range") or []):
                item["season_id"] = season["season_id"]
                break
        updated.append(item)
    return updated


def map_must_keep_to_episodes(
    must_keep: list[dict[str, Any]],
    episodes: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    updated = []
    for scene in must_keep:
        item = dict(scene)
        chapters = set(scene.get("source_chapters") or [])
        name = scene.get("name", "")
        best_ep = None
        best_score = -1
        for ep in episodes:
            ep_chs = set(ep.get("source_chapters") or [])
            overlap = len(chapters & ep_chs)
            if overlap == 0:
                continue
            logline = ep.get("logline", "") + ep.get("core_conflict", "")
            name_bonus = sum(1 for token in _name_tokens(name) if token in logline)
            tight_bonus = max(0, 6 - len(ep_chs))
            score = overlap * 10 + name_bonus * 3 + tight_bonus
            if score > best_score:
                best_score = score
                best_ep = ep["episode_id"]
        if best_ep:
            item["episode_id"] = best_ep
        updated.append(item)
    return updated


def map_must_keep_to_scenes(
    must_keep: list[dict[str, Any]],
    script: dict[str, Any],
) -> list[dict[str, Any]]:
    ep_id = script.get("episode_id")
    updated = []
    for scene in must_keep:
        item = dict(scene)
        if item.get("episode_id") != ep_id:
            updated.append(item)
            continue
        matched = _best_scene_match(scene.get("name", ""), script.get("scenes") or [])
        if matched:
            item["scene_id"] = matched
        updated.append(item)
    return updated


def _best_scene_match(name: str, scenes: list[dict[str, Any]]) -> str | None:
    best_id: str | None = None
    best_score = 0
    for sc in scenes:
        blob = json.dumps(sc, ensure_ascii=False).lower()
        score = _score_name_against_blob(name, blob)
        if score > best_score:
            best_score = score
            best_id = sc.get("scene_id")
    return best_id if best_score >= 2 else None


def _score_name_against_blob(name: str, blob: str) -> int:
    score = 0
    for token in _name_tokens(name):
        if token in blob:
            score += 2
    for key, hints in MUST_KEEP_HINTS.items():
        if key in name:
            score += sum(1 for h in hints if h.lower() in blob)
    return score


def _name_tokens(name: str) -> list[str]:
    chunks = re.findall(r"[\u4e00-\u9fff]{2,}", name)
    out: list[str] = []
    for chunk in chunks:
        out.append(chunk)
        if len(chunk) > 2:
            out.extend(chunk[i : i + 2] for i in range(len(chunk) - 1))
    return list(dict.fromkeys(out))[:24]

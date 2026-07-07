from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from novelscript.io.atomic import write_json
from novelscript.pipeline.context import ProjectContext
from novelscript.stages.source import novel_content_hash

STAGE_ORDER = ("P0", "stage0", "index", "P1", "S0", "brief", "P3", "S1", "S2", "S3", "S4", "S5", "P6")

STAGE_INPUTS: dict[str, list[str]] = {
    "P0": ["novel_hash"],
    "stage0": ["novel_hash", "preference_hash"],
    "index": ["novel_hash"],
    "P1": ["stage0_outline_hash", "novel_hash", "preference_hash"],
    "S0": ["source_cards_hash"],
    "brief": ["source_cards_hash", "s0_engine_hash", "preference_hash"],
    "P3": ["source_cards_hash", "s0_engine_hash", "brief_hash", "preference_hash"],
    "S1": ["brief_hash", "s0_engine_hash", "source_cards_hash", "preference_hash"],
    "S2": ["brief_hash", "s0_engine_hash", "strategy_hash", "source_cards_hash", "must_keep_hash"],
    "S3": ["strategy_hash", "must_keep_hash"],
    "S4": ["must_keep_hash"],
    "S5": ["must_keep_hash"],
    "P6": [],
}

_STAGE_OUTPUTS: dict[str, list[str]] = {
    "P0": ["project_preference.md"],
    "stage0": ["input/stage0/outline.md", "input/stage0/characters.md"],
    "P1": ["source_cards/index.md", "source_cards/index.json"],
    "S0": ["S0_story_engine.md"],
    "brief": ["S0_adaptation_brief.md"],
    "P3": ["adaptation_strategy.md", "index/must_keep_scenes.json"],
    "S1": ["S1_series_premise.md", "S1_character_bible.md"],
    "S2": ["S2_season_map.md"],
}


def _file_hash(path: Path) -> str:
    if not path.exists() or path.stat().st_size == 0:
        return ""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def compute_input_hashes(ctx: ProjectContext) -> dict[str, str]:
    root = ctx.root
    return {
        "novel_hash": novel_content_hash(ctx),
        "preference_hash": _file_hash(root / "project_preference.md"),
        "stage0_outline_hash": _file_hash(root / "input" / "stage0" / "outline.md"),
        "source_cards_hash": _file_hash(root / "source_cards" / "index.json")
        or _file_hash(root / "source_cards" / "index.md"),
        "s0_engine_hash": _file_hash(root / "S0_story_engine.md"),
        "brief_hash": _file_hash(root / "S0_adaptation_brief.md"),
        "strategy_hash": _file_hash(root / "adaptation_strategy.md"),
        "must_keep_hash": _file_hash(ctx.index_dir / "must_keep_scenes.json"),
    }


def stage_inputs_valid(ctx: ProjectContext, stage: str) -> bool:
    """Return False when upstream inputs changed since stage last succeeded."""
    stage = stage.lower() if stage in ("stage0", "index", "brief") else stage.upper()
    if stage.startswith("S") and stage[1:].isdigit():
        stage = stage
    elif stage.startswith("s"):
        stage = stage.upper()

    keys = STAGE_INPUTS.get(stage) or STAGE_INPUTS.get(stage.lower())
    if not keys:
        return True

    meta = ctx.meta.get("stage_input_hashes") or {}
    stored = meta.get(stage)
    if not stored:
        return True

    current = compute_input_hashes(ctx)
    return all(stored.get(k) == current.get(k) for k in keys)


def persist_stage_hashes(ctx: ProjectContext, stage: str) -> None:
    stage_key = stage
    if stage.lower() in ("stage0", "index", "brief"):
        stage_key = stage.lower()
    elif stage.upper().startswith("S") or stage.upper().startswith("P"):
        stage_key = stage.upper().split("_")[0]

    keys = STAGE_INPUTS.get(stage_key, [])
    if not keys:
        return

    meta = dict(ctx.meta)
    all_hashes = meta.get("stage_input_hashes") or {}
    snapshot = {k: compute_input_hashes(ctx).get(k, "") for k in keys}
    all_hashes[stage_key] = snapshot
    meta["stage_input_hashes"] = all_hashes
    write_json(ctx.root / "project.meta.json", meta)
    ctx.meta = meta


def downstream_stages(stage: str) -> list[str]:
    stage_norm = stage
    if stage.lower() in ("stage0", "index", "brief"):
        stage_norm = stage.lower()
    else:
        stage_norm = stage.upper().split("_")[0]
    if stage_norm not in STAGE_ORDER:
        return []
    idx = STAGE_ORDER.index(stage_norm)
    return list(STAGE_ORDER[idx + 1 :])


def _clear_season_artifacts(ctx: ProjectContext, pattern: str) -> list[str]:
    removed: list[str] = []
    seasons = ctx.root / "seasons"
    if not seasons.is_dir():
        return removed
    for path in seasons.glob(pattern):
        path.unlink()
        removed.append(path.relative_to(ctx.root).as_posix())
    return removed


def invalidate_downstream(ctx: ProjectContext, stage: str) -> list[str]:
    """Remove downstream stage outputs so cache cannot mask stale upstream changes."""
    removed: list[str] = []
    downstream = downstream_stages(stage)
    for ds in downstream:
        for rel in _STAGE_OUTPUTS.get(ds, []):
            path = ctx.root / rel
            if path.exists():
                path.unlink()
                removed.append(rel)
        if ds == "S3":
            removed.extend(_clear_season_artifacts(ctx, "**/episode_list.md"))
        elif ds == "S4":
            removed.extend(_clear_season_artifacts(ctx, "**/beat_sheet.md"))
        elif ds == "S5":
            removed.extend(_clear_season_artifacts(ctx, "**/script.md"))
            removed.extend(_clear_season_artifacts(ctx, "**/script.json"))

    meta = dict(ctx.meta)
    hashes = dict(meta.get("stage_input_hashes") or {})
    for ds in downstream:
        hashes.pop(ds, None)
    meta["stage_input_hashes"] = hashes
    write_json(ctx.root / "project.meta.json", meta)
    ctx.meta = meta
    return removed

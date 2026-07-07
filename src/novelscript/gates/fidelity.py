from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from novelscript.checkers.base import CheckerReport


def run_fidelity_audit(
    *,
    must_keep: list[dict[str, Any]],
    story_engines: list[str],
    episodes: list[dict[str, Any]],
    scripts: dict[str, dict[str, Any]],
    season_id: str = "S1",
    min_engine_episodes: int = 3,
    scope_episode_ids: list[str] | None = None,
) -> dict[str, Any]:
    min_hits = min(min_engine_episodes, max(1, len(episodes) // 2)) if episodes else min_engine_episodes
    produced_ids = set(scripts.keys())
    scope = set(scope_episode_ids or [])
    coverage = []
    for scene in must_keep:
        sid = scene.get("season_id")
        if sid and sid != season_id:
            continue
        ep_id = scene.get("episode_id")
        if scope and ep_id and ep_id not in scope:
            continue
        if ep_id and produced_ids and ep_id not in produced_ids:
            continue
        status = "mapped" if scene.get("scene_id") and scene.get("episode_id") else "missing"
        coverage.append(
            {
                "id": scene.get("id"),
                "season_id": sid or season_id,
                "episode_id": scene.get("episode_id"),
                "scene_id": scene.get("scene_id"),
                "status": status,
            }
        )

    active_engines = sorted({e for ep in episodes for e in (ep.get("serves_engines") or [])})
    targets = active_engines or story_engines
    engine_supply = []
    for engine in targets:
        served = [ep["episode_id"] for ep in episodes if engine in (ep.get("serves_engines") or [])]
        engine_supply.append(
            {
                "engine_id": engine,
                "episodes_served": served,
                "min_per_season_met": len(served) >= min_hits,
            }
        )

    issues = []
    for item in coverage:
        if item["status"] == "missing":
            issues.append(f"must_keep #{item['id']} not mapped to scene")

    for item in engine_supply:
        if not item["min_per_season_met"]:
            issues.append(f"engine {item['engine_id']} served by < {min_hits} episodes")

    verdict = "pass" if not issues else "fail"
    return {
        "verdict": verdict,
        "must_keep_coverage": coverage,
        "engine_supply": engine_supply,
        "key_dialogue_preserved": [],
        "issues": issues,
    }


def check_fidelity_report(report: dict[str, Any]) -> CheckerReport:
    result = CheckerReport(stage="fidelity", passed=report.get("verdict") == "pass")
    if report.get("verdict") != "pass":
        result.hard_fail = True
        for issue in report.get("issues") or []:
            result.add_issue(issue)
    return result


def save_fidelity_report(report: dict[str, Any], audit_dir: Path, *, name: str) -> Path:
    audit_dir.mkdir(parents=True, exist_ok=True)
    out = audit_dir / f"fidelity_report.{name}.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return out

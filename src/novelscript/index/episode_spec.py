from __future__ import annotations

import re
from typing import Any

from novelscript.index.season_plan import parse_adaptation_brief
from novelscript.pipeline.context import ProjectContext

DEFAULT_DURATION_SEC = 150
DEFAULT_TOLERANCE_PCT = 15
DEFAULT_HOOK_SEC = 15


def _parse_duration_sec(text: str) -> int | None:
    """Parse duration from brief cell like '2–3 分钟 / 目标 150 秒' or '150秒'."""
    if not text.strip():
        return None
    # Explicit target: 目标 150 秒 / 目标150s
    target = re.search(r"目标\s*(\d+)\s*(?:秒|s|sec)?", text, re.I)
    if target:
        return int(target.group(1))
    # Single seconds value
    sec_only = re.search(r"(\d+)\s*(?:秒|s|sec)\b", text, re.I)
    if sec_only and "分钟" not in text and "分" not in text:
        return int(sec_only.group(1))
    # Minute range: 2–3 分钟 → midpoint in seconds
    minute_range = re.search(r"(\d+)\s*[–\-—~至]\s*(\d+)\s*分", text)
    if minute_range:
        lo, hi = int(minute_range.group(1)), int(minute_range.group(2))
        return int((lo + hi) / 2 * 60)
    single_min = re.search(r"(\d+)\s*分(?:钟)?", text)
    if single_min:
        return int(single_min.group(1)) * 60
    return None


def build_episode_spec(
    *,
    duration_sec: int = DEFAULT_DURATION_SEC,
    tolerance_pct: int = DEFAULT_TOLERANCE_PCT,
    hook_sec: int = DEFAULT_HOOK_SEC,
) -> dict[str, Any]:
    tolerance_pct = max(1, min(30, tolerance_pct))
    delta = int(duration_sec * tolerance_pct / 100)
    return {
        "duration_sec": duration_sec,
        "duration_tolerance_pct": tolerance_pct,
        "min_sec": duration_sec - delta,
        "max_sec": duration_sec + delta,
        "hook_sec": hook_sec,
    }


def parse_episode_duration_from_brief(md_text: str) -> int | None:
    plan = parse_adaptation_brief(md_text)
    duration_text = plan.get("duration_text") or ""
    return _parse_duration_sec(duration_text)


def resolve_episode_spec(ctx: ProjectContext) -> dict[str, Any]:
    """Resolve episode timing spec from project.meta or adaptation brief."""
    meta_spec = ctx.meta.get("episode_spec") or {}
    if meta_spec.get("duration_sec"):
        return build_episode_spec(
            duration_sec=int(meta_spec["duration_sec"]),
            tolerance_pct=int(meta_spec.get("duration_tolerance_pct", DEFAULT_TOLERANCE_PCT)),
            hook_sec=int(meta_spec.get("hook_sec", DEFAULT_HOOK_SEC)),
        )

    brief_path = ctx.root / "S0_adaptation_brief.md"
    if brief_path.exists():
        duration = parse_episode_duration_from_brief(brief_path.read_text(encoding="utf-8"))
        if duration:
            return build_episode_spec(duration_sec=duration)

    return build_episode_spec()


def format_episode_spec_block(spec: dict[str, Any]) -> str:
    return (
        f"## 单集时长规格\n\n"
        f"- 目标时长：**{spec['duration_sec']} 秒**\n"
        f"- 容差范围：**{spec['min_sec']}–{spec['max_sec']} 秒**\n"
        f"- 集尾钩子预算：**{spec['hook_sec']} 秒**\n"
    )


def duration_in_spec(seconds: int, spec: dict[str, Any]) -> bool:
    return int(spec["min_sec"]) <= seconds <= int(spec["max_sec"])

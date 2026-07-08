from __future__ import annotations

import re
from typing import Any

from novelscript.checkers.base import CheckerReport

_CJK_RE = re.compile(r"[\u4e00-\u9fff\u3400-\u4dbf\uf900-\ufaff]")
_CHINESE_INNER_MARKERS = ("内心", "独白", "自语", "惊叫", "崩溃", "低语", "怒吼")

# Props that need a prior establishing beat in the same episode (action or dialogue).
_PROP_SETUP_HINTS: dict[str, tuple[str, ...]] = {
    "ring": ("ring", "dive", "lake bottom", "bottom of the lake"),
    "ribbon": ("ribbon", "knight", "tournament"),
}

_DEFERRED_EPISODE_MARKERS = ("ep02", "下集", "延后", "deferred", "moved to")


def _dialogue_blob(beat: dict[str, Any]) -> str:
    return f"{beat.get('dialogue') or ''} {beat.get('sound') or ''}".strip()


def contains_cjk(text: str) -> bool:
    return bool(_CJK_RE.search(text))


def check_english_dialogue(
    beats: list[dict[str, Any]],
    *,
    scene_id: str = "",
    stage: str = "dialogue",
) -> CheckerReport:
    """Spoken lines and SFX labels must be English-only (overseas audience)."""
    report = CheckerReport(stage=stage, passed=True)
    prefix = f"{scene_id} " if scene_id else ""

    for beat in beats:
        bid = beat.get("beat_id", "?")
        blob = _dialogue_blob(beat)
        if not blob:
            continue
        if contains_cjk(blob):
            report.add_issue(
                f"{prefix}beat {bid}: dialogue/sound must be English only (no Chinese labels or SFX text)"
            )
        for marker in _CHINESE_INNER_MARKERS:
            if marker in blob:
                report.add_issue(
                    f"{prefix}beat {bid}: use English speaker tags (e.g. Freya (V.O.)) not Chinese ({marker})"
                )

    if not report.hard_fail:
        report.passed = True
    return report


def _prop_deferred(prop: str, notes: list[dict[str, Any]]) -> bool:
    for row in notes:
        text = f"{row.get('source_ref', '')} {row.get('action', '')} {row.get('dramatic_reason', '')}".lower()
        if prop in text and ("adapt:defer" in text or any(m in text for m in _DEFERRED_EPISODE_MARKERS)):
            return True
    return False


def check_narrative_clarity(
    beats: list[dict[str, Any]],
    *,
    scene_id: str = "",
    adaptation_notes: list[dict[str, Any]] | None = None,
) -> CheckerReport:
    """Flag props/conflicts referenced in dialogue without prior establishment in-episode."""
    report = CheckerReport(stage="narrative_clarity", passed=True)
    notes_list = adaptation_notes or []

    prior_text = ""
    for beat in beats:
        bid = beat.get("beat_id", "?")
        blob_lower = _dialogue_blob(beat).lower()
        action = (beat.get("action") or "").lower()
        combined = f"{prior_text} {action}"

        for prop, hints in _PROP_SETUP_HINTS.items():
            if not re.search(rf"\b{re.escape(prop)}\b", blob_lower):
                continue
            if any(h in combined for h in hints):
                continue
            if _prop_deferred(prop, notes_list):
                continue
            loc = f"{scene_id} beat {bid}" if scene_id else f"beat {bid}"
            report.add_issue(
                f"{loc}: '{prop}' in dialogue without prior in-episode setup "
                f"(establish visually or cut; record adapt:defer in adaptation notes)"
            )

        prior_text = f"{prior_text} {blob_lower} {action}"

    if not report.hard_fail:
        report.passed = True
    return report


def merge_dialogue_reports(*reports: CheckerReport) -> CheckerReport:
    merged = CheckerReport(stage="dialogue", passed=True)
    for rep in reports:
        merged.issues.extend(rep.issues)
        if rep.hard_fail:
            merged.hard_fail = True
            merged.passed = False
    if not merged.hard_fail:
        merged.passed = True
    return merged

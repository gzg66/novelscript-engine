from __future__ import annotations

import re
from typing import Any, Literal

from novelscript.checkers.base import CheckerReport

_CJK_RE = re.compile(r"[\u4e00-\u9fff\u3400-\u4dbf\uf900-\ufaff]")
_CHINESE_INNER_MARKERS = ("内心", "独白", "自语", "惊叫", "崩溃", "低语", "怒吼")

# Payoff token -> bridge hints that must appear in prior action/dialogue/sound.
_CAUSAL_RULES: dict[str, tuple[str, ...]] = {
    "ring": ("ring", "dive", "lake bottom", "bottom of the lake", "searching"),
    "ribbon": ("ribbon", "knight", "tournament", "knight tournament"),
}

_DEFERRED_EPISODE_MARKERS = ("ep02", "下集", "延后", "deferred", "moved to")

# High-signal payoff patterns only (avoid false positives on beat-sheet placeholders).
_PAYOFF_PATTERNS: list[tuple[re.Pattern[str], tuple[str, ...], str]] = [
    (
        re.compile(r"\bget up and walk home\b", re.I),
        ("searching", "lantern", "calling", "shout", "why are you", "sent her", "task", "freya"),
        "task directive without prior context",
    ),
    (
        re.compile(r"\bdid you find the ring\b", re.I),
        ("searching", "lantern", "calling", "shout", "freya", "what ring", "ring"),
        "ring task without prior search context",
    ),
]

_ESTABLISHMENT_HINTS = (
    "入画",
    "灯光",
    "lantern",
    "light",
    "approach",
    "shout",
    "calling",
    "呼喊",
    "远处",
    "distant",
    "enter",
    "enters",
    "appear",
    "emerge",
)

_SPEAKER_RE = re.compile(r"^([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)\s*[\(:]")


def _dialogue_blob(beat: dict[str, Any]) -> str:
    return f"{beat.get('dialogue') or ''} {beat.get('sound') or ''}".strip()


def _beat_action_text(beat: dict[str, Any]) -> str:
    return str(beat.get("action") or beat.get("externalization") or "")


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
        text = (
            f"{row.get('source_ref', '')} {row.get('action', '')} "
            f"{row.get('dramatic_reason', '')} {row.get('viewer_substitute', '')}"
        ).lower()
        if prop in text and ("adapt:defer" in text or any(m in text for m in _DEFERRED_EPISODE_MARKERS)):
            return True
    return False


def _has_bridge(combined_prior: str, hints: tuple[str, ...]) -> bool:
    return any(h in combined_prior for h in hints)


def _extract_speakers(dialogue: str) -> list[str]:
    speakers: list[str] = []
    for line in dialogue.splitlines():
        match = _SPEAKER_RE.match(line.strip())
        if match:
            speakers.append(match.group(1))
    return speakers


def _speaker_established(speaker: str, combined: str, beat: dict[str, Any]) -> bool:
    speaker_lower = speaker.lower()
    if speaker_lower in combined:
        return True
    action_text = _beat_action_text(beat).lower()
    if speaker_lower in action_text:
        return True
    # First name token often appears in action (e.g. "Professor Arsene enters")
    first = speaker_lower.split()[0]
    return len(first) >= 4 and first in combined


def _is_prop_question(blob_lower: str, prop: str) -> bool:
    """Audience-proxy confusion lines (What ring?) are bridges, not payoffs."""
    return bool(
        re.search(rf"\b(what|where|which)\b[^.\"]{{0,30}}\b{re.escape(prop)}\b", blob_lower)
    )


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
        action = _beat_action_text(beat).lower()
        combined = f"{prior_text} {action}"

        for prop, hints in _CAUSAL_RULES.items():
            if not re.search(rf"\b{re.escape(prop)}\b", blob_lower):
                continue
            if _is_prop_question(blob_lower, prop):
                continue
            if _has_bridge(combined, hints):
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


def check_causal_chain(
    beats: list[dict[str, Any]],
    *,
    scene_id: str = "",
    adaptation_notes: list[dict[str, Any]] | None = None,
    tier: Literal["beat_sheet", "script"] = "script",
) -> CheckerReport:
    """Detect 'cut bridges, keep payoff dialogue' incoherence patterns."""
    report = CheckerReport(stage="causal_chain", passed=True)
    notes_list = adaptation_notes or []

    if tier == "beat_sheet":
        narr = check_narrative_clarity(beats, scene_id=scene_id, adaptation_notes=notes_list)
        for issue in narr.issues:
            report.add_issue(issue)
        if not report.hard_fail:
            report.passed = True
        return report

    prior_text = ""
    seen_speakers: set[str] = set()

    for beat in beats:
        bid = beat.get("beat_id", "?")
        dialogue = _dialogue_blob(beat)
        blob_lower = dialogue.lower()
        action = _beat_action_text(beat).lower()
        combined = f"{prior_text} {action}"

        for pattern, hints, label in _PAYOFF_PATTERNS:
            if not pattern.search(blob_lower):
                continue
            if _has_bridge(combined, hints):
                continue
            loc = f"{scene_id} beat {bid}" if scene_id else f"beat {bid}"
            report.add_issue(
                f"{loc}: {label} — add bridge beat (who/why here) or record adapt:defer with viewer_substitute"
            )

        for speaker in _extract_speakers(dialogue):
            if speaker in seen_speakers:
                continue
            if not _has_bridge(combined, _ESTABLISHMENT_HINTS) and not _speaker_established(speaker, combined, beat):
                loc = f"{scene_id} beat {bid}" if scene_id else f"beat {bid}"
                report.add_issue(
                    f"{loc}: new speaker '{speaker}' in dialogue without prior establishment "
                    f"(lights/shout/enter frame, or adapt:defer)"
                )
            seen_speakers.add(speaker)

        prior_text = f"{prior_text} {blob_lower} {action}"

    narr = check_narrative_clarity(beats, scene_id=scene_id, adaptation_notes=notes_list)
    for issue in narr.issues:
        report.add_issue(issue)

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

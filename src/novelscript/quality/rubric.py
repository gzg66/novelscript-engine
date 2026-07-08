from __future__ import annotations

import re
from typing import Any

from novelscript.checkers.base import CheckerReport

# Production bar — intentionally stricter than dragons-ice sample fixtures.
MIN_SCENE_COUNT_EP01 = 4
MAX_SCENE_COUNT_EP01 = 5
MIN_BEATS_PER_SCENE = 2
MIN_ACTION_CHARS = 10
MIN_PRESENTATION_HINT_CHARS = 12
from novelscript.index.episode_spec import build_episode_spec, resolve_episode_spec

DEFAULT_DURATION_SEC = 150
DEFAULT_TOLERANCE_PCT = 15
DEFAULT_HOOK_SEC = 15
MIN_EP_DURATION_SEC = 128  # 150s - 15%
MAX_EP_DURATION_SEC = 172  # 150s + 15%
VAGUE_HINTS = ("画面", "镜头", "展示", "呈现", "一般", "普通")
ACTIVE_VERBS = (
    "选择", "拒绝", "冲", "推", "抓", "砸", "跑", "转身", "抬头", "攥", "挡", "冲出去",
    "踹", "划", "游", "尖叫", "扯", "撕", "抠",
    "kick", "push", "grab", "run", "turn", "swim", "refuse", "punch", "slash", "strike",
)


def check_script_quality(
    script: dict[str, Any],
    *,
    tier: str = "production",
    episode_spec: dict[str, Any] | None = None,
) -> CheckerReport:
    """Quality gate above structural S5 checker. tier=baseline is looser (fixture/dev)."""
    report = CheckerReport(stage="quality", passed=True)
    if tier == "baseline":
        return report

    scenes = script.get("scenes") or []
    ep_id = script.get("episode_id", "")

    if ep_id.endswith("01") and len(scenes) < MIN_SCENE_COUNT_EP01:
        report.add_issue(f"EP01 needs >={MIN_SCENE_COUNT_EP01} scenes (pilot: one clear story)")
    if ep_id.endswith("01") and len(scenes) > MAX_SCENE_COUNT_EP01:
        report.add_issue(f"EP01 has {len(scenes)} scenes; pilot max {MAX_SCENE_COUNT_EP01} (defer subplots)")

    total_duration = 0
    active_choices = 0
    inner_only_beats = 0

    for scene in scenes:
        total_duration += int(scene.get("duration_target_sec") or 0)
        beats = scene.get("beats") or []
        if len(beats) < MIN_BEATS_PER_SCENE:
            report.add_issue(f"{scene.get('scene_id')}: <{MIN_BEATS_PER_SCENE} beats (too thin)")

        arc = scene.get("emotion_arc") or ""
        if "→" not in arc and "->" not in arc:
            report.add_issue(f"{scene.get('scene_id')}: emotion_arc must show shift (A→B)")

        for beat in beats:
            action = (beat.get("action") or "").strip()
            hint = (beat.get("presentation_hint") or "").strip()
            dialogue = (beat.get("dialogue") or "").strip()
            sound = (beat.get("sound") or "").strip()

            if len(action) < MIN_ACTION_CHARS:
                report.add_issue(f"{scene.get('scene_id')} beat {beat.get('beat_id')}: action too short/vague")
            if not beat.get("source_index"):
                report.add_issue(f"{scene.get('scene_id')} beat {beat.get('beat_id')}: missing beat-level source_index")
            if len(hint) < MIN_PRESENTATION_HINT_CHARS:
                report.add_issue(f"{scene.get('scene_id')} beat {beat.get('beat_id')}: presentation_hint too thin")
            if hint in VAGUE_HINTS or (len(hint) < 20 and hint.endswith("画面")):
                report.add_issue(f"{scene.get('scene_id')} beat {beat.get('beat_id')}: presentation_hint too generic")

            if re.search(r"\(V\.O\.\)|\(inner\)|\(内心\)", dialogue, re.I) and len(action) < MIN_ACTION_CHARS:
                inner_only_beats += 1

            if any(v in action for v in ACTIVE_VERBS):
                active_choices += 1

            if re.search(r"感到\w+|觉得\w+|心里想", action + dialogue):
                report.add_issue(f"{scene.get('scene_id')} beat {beat.get('beat_id')}: psych verb in prose (externalize)")

    if inner_only_beats > 0:
        report.add_issue(f"{inner_only_beats} beat(s) are V.O.-only without strong action")

    from novelscript.checkers.dialogue import check_english_dialogue

    all_beats: list[dict[str, Any]] = []
    for scene in scenes:
        all_beats.extend(scene.get("beats") or [])
    dial = check_english_dialogue(all_beats, stage="quality")
    for issue in dial.issues:
        report.add_issue(issue)

    if active_choices < 2:
        report.add_issue("Protagonist needs >=2 beats with active physical choice (三成立·主角)")

    spec = episode_spec or build_episode_spec()
    min_sec = int(spec.get("min_sec", MIN_EP_DURATION_SEC))
    max_sec = int(spec.get("max_sec", MAX_EP_DURATION_SEC))
    if total_duration < min_sec or total_duration > max_sec:
        target = spec.get("duration_sec", DEFAULT_DURATION_SEC)
        report.add_issue(
            f"Episode duration sum {total_duration}s outside {min_sec}-{max_sec}s (target {target}s)"
        )

    hook_sec = int(spec.get("hook_sec", DEFAULT_HOOK_SEC))
    if scenes:
        last_scene = scenes[-1]
        last_dur = int(last_scene.get("duration_target_sec") or 0)
        if last_dur > 0 and last_dur < hook_sec - 5:
            report.add_issue(
                f"Final scene duration {last_dur}s too short for hook budget ({hook_sec}s)",
                hard=False,
            )

    cliff = script.get("cliffhanger") or ""
    if not cliff or len(cliff) < 8:
        report.add_issue("Missing strong cliffhanger line")

    if scenes:
        last_beats = scenes[-1].get("beats") or []
        if not last_beats:
            report.add_issue("Final scene has no beats for hook landing")

    if not report.hard_fail:
        report.passed = True
    return report

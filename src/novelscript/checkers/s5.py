from __future__ import annotations

import re
from typing import Any

from novelscript.checkers.base import CheckerReport

PSYCH_NARRATION_RE = [
    re.compile(r"她感到\w+"),
    re.compile(r"他感到\w+"),
    re.compile(r"内心独白[:：].{20,}"),
]

KEY_DIALOGUE_WHITELIST = [
    "blondie",
    "There are no bridges",
    "Easy there",
    "Why didn't you tell me you are a mage",
]

_SCENE_FIELD_ALIASES: dict[str, tuple[str, ...]] = {
    "source_index": ("来源索引", "source_index", "source index"),
    "location": ("地点/时间", "地点时间", "location", "地点"),
    "characters": ("出场角色", "characters", "角色"),
    "scene_goal": ("场景目标", "scene_goal", "scene goal"),
    "conflict_resistance": ("冲突/阻力", "冲突阻力", "conflict", "阻力"),
    "emotion_arc": ("情绪弧线", "emotion_arc", "情绪"),
    "value_change": ("场景价值变化", "价值变化", "value_change"),
    "duration_target_sec": ("场次时长目标", "duration_target", "场次时长", "时长"),
}


def _normalize_meta_line(line: str) -> tuple[str, str] | None:
    stripped = line.strip()
    if not stripped.startswith(("-", "*", "•")):
        return None
    body = re.sub(r"^[-*•]\s*", "", stripped)
    if "：" in body:
        key, value = body.split("：", 1)
    elif ":" in body:
        key, value = body.split(":", 1)
    else:
        return None
    key = key.strip().strip("*").lower().replace("_", " ")
    value = value.strip().strip("*")
    return key, value


def _assign_scene_field(scene: dict[str, Any], key: str, value: str) -> None:
    normalized = key.lower().replace("_", " ")
    for field, aliases in _SCENE_FIELD_ALIASES.items():
        if any(alias.lower() in normalized for alias in aliases):
            if field == "characters":
                scene["characters"] = [c.strip() for c in re.split(r"[、,，/]", value) if c.strip()]
            elif field == "duration_target_sec":
                dur = re.search(r"(\d+)", value)
                if dur:
                    scene["duration_target_sec"] = int(dur.group(1))
            elif field == "location":
                parts = [p.strip() for p in re.split(r"[/／]", value) if p.strip()]
                scene["location"] = parts[-1] if parts else value
                if len(parts) > 1 and not scene.get("time"):
                    scene["time"] = parts[0]
            elif field == "source_index":
                refs = re.findall(r"Ch\d+\s*§?\d*[-\d]*", value, re.I) or re.findall(r"§\d+[-\d]*", value)
                scene["source_index"] = refs if refs else [value]
            else:
                scene[field] = value
            return


def _parse_beat_row(cells: list[str]) -> dict[str, Any] | None:
    if len(cells) < 4:
        return None
    beat_match = re.search(r"(\d+)", cells[0])
    if not beat_match:
        return None
    beat_id = beat_match.group(1)
    action = cells[2] if len(cells) > 2 else ""
    dialogue = cells[3] if len(cells) > 3 else ""
    dramatic_function = cells[4] if len(cells) > 4 else ""
    presentation_hint = cells[5] if len(cells) > 5 else ""
    beat: dict[str, Any] = {
        "beat_id": beat_id,
        "source_index": cells[1] if len(cells) > 1 else "",
        "action": action,
        "dialogue": dialogue,
        "dramatic_function": dramatic_function,
        "presentation_hint": presentation_hint,
    }
    if "(雨声" in dialogue or "声音" in dialogue or "背景音" in dialogue:
        beat["sound"] = dialogue.strip("()（）")
        beat["dialogue"] = ""
    return beat


def parse_script_md(md_text: str, *, episode_id: str = "S1E01", global_episode_id: str = "EP001") -> dict[str, Any]:
    scenes: list[dict[str, Any]] = []
    logline = ""
    cliffhanger = ""
    source_chapters: list[int] = []

    for line in md_text.splitlines():
        if line.startswith("**集情**"):
            logline = line.split("：", 1)[-1].strip().strip("*")
        if line.startswith("**集尾钩子**"):
            cliffhanger = line.split("：", 1)[-1].strip().strip("*")

    for line in md_text.splitlines():
        if line.startswith("**集情**"):
            logline = line.split("：", 1)[-1].strip().strip("*")
        if line.startswith("**集尾钩子**"):
            cliffhanger = line.split("：", 1)[-1].strip().strip("*")
        if "hook_landing" in line.lower() or "集尾悬念" in line:
            cliffhanger = cliffhanger or line.split("：", 1)[-1].split(":", 1)[-1].strip().strip("*")

    current_scene: dict[str, Any] | None = None
    in_beat_table = False

    for line in md_text.splitlines():
        scene_match = re.match(r"^##\s+Scene\s+(\d+)", line, re.I)
        if scene_match:
            if current_scene:
                scenes.append(current_scene)
            current_scene = {
                "scene_id": f"Scene {scene_match.group(1)}",
                "source_index": [],
                "location": "",
                "time": "",
                "characters": [],
                "scene_goal": "",
                "conflict_resistance": "",
                "emotion_arc": "",
                "duration_target_sec": 30,
                "beats": [],
            }
            in_beat_table = False
            continue

        if current_scene is None:
            continue

        meta = _normalize_meta_line(line)
        if meta:
            _assign_scene_field(current_scene, meta[0], meta[1])
            in_beat_table = False
            continue

        if re.match(r"^\|\s*Beat\s*\|", line, re.I):
            in_beat_table = True
            continue
        if in_beat_table and line.strip().startswith("|"):
            if re.match(r"^\|[-\s|:]+\|$", line):
                continue
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            beat = _parse_beat_row(cells)
            if beat:
                current_scene["beats"].append(beat)
                for m in re.finditer(r"Ch(\d+)", beat.get("source_index", ""), re.I):
                    source_chapters.append(int(m.group(1)))

    if current_scene:
        scenes.append(current_scene)

    for scene in scenes:
        for m in re.finditer(r"Ch(\d+)", " ".join(scene.get("source_index") or []), re.I):
            source_chapters.append(int(m.group(1)))

    return {
        "episode_id": episode_id,
        "global_episode_id": global_episode_id,
        "season_id": episode_id.split("E")[0] if "E" in episode_id else "S1",
        "logline": logline,
        "source_chapters": sorted(set(source_chapters)) or [1],
        "cliffhanger": cliffhanger,
        "serves_engines": ["逆袭", "身世之谜"],
        "scenes": scenes,
    }


def check_s5_script(
    script: dict[str, Any],
    *,
    episode_chapters: list[int] | None = None,
    must_keep: list[dict[str, Any]] | None = None,
    adaptation_notes: list[dict[str, Any]] | None = None,
) -> CheckerReport:
    report = CheckerReport(stage="S5", passed=True)
    scenes = script.get("scenes") or []
    if not scenes:
        report.add_issue("No scenes in script")
        return report

    ep_chapters = set(episode_chapters or script.get("source_chapters") or [])

    for scene in scenes:
        for field in ("scene_id", "location", "characters", "scene_goal", "conflict_resistance", "emotion_arc"):
            if not scene.get(field):
                report.add_issue(f"{scene.get('scene_id')}: missing {field}")
        if not scene.get("source_index"):
            report.add_issue(f"{scene.get('scene_id')}: missing source_index")
        if not scene.get("value_change") and "→" not in str(scene.get("emotion_arc", "")):
            report.add_warning(f"{scene.get('scene_id')}: missing scene value change")

        scene_beats = scene.get("beats") or []
        from novelscript.checkers.dialogue import check_english_dialogue

        dial = check_english_dialogue(scene_beats, scene_id=str(scene.get("scene_id", "")))
        for issue in dial.issues:
            report.add_issue(issue)

        for beat in scene_beats:
            text_blob = f"{beat.get('action', '')} {beat.get('dialogue', '')} {beat.get('sound', '')}"
            for pattern in PSYCH_NARRATION_RE:
                if pattern.search(text_blob):
                    report.add_issue(f"{scene.get('scene_id')} beat {beat.get('beat_id')}: forbidden psych narration")
            if not beat.get("action"):
                report.add_issue(f"{scene.get('scene_id')} beat {beat.get('beat_id')}: missing action")
            if not beat.get("dramatic_function"):
                report.add_issue(f"{scene.get('scene_id')} beat {beat.get('beat_id')}: missing dramatic_function")
            if not beat.get("presentation_hint"):
                report.add_issue(f"{scene.get('scene_id')} beat {beat.get('beat_id')}: missing presentation_hint")
            if not beat.get("dialogue") and not beat.get("sound"):
                report.add_warning(f"{scene.get('scene_id')} beat {beat.get('beat_id')}: no dialogue or sound")

    full_text = str(script)
    for key in KEY_DIALOGUE_WHITELIST:
        if key.lower() in full_text.lower():
            continue

    if must_keep:
        ep_id = script.get("episode_id")
        for scene in must_keep:
            if scene.get("episode_id") == ep_id and not scene.get("scene_id"):
                report.add_issue(f"must_keep #{scene.get('id')}: missing scene_id on episode {ep_id}")

    all_beats: list[dict[str, Any]] = []
    for scene in scenes:
        all_beats.extend(scene.get("beats") or [])
    from novelscript.checkers.dialogue import check_causal_chain

    causal = check_causal_chain(all_beats, adaptation_notes=adaptation_notes or [])
    for issue in causal.issues:
        report.add_issue(issue)

    if not report.hard_fail:
        report.passed = True
    return report

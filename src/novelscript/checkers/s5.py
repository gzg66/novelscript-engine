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

    current_scene: dict[str, Any] | None = None
    in_beat_table = False

    for line in md_text.splitlines():
        scene_match = re.match(r"^##\s+Scene\s+(\d+)", line)
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

        if line.strip().startswith("- 来源索引"):
            refs = re.findall(r"Ch\d+\s*§?\d*[-\d]*", line) or re.findall(r"§\d+[-\d]*", line)
            current_scene["source_index"] = refs if refs else [line.split("：", 1)[-1].strip()]
            for m in re.finditer(r"Ch(\d+)", line, re.I):
                source_chapters.append(int(m.group(1)))
        elif line.strip().startswith("- 地点/时间"):
            loc_time = line.split("：", 1)[-1].strip()
            parts = [p.strip() for p in loc_time.split("/")]
            current_scene["location"] = parts[-1] if parts else loc_time
            current_scene["time"] = parts[0] if len(parts) > 1 else "夜"
        elif line.strip().startswith("- 出场角色"):
            chars = line.split("：", 1)[-1].strip()
            current_scene["characters"] = [c.strip() for c in re.split(r"[、,，]", chars) if c.strip()]
        elif line.strip().startswith("- 场景目标"):
            current_scene["scene_goal"] = line.split("：", 1)[-1].strip()
        elif line.strip().startswith("- 冲突/阻力"):
            current_scene["conflict_resistance"] = line.split("：", 1)[-1].strip()
        elif line.strip().startswith("- 情绪弧线"):
            current_scene["emotion_arc"] = line.split("：", 1)[-1].strip()
        elif line.strip().startswith("- 场次时长目标"):
            dur = re.search(r"(\d+)", line)
            if dur:
                current_scene["duration_target_sec"] = int(dur.group(1))
        elif line.strip().startswith("| Beat"):
            in_beat_table = True
        elif in_beat_table and line.strip().startswith("|"):
            if re.match(r"^\|[-\s|]+\|$", line):
                continue
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            if len(cells) < 6:
                continue
            try:
                beat_id = str(int(cells[0]))
            except ValueError:
                continue
            beat = {
                "beat_id": beat_id,
                "source_index": cells[1],
                "action": cells[2],
                "dialogue": cells[3] if "(雨声" not in cells[3] else "",
                "dramatic_function": cells[4],
                "presentation_hint": cells[5],
            }
            if "(雨声" in cells[3] or "声音" in cells[3]:
                beat["sound"] = cells[3].strip("()")
                beat["dialogue"] = ""
            current_scene["beats"].append(beat)

    if current_scene:
        scenes.append(current_scene)

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

        for beat in scene.get("beats") or []:
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

    if not report.hard_fail:
        report.passed = True
    return report

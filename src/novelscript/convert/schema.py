from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import jsonschema

from novelscript.checkers.s5 import parse_script_md


def validate_json(data: Any, schema_path: Path) -> list[str]:
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    validator = jsonschema.Draft202012Validator(schema)
    return [f"{'.'.join(str(p) for p in e.path)}: {e.message}" for e in validator.iter_errors(data)]


def script_md_to_json(md_path: Path, *, episode_id: str, global_episode_id: str) -> dict[str, Any]:
    md = md_path.read_text(encoding="utf-8")
    return parse_script_md(md, episode_id=episode_id, global_episode_id=global_episode_id)


def to_museframe_handoff(
    script: dict[str, Any],
    *,
    character_bible_slice: dict[str, Any] | None = None,
    series_premise: dict[str, Any] | None = None,
    visual_tone: str = "",
) -> dict[str, Any]:
    scenes = []
    for scene in script.get("scenes") or []:
        beats = []
        for beat in scene.get("beats") or []:
            beats.append(
                {
                    "beat_id": beat.get("beat_id"),
                    "source_index": beat.get("source_index"),
                    "action": beat.get("action", ""),
                    "dialogue": beat.get("dialogue", ""),
                    "sound": beat.get("sound", ""),
                    "dramatic_function": beat.get("dramatic_function", ""),
                    "visual_hint": beat.get("presentation_hint", ""),
                }
            )
        scenes.append({**scene, "beats": beats})

    return {
        "episode_id": script.get("episode_id"),
        "global_episode_id": script.get("global_episode_id"),
        "script": {
            "logline": script.get("logline", ""),
            "scenes": scenes,
        },
        "character_bible_slice": character_bible_slice or {},
        "series_premise": series_premise or {},
        "visual_tone": visual_tone,
    }

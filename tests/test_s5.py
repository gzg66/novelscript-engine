from __future__ import annotations

from pathlib import Path

from novelscript.checkers.s5 import check_s5_script, parse_script_md
from novelscript.config import PROJECT_ROOT


def test_parse_bullet_meta_script() -> None:
    md = Path(PROJECT_ROOT / "projects/dragon-ice-132/seasons/s1/ep01/script.md").read_text(encoding="utf-8")
    script = parse_script_md(md, episode_id="S1E01", global_episode_id="EP001")
    report = check_s5_script(script)
    beat_count = sum(len(scene.get("beats") or []) for scene in script["scenes"])
    assert beat_count >= 4, beat_count
    assert script["scenes"][0]["location"]
    assert report.passed, report.issues


def test_parse_full_run_script() -> None:
    md = Path(PROJECT_ROOT / "projects/full-run/seasons/s1/ep01/script.md").read_text(encoding="utf-8")
    script = parse_script_md(md, episode_id="S1E01", global_episode_id="EP001")
    report = check_s5_script(script)
    assert report.passed, report.issues

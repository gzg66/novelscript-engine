from __future__ import annotations

from novelscript.checkers.s5 import parse_script_md
from novelscript.config import PROJECT_ROOT
from novelscript.quality.rubric import check_script_quality


def test_sample_ep01_fails_production_bar() -> None:
    """dragons-ice sample is format reference only; production bar must be higher."""
    md = (PROJECT_ROOT / "projects" / "full-run" / "seasons" / "s1" / "ep01" / "script.md").read_text(encoding="utf-8")
    script = parse_script_md(md, episode_id="S1E01", global_episode_id="EP001")
    report = check_script_quality(script, tier="production")
    assert not report.passed, f"sample should not pass production bar: {report.issues[:5]}"


def test_sample_ep01_passes_baseline_tier() -> None:
    md = (PROJECT_ROOT / "projects" / "full-run" / "seasons" / "s1" / "ep01" / "script.md").read_text(encoding="utf-8")
    script = parse_script_md(md, episode_id="S1E01", global_episode_id="EP001")
    report = check_script_quality(script, tier="baseline")
    assert report.passed

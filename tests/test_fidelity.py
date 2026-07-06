from __future__ import annotations

from novelscript.config import PROJECT_ROOT
from novelscript.gates.fidelity import check_fidelity_report, run_fidelity_audit
from novelscript.index.mapping import map_must_keep_to_seasons


def test_map_must_keep_to_seasons() -> None:
    from novelscript.index.must_keep import parse_must_keep_from_story_engine

    engine = (PROJECT_ROOT / "projects" / "full-run" / "S0_story_engine.md").read_text(encoding="utf-8")
    s2 = (PROJECT_ROOT / "projects" / "full-run" / "S2_season_map.md").read_text(encoding="utf-8")
    scenes = parse_must_keep_from_story_engine(engine)
    mapped = map_must_keep_to_seasons(scenes, s2)
    assert all(s.get("season_id") for s in mapped)


def test_fidelity_audit_passes_with_mapped_scenes() -> None:
    report = run_fidelity_audit(
        must_keep=[{"id": 1, "season_id": "S1", "episode_id": "S1E01", "scene_id": "Scene 1"}],
        story_engines=["逆袭"],
        episodes=[
            {"episode_id": "S1E01", "serves_engines": ["逆袭"]},
            {"episode_id": "S1E02", "serves_engines": ["逆袭"]},
            {"episode_id": "S1E03", "serves_engines": ["逆袭"]},
        ],
        scripts={},
    )
    assert report["verdict"] == "pass"
    assert check_fidelity_report(report).passed

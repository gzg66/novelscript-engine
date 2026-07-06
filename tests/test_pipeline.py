from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from novelscript.config import PROJECT_ROOT, load_settings
from novelscript.convert.schema import script_md_to_json, validate_json
from novelscript.pipeline.context import init_project, load_project
from novelscript.pipeline.orchestrator import Pipeline

SAMPLE = PROJECT_ROOT / "projects" / "full-run"


@pytest.fixture
def project_dir(tmp_path: Path) -> Path:
    novel = PROJECT_ROOT / "input" / "novel.txt"
    root = tmp_path / "dragons-ice-run"
    init_project(root, novel_src=novel)
    stage0_src = SAMPLE / "input" / "stage0"
    if stage0_src.is_dir():
        shutil.copytree(stage0_src, root / "input" / "stage0", dirs_exist_ok=True)
    for name in (
        "S0_adaptation_brief.md",
        "S0_story_engine.md",
        "S1_series_premise.md",
        "S1_character_bible.md",
        "S2_season_map.md",
    ):
        shutil.copy2(SAMPLE / name, root / name)
    s1 = root / "seasons" / "s1"
    s1.mkdir(parents=True)
    shutil.copy2(SAMPLE / "seasons" / "s1" / "episode_list.md", s1 / "episode_list.md")
    (root / "approved").mkdir(exist_ok=True)
    (root / "approved" / "S2.approved").write_text("", encoding="utf-8")
    for ep in (1, 2, 3):
        ep_dir = s1 / f"ep{ep:02d}"
        ep_dir.mkdir(parents=True)
        src_ep = SAMPLE / "seasons" / "s1" / f"ep{ep:02d}"
        shutil.copy2(src_ep / "beat_sheet.md", ep_dir / "beat_sheet.md")
        shutil.copy2(src_ep / "script.md", ep_dir / "script.md")
        script = script_md_to_json(
            src_ep / "script.md",
            episode_id=f"S1E{ep:02d}",
            global_episode_id=f"EP{ep:03d}",
        )
        (ep_dir / "script.json").write_text(json.dumps(script, ensure_ascii=False, indent=2), encoding="utf-8")
    return root


def test_fixture_validates_against_schema() -> None:
    settings = load_settings()
    fixture = json.loads((settings.schemas_dir / "fixtures" / "ep01.script.json").read_text(encoding="utf-8"))
    errors = validate_json(fixture, settings.schemas_dir / "script.schema.v1.json")
    assert errors == [], errors


def test_pipeline_index_and_check(project_dir: Path) -> None:
    ctx = load_project(project_dir)
    pipe = Pipeline(ctx)
    idx = pipe._run_index()
    assert idx["total_chapters"] == 132
    report = pipe.check("S2")
    assert report.passed, report.issues
    report_s3 = pipe.check("S3")
    assert report_s3.passed, report_s3.issues


def test_pipeline_fidelity_audit(project_dir: Path) -> None:
    ctx = load_project(project_dir)
    pipe = Pipeline(ctx)
    pipe._run_index()
    report = pipe.run_fidelity_audit("S1")
    assert "verdict" in report
    assert "must_keep_coverage" in report


def test_full_verify(project_dir: Path) -> None:
    ctx = load_project(project_dir)
    pipe = Pipeline(ctx)
    summary = pipe.verify(export_pilot=True)
    assert summary["fidelity"]["verdict"] == "pass"
    assert len(summary["exports"]) == 3


def test_export_museframe(project_dir: Path) -> None:
    ctx = load_project(project_dir)
    pipe = Pipeline(ctx)
    out = pipe.export_museframe("S1E01")
    assert out.exists()
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["episode_id"] == "S1E01"
    assert data["script"]["scenes"]

from __future__ import annotations

import shutil
from pathlib import Path

from novelscript.config import PROJECT_ROOT
from novelscript.pipeline.context import ensure_project, load_project
from novelscript.web.manifest import _collect_stage_docs, build_manifest, detect_pending_gate, pipeline_status

SAMPLE = PROJECT_ROOT / "projects" / "full-run"


def test_detect_pending_gate_s2(tmp_path: Path) -> None:
    novel = PROJECT_ROOT / "input" / "novel.txt"
    project = tmp_path / "gate-s2"
    ensure_project(novel, project_root=project)
    shutil.copy2(SAMPLE / "S2_season_map.md", project / "S2_season_map.md")

    gate = detect_pending_gate(project)
    assert gate is not None
    assert gate["gate"] == "S2"
    assert gate["resumeFrom"] == "S3"
    assert gate["docFile"] == "S2_season_map.md"


def test_detect_pending_gate_s2_even_when_auto_approved(tmp_path: Path) -> None:
    novel = PROJECT_ROOT / "input" / "novel.txt"
    project = tmp_path / "gate-stalled"
    ensure_project(novel, project_root=project)
    shutil.copy2(SAMPLE / "S2_season_map.md", project / "S2_season_map.md")
    (project / "approved").mkdir(exist_ok=True)
    (project / "approved" / "S2.approved").write_text("", encoding="utf-8")

    gate = detect_pending_gate(project)
    assert gate is not None
    assert gate["gate"] == "S2"
    assert gate["resumeOnly"] is True
    assert gate["approved"] is True


def test_detect_pending_gate_cleared_after_s3_started(tmp_path: Path) -> None:
    novel = PROJECT_ROOT / "input" / "novel.txt"
    project = tmp_path / "gate-approved"
    ensure_project(novel, project_root=project)
    shutil.copy2(SAMPLE / "S2_season_map.md", project / "S2_season_map.md")
    s1_dir = project / "seasons" / "s1"
    s1_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(SAMPLE / "seasons" / "s1" / "episode_list.md", s1_dir / "episode_list.md")

    gate = detect_pending_gate(project)
    assert gate is not None
    assert gate["gate"] == "s1_pilot"
    assert gate["stageId"] == "S3"


def test_pipeline_status_exposes_pending_gate(tmp_path: Path) -> None:
    novel = PROJECT_ROOT / "input" / "novel.txt"
    project = tmp_path / "status-gate"
    ensure_project(novel, project_root=project)
    shutil.copy2(SAMPLE / "S2_season_map.md", project / "S2_season_map.md")

    status = pipeline_status(project)
    assert status["pendingGate"] is not None
    assert status["pendingGate"]["gate"] == "S2"
    assert status["message"] == status["pendingGate"]["message"]
    assert "decisionQueue" in status


def test_pipeline_status_decision_queue(tmp_path: Path) -> None:
    from novelscript.audit.decision_log import save_decision_queue

    novel = PROJECT_ROOT / "input" / "novel.txt"
    project = tmp_path / "status-dq"
    ensure_project(novel, project_root=project)
    save_decision_queue(
        project / "audit",
        [{"id": "dq_x", "question": "test?", "status": "pending", "options": ["A"]}],
    )
    status = pipeline_status(project)
    assert len(status["decisionQueue"]) == 1
    assert status["decisionQueue"][0]["id"] == "dq_x"


def test_s3_collects_season_episode_lists(tmp_path: Path) -> None:
    project = tmp_path / "s3-seasons"
    project.mkdir()
    s1 = project / "seasons" / "s1"
    s1.mkdir(parents=True)
    (s1 / "episode_list.md").write_text("# EP list\n", encoding="utf-8")

    docs = _collect_stage_docs(project, "S3", [])
    assert len(docs) == 1
    assert docs[0]["file"] == "seasons/s1/episode_list.md"
    assert docs[0]["title"] == "分集清单 S1"

    manifest = build_manifest(project)
    s3 = next(s for s in manifest["stages"] if s["id"] == "S3")
    assert s3["status"] == "partial"
    assert len(s3["docs"]) == 1


def test_build_manifest_includes_all_pipeline_stages(tmp_path: Path) -> None:
    project = tmp_path / "all-stages"
    project.mkdir()
    manifest = build_manifest(project)
    stage_ids = [s["id"] for s in manifest["stages"]]
    assert stage_ids == ["P0", "stage0", "P1", "S0", "brief", "P3", "S1", "S2", "S3", "S4", "S5", "P6"]

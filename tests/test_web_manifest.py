from __future__ import annotations

import shutil
from pathlib import Path

from novelscript.config import PROJECT_ROOT
from novelscript.pipeline.context import ensure_project, load_project
from novelscript.web.manifest import _collect_stage_docs, build_manifest, detect_pending_gate, pipeline_status

SAMPLE = PROJECT_ROOT / "projects" / "full-run"

EPISODE_LIST_MD = """
| 集 | 一句话集情 | 覆盖 | 核心冲突 | 主角的选择 | 本集变化 | 时长目标 | 集尾钩子 |
|---|---|---|---|---|---|---|---|
| **EP01** | 开篇 | Ch1–Ch2 | 冲突 | 选择 | 处境彻底翻转不可逆 | 150s | 新威胁入画 |
| **EP02** | 续 | Ch3–Ch4 | 冲突 | 选择 | 信任链断裂不可逆 | 150s | 手攥紧特写 |
| **EP03** | 续 | Ch5–Ch6 | 冲突 | 选择 | 秘密曝光不可逆 | 150s | 门被推开 |
| **EP04** | 续 | Ch7–Ch8 | 冲突 | 选择 | 联盟重组不可逆 | 150s | 火光映脸 |
| **EP05** | 续 | Ch9–Ch10 | 冲突 | 选择 | 代价落地不可逆 | 150s | 沉默对视 |
"""


def _write_s1_episode_list(project: Path) -> None:
    s1_dir = project / "seasons" / "s1"
    s1_dir.mkdir(parents=True, exist_ok=True)
    (s1_dir / "episode_list.md").write_text(EPISODE_LIST_MD, encoding="utf-8")


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
    _write_s1_episode_list(project)

    gate = detect_pending_gate(project)
    assert gate is not None
    assert gate["gate"] == "s1_pilot"
    assert gate["stageId"] == "S4"
    assert gate["resumeOnly"] is True
    assert "试播集" in gate["message"]


def test_detect_pending_gate_s1_pilot_review(tmp_path: Path) -> None:
    novel = PROJECT_ROOT / "input" / "novel.txt"
    project = tmp_path / "gate-pilot-review"
    ensure_project(novel, project_root=project)
    _write_s1_episode_list(project)
    s1_dir = project / "seasons" / "s1"
    for ep in (1, 2, 3):
        ep_dir = s1_dir / f"ep{ep:02d}"
        ep_dir.mkdir(parents=True, exist_ok=True)
        (ep_dir / "script.json").write_text("{}", encoding="utf-8")

    gate = detect_pending_gate(project)
    assert gate is not None
    assert gate["gate"] == "s1_pilot"
    assert gate["resumeOnly"] is False
    assert gate["approved"] is False
    assert gate["docFile"] == "seasons/s1/ep01/script.json"
    assert "审阅" in gate["message"]


def test_detect_pending_gate_s1_remaining_resume(tmp_path: Path) -> None:
    novel = PROJECT_ROOT / "input" / "novel.txt"
    project = tmp_path / "gate-remaining"
    ensure_project(novel, project_root=project)
    _write_s1_episode_list(project)
    s1_dir = project / "seasons" / "s1"
    (project / "approved").mkdir(exist_ok=True)
    (project / "approved" / "s1_pilot.approved").write_text("", encoding="utf-8")
    for ep in (1, 2, 3):
        ep_dir = s1_dir / f"ep{ep:02d}"
        ep_dir.mkdir(parents=True, exist_ok=True)
        (ep_dir / "script.json").write_text("{}", encoding="utf-8")

    gate = detect_pending_gate(project)
    assert gate is not None
    assert gate["gate"] == "s1_pilot"
    assert gate["resumeOnly"] is True
    assert gate["approved"] is True
    assert "剩余集" in gate["message"]


def test_detect_pending_gate_pilot_test_complete_no_gate(tmp_path: Path) -> None:
    import json

    novel = PROJECT_ROOT / "input" / "novel.txt"
    project = tmp_path / "gate-pilot-test"
    ensure_project(novel, project_root=project)
    _write_s1_episode_list(project)
    meta_path = project / "project.meta.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    meta["pilot_test"] = True
    meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    s1_dir = project / "seasons" / "s1"
    for ep in (1, 2, 3):
        ep_dir = s1_dir / f"ep{ep:02d}"
        ep_dir.mkdir(parents=True, exist_ok=True)
        (ep_dir / "script.json").write_text("{}", encoding="utf-8")

    assert detect_pending_gate(project) is None


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

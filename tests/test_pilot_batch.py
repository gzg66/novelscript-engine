from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from novelscript.config import PROJECT_ROOT
from novelscript.pipeline.context import ensure_project, load_project
from novelscript.pipeline.orchestrator import Pipeline

EPISODE_LIST_MD = """
| 集 | 一句话集情 | 覆盖 | 核心冲突 | 主角的选择 | 本集变化 | 时长目标 | 集尾钩子 |
|---|---|---|---|---|---|---|---|
| **EP01** | 开篇 | Ch1–Ch2 | 冲突 | 选择 | 处境彻底翻转不可逆 | 150s | 新威胁入画 |
| **EP02** | 续 | Ch3–Ch4 | 冲突 | 选择 | 信任链断裂不可逆 | 150s | 手攥紧特写 |
| **EP03** | 续 | Ch5–Ch6 | 冲突 | 选择 | 秘密曝光不可逆 | 150s | 门被推开 |
| **EP04** | 续 | Ch7–Ch8 | 冲突 | 选择 | 联盟重组不可逆 | 150s | 火光映脸 |
| **EP05** | 续 | Ch9–Ch10 | 冲突 | 选择 | 代价落地不可逆 | 150s | 沉默对视 |
"""


@pytest.fixture
def s1_project(tmp_path: Path) -> Path:
    novel = PROJECT_ROOT / "input" / "novel.txt"
    project = tmp_path / "pilot-batch"
    ensure_project(novel, project_root=project)
    s1_dir = project / "seasons" / "s1"
    s1_dir.mkdir(parents=True, exist_ok=True)
    (s1_dir / "episode_list.md").write_text(EPISODE_LIST_MD, encoding="utf-8")
    (project / "approved").mkdir(exist_ok=True)
    (project / "approved" / "S2.approved").write_text("", encoding="utf-8")
    return project


def test_episodes_for_s4_s5_pilot_before_approval(s1_project: Path) -> None:
    pipe = Pipeline(load_project(s1_project))
    assert pipe._episodes_for_s4_s5() == ["S1E01", "S1E02", "S1E03"]


def test_episodes_for_s4_s5_remaining_after_approval(s1_project: Path) -> None:
    (s1_project / "approved" / "s1_pilot.approved").write_text("", encoding="utf-8")
    pipe = Pipeline(load_project(s1_project))
    remaining = pipe._remaining_episodes("S1")
    assert remaining == ["S1E04", "S1E05"]
    assert pipe._episodes_for_s4_s5() == remaining


def test_pilot_batch_blocks_without_auto_approve(s1_project: Path) -> None:
    pipe = Pipeline(load_project(s1_project))
    with patch.object(pipe, "_run_s4_s5_episodes"), patch.object(pipe, "_post_pilot_s4_s5"):
        result = pipe.run(through="S5", from_stage="S4", skip_llm=False, auto_approve=False)
    assert "blocked" in result
    assert "EP01" in result["blocked"]


def test_pilot_scripts_do_not_repeat_after_approval(s1_project: Path) -> None:
    s1_dir = s1_project / "seasons" / "s1"
    for ep in (1, 2, 3):
        ep_dir = s1_dir / f"ep{ep:02d}"
        ep_dir.mkdir(parents=True, exist_ok=True)
        (ep_dir / "script.json").write_text(json.dumps({"episode_id": f"S1E{ep:02d}"}), encoding="utf-8")
    (s1_project / "approved" / "s1_pilot.approved").write_text("", encoding="utf-8")

    pipe = Pipeline(load_project(s1_project))
    selected = pipe._episodes_for_s4_s5()
    assert "S1E01" not in selected
    assert "S1E02" not in selected
    assert "S1E03" not in selected
    assert selected == ["S1E04", "S1E05"]


def test_stop_after_pilot_does_not_approve_or_continue(s1_project: Path) -> None:
    pipe = Pipeline(load_project(s1_project))
    with patch.object(pipe, "_run_s4_s5_episodes"), patch.object(pipe, "_post_pilot_s4_s5"):
        result = pipe.run(
            through="S5",
            from_stage="S4",
            skip_llm=False,
            auto_approve=True,
            stop_after_pilot=True,
        )
    assert "blocked" not in result
    assert not (s1_project / "approved" / "s1_pilot.approved").exists()


def test_pilot_test_skips_episodes_when_scripts_complete(s1_project: Path) -> None:
    meta_path = s1_project / "project.meta.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    meta["pilot_test"] = True
    meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    s1_dir = s1_project / "seasons" / "s1"
    for ep in (1, 2, 3):
        ep_dir = s1_dir / f"ep{ep:02d}"
        ep_dir.mkdir(parents=True, exist_ok=True)
        (ep_dir / "script.json").write_text(json.dumps({"episode_id": f"S1E{ep:02d}"}), encoding="utf-8")

    pipe = Pipeline(load_project(s1_project))
    assert pipe._episodes_for_s4_s5() == []

from __future__ import annotations

from pathlib import Path

import pytest

from novelscript.pipeline.cancel import (
    PipelineCancelled,
    acquire_run_lock,
    check_cancelled,
    clear_cancel,
    is_cancelled,
    is_pipeline_active,
    release_run_lock,
    request_cancel,
)


def test_cancel_lifecycle(tmp_path: Path) -> None:
    root = tmp_path / "demo"
    root.mkdir()

    assert not is_cancelled(root)
    check_cancelled(root)

    request_cancel(root)
    assert is_cancelled(root)
    with pytest.raises(PipelineCancelled):
        check_cancelled(root)

    clear_cancel(root)
    assert not is_cancelled(root)
    check_cancelled(root)


def test_cancel_is_per_project(tmp_path: Path) -> None:
    a = tmp_path / "a"
    b = tmp_path / "b"
    a.mkdir()
    b.mkdir()

    request_cancel(a)
    assert is_cancelled(a)
    assert not is_cancelled(b)


def test_pipeline_lock_tracks_active_process(tmp_path: Path) -> None:
    root = tmp_path / "locked"
    root.mkdir()

    assert not is_pipeline_active(root)
    acquire_run_lock(root, slug="demo")
    assert is_pipeline_active(root)
    release_run_lock(root)
    assert not is_pipeline_active(root)


def test_cancel_flag_survives_without_thread_event(tmp_path: Path) -> None:
    root = tmp_path / "flagged"
    root.mkdir()
    flag = root / ".runs" / "cancel.flag"
    flag.parent.mkdir(parents=True, exist_ok=True)
    flag.write_text("1", encoding="utf-8")

    assert is_cancelled(root)
    with pytest.raises(PipelineCancelled):
        check_cancelled(root)

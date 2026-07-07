from __future__ import annotations

import json
import os
import threading
import time
from collections.abc import Callable
from pathlib import Path

_cancel_events: dict[str, threading.Event] = {}
_lock = threading.Lock()

_FLAG_NAME = "cancel.flag"
_LOCK_NAME = "pipeline.lock"


class PipelineCancelled(Exception):
    """Raised when the user requests pipeline cancellation."""


def _key(project_root: Path) -> str:
    return str(project_root.resolve())


def _flag_path(project_root: Path) -> Path:
    return project_root / ".runs" / _FLAG_NAME


def _lock_path(project_root: Path) -> Path:
    return project_root / ".runs" / _LOCK_NAME


def acquire_run_lock(project_root: Path, *, slug: str = "") -> None:
    path = _lock_path(project_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"slug": slug, "pid": os.getpid(), "started": time.time()}, ensure_ascii=False),
        encoding="utf-8",
    )


def release_run_lock(project_root: Path) -> None:
    _lock_path(project_root).unlink(missing_ok=True)


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if os.name == "nt":
        import ctypes

        kernel32 = ctypes.windll.kernel32
        handle = kernel32.OpenProcess(0x1000, False, pid)
        if handle:
            kernel32.CloseHandle(handle)
            return True
        return False
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def is_pipeline_active(project_root: Path) -> bool:
    path = _lock_path(project_root)
    if not path.exists():
        return False
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        pid = int(data.get("pid", 0))
        if _pid_alive(pid):
            return True
        path.unlink(missing_ok=True)
        return False
    except (ValueError, json.JSONDecodeError):
        path.unlink(missing_ok=True)
        return False


def mark_stopped(project_root: Path) -> None:
    path = project_root / ".runs" / "stopped.at"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(str(time.time()), encoding="utf-8")


def clear_cancel(project_root: Path) -> None:
    _flag_path(project_root).unlink(missing_ok=True)
    (project_root / ".runs" / "stopped.at").unlink(missing_ok=True)
    with _lock:
        event = _cancel_events.get(_key(project_root))
        if event is not None:
            event.clear()


def request_cancel(project_root: Path) -> bool:
    flag = _flag_path(project_root)
    flag.parent.mkdir(parents=True, exist_ok=True)
    flag.write_text(str(time.time()), encoding="utf-8")
    with _lock:
        key = _key(project_root)
        event = _cancel_events.get(key)
        if event is None:
            event = threading.Event()
            _cancel_events[key] = event
        event.set()
        return True


def is_cancelled(project_root: Path) -> bool:
    if _flag_path(project_root).exists():
        return True
    with _lock:
        event = _cancel_events.get(_key(project_root))
        return event is not None and event.is_set()


def check_cancelled(project_root: Path) -> None:
    if is_cancelled(project_root):
        raise PipelineCancelled("用户已中断精编")


def cancel_check(project_root: Path) -> Callable[[], None]:
    def _check() -> None:
        check_cancelled(project_root)

    return _check

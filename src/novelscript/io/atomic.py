from __future__ import annotations

import json
import os
import shutil
from pathlib import Path
from typing import Any


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def write_json(path: Path, data: Any, *, indent: int = 2) -> None:
    atomic_write(path, json.dumps(data, ensure_ascii=False, indent=indent) + "\n")


def atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    partial = path.with_suffix(path.suffix + ".partial")
    partial.write_text(content, encoding="utf-8")
    if path.exists():
        path.unlink()
    os.replace(partial, path)


def atomic_copy(src: Path, dst: Path) -> None:
    atomic_write(dst, src.read_text(encoding="utf-8"))


def ensure_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path

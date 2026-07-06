from __future__ import annotations

import logging
import sys
from pathlib import Path

_STDERR_CONFIGURED = False
_FILE_HANDLER: logging.FileHandler | None = None
_FILE_PATH: Path | None = None


def setup_logging(*, project_root: Path | None = None, verbose: bool = False) -> logging.Logger:
    global _STDERR_CONFIGURED, _FILE_HANDLER, _FILE_PATH
    level = logging.DEBUG if verbose else logging.INFO
    root = logging.getLogger("novelscript")
    root.setLevel(level)

    fmt = logging.Formatter("%(asctime)s %(levelname)s [%(name)s] %(message)s", datefmt="%H:%M:%S")
    if not _STDERR_CONFIGURED:
        stderr = logging.StreamHandler(sys.stderr)
        stderr.setFormatter(fmt)
        root.addHandler(stderr)
        _STDERR_CONFIGURED = True

    if project_root is not None:
        log_path = project_root / "pipeline.log"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        if _FILE_HANDLER is not None and _FILE_PATH != log_path:
            root.removeHandler(_FILE_HANDLER)
            _FILE_HANDLER.close()
            _FILE_HANDLER = None
        if _FILE_HANDLER is None:
            _FILE_HANDLER = logging.FileHandler(log_path, encoding="utf-8")
            _FILE_HANDLER.setFormatter(
                logging.Formatter("%(asctime)s %(levelname)s [%(name)s] %(message)s")
            )
            root.addHandler(_FILE_HANDLER)
            _FILE_PATH = log_path
        root.info("日志文件：%s", log_path)

    return root


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(f"novelscript.{name}")

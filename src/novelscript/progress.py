from __future__ import annotations

import sys


def emit(message: str) -> None:
    """Immediate progress line on stderr (also captured in pipeline.log via logging elsewhere)."""
    sys.stderr.write(message + "\n")
    sys.stderr.flush()

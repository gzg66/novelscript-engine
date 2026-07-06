from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class CheckerReport:
    stage: str
    passed: bool
    hard_fail: bool = False
    issues: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def add_issue(self, msg: str, *, hard: bool = True) -> None:
        self.issues.append(msg)
        if hard:
            self.hard_fail = True
            self.passed = False

    def add_warning(self, msg: str) -> None:
        self.warnings.append(msg)


def passes_gate(report: CheckerReport) -> bool:
    return report.passed and not report.hard_fail

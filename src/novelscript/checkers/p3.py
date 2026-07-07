from __future__ import annotations

from novelscript.checkers.base import CheckerReport

REQUIRED_SECTIONS = ("允许改动", "禁止改动", "主要风险")
ENGINE_MARKERS = ("主引擎", "辅引擎")


def check_adaptation_strategy(md_text: str) -> CheckerReport:
    report = CheckerReport(stage="P3", passed=True)
    for section in REQUIRED_SECTIONS:
        if section not in md_text:
            report.add_issue(f"Missing section: {section}")
    if not any(marker in md_text for marker in ENGINE_MARKERS):
        report.add_warning("Missing engine declaration (主引擎/辅引擎)")
    if "创作策略" not in md_text and "adaptation_strategy" not in md_text.lower():
        report.add_warning("Missing strategy title")
    if not report.hard_fail:
        report.passed = True
    return report

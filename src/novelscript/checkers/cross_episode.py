from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from novelscript.checkers.base import CheckerReport
from novelscript.checkers.info_ledger import check_cross_episode_info_chain, parse_info_ledger_md
from novelscript.checkers.s3 import check_episode_progression_chain, parse_episode_list_md


def load_season_episode_ledgers(season_dir: Path, *, season_id: str = "S1") -> list[tuple[str, list[dict[str, Any]]]]:
    ledgers: list[tuple[str, list[dict[str, Any]]]] = []
    if not season_dir.exists():
        return ledgers
    for ep_dir in sorted(season_dir.iterdir()):
        if not ep_dir.is_dir() or not ep_dir.name.startswith("ep"):
            continue
        beat_path = ep_dir / "beat_sheet.md"
        if not beat_path.exists():
            continue
        ep_num = int(ep_dir.name.replace("ep", ""))
        ep_id = f"{season_id}E{ep_num:02d}"
        rows = parse_info_ledger_md(beat_path.read_text(encoding="utf-8"))
        if rows:
            ledgers.append((ep_id, rows))
    return ledgers


def check_chapter_coverage_gap(
    episodes: list[dict[str, Any]],
) -> CheckerReport:
    """Detect skipped chapter ranges between adjacent episodes without handoff."""
    report = CheckerReport(stage="chapter_gap", passed=True)
    if len(episodes) < 2:
        return report

    sorted_eps = sorted(episodes, key=lambda e: e.get("episode_id", ""))
    for prev_ep, next_ep in zip(sorted_eps, sorted_eps[1:]):
        prev_chs = set(prev_ep.get("source_chapters") or [])
        next_chs = set(next_ep.get("source_chapters") or [])
        if not prev_chs or not next_chs:
            continue
        prev_max = max(prev_chs)
        next_min = min(next_chs)
        if next_min > prev_max + 1:
            gap = list(range(prev_max + 1, next_min))
            prev_id = prev_ep.get("episode_id", "?")
            next_id = next_ep.get("episode_id", "?")
            next_logline = str(next_ep.get("logline") or "")
            next_conflict = str(next_ep.get("core_conflict") or "")
            gap_text = ",".join(f"Ch{c}" for c in gap)
            combined = f"{next_logline} {next_conflict}".lower()
            needs_handoff = any(
                kw in combined
                for kw in ("戴斯蒙德", "desmond", "大赛", "tournament", "丝带", "ribbon", "金冠", "crown")
            )
            if needs_handoff:
                report.add_issue(
                    f"{prev_id}→{next_id}: chapter gap {gap_text} but {next_id} assumes "
                    f"skipped content ({next_logline[:40]})"
                )

    if not report.hard_fail:
        report.passed = True
    return report


def run_season_cross_checks(
    season_dir: Path,
    *,
    season_id: str = "S1",
) -> CheckerReport:
    """Load episode_list + ledgers and run cross-episode continuity checks."""
    report = CheckerReport(stage="cross_episode", passed=True)
    ep_list_path = season_dir / "episode_list.md"
    if not ep_list_path.exists():
        report.add_issue("cross_episode: missing episode_list.md")
        return report

    episodes = parse_episode_list_md(ep_list_path.read_text(encoding="utf-8"), season_id=season_id)
    ledgers = load_season_episode_ledgers(season_dir, season_id=season_id)

    for sub in (
        check_episode_progression_chain(episodes),
        check_chapter_coverage_gap(episodes),
    ):
        for issue in sub.issues:
            if sub.hard_fail:
                report.add_issue(issue)
            else:
                report.add_warning(issue)

    if ledgers:
        info_report = check_cross_episode_info_chain(ledgers)
        for issue in info_report.issues:
            report.add_issue(issue)

    if not report.hard_fail:
        report.passed = True
    return report

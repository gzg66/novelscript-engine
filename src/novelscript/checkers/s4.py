from __future__ import annotations

import re
from typing import Any

from novelscript.checkers.base import CheckerReport
from novelscript.index.episode_spec import build_episode_spec, duration_in_spec

_BEAT_HEADER_MARKERS = (
    "beat",
    "节拍",
    "来源索引",
    "画面动作",
    "外化",
    "戏剧功能",
)
_SKIP_HEADER_CELLS = {"beat", "节拍", "#", "beat id", "beat_id"}


def _parse_beat_id(cell: str) -> int | None:
    text = cell.strip().strip("*").lower()
    if text in _SKIP_HEADER_CELLS:
        return None
    match = re.search(r"(\d+)", cell)
    return int(match.group(1)) if match else None


def _column_index(headers: list[str], *needles: str) -> int | None:
    lowered = [h.lower() for h in headers]
    for needle in needles:
        for idx, header in enumerate(lowered):
            if needle in header:
                return idx
    return None


def _parse_table_rows(lines: list[str], start: int) -> tuple[list[dict[str, Any]], int]:
    beats: list[dict[str, Any]] = []
    headers: list[str] = []
    idx = start
    while idx < len(lines):
        line = lines[idx].strip()
        if not line.startswith("|"):
            break
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if re.match(r"^\|[-\s|:]+\|$", line):
            idx += 1
            continue
        if not headers:
            header_text = " ".join(cells).lower()
            if not any(marker in header_text for marker in _BEAT_HEADER_MARKERS):
                idx += 1
                continue
            headers = cells
            idx += 1
            continue

        beat_id = _parse_beat_id(cells[0])
        if beat_id is None:
            idx += 1
            continue

        ext_idx = _column_index(headers, "外化", "画面动作", "画面")
        dial_idx = _column_index(headers, "对白", "声音", "dialogue")
        src_idx = _column_index(headers, "来源", "source", "索引")
        func_idx = _column_index(headers, "戏剧功能", "功能")
        dur_idx = _column_index(headers, "时长", "duration")
        hook_idx = _column_index(headers, "钩子", "hook")
        info_idx = _column_index(headers, "信息差", "info_gap", "信息")
        externalization = cells[ext_idx] if ext_idx is not None and ext_idx < len(cells) else ""
        dialogue = cells[dial_idx] if dial_idx is not None and dial_idx < len(cells) else ""
        source_index = cells[src_idx] if src_idx is not None and src_idx < len(cells) else ""
        dramatic_function = cells[func_idx] if func_idx is not None and func_idx < len(cells) else ""
        info_gap = cells[info_idx] if info_idx is not None and info_idx < len(cells) else ""
        if not externalization and len(cells) > 2:
            externalization = cells[2]
        if not dramatic_function and len(cells) > 4:
            dramatic_function = cells[4]
        hook_anchor = cells[hook_idx] if hook_idx is not None and hook_idx < len(cells) else None
        duration_sec = None
        if dur_idx is not None and dur_idx < len(cells):
            dur_match = re.search(r"(\d+)", cells[dur_idx])
            if dur_match:
                duration_sec = int(dur_match.group(1))
        if hook_anchor is None and dramatic_function and "钩" in dramatic_function:
            hook_anchor = dramatic_function

        beats.append(
            {
                "beat_id": beat_id,
                "dramatic_function": dramatic_function,
                "info_gap": info_gap,
                "externalization": externalization,
                "action": externalization,
                "dialogue": dialogue,
                "source_index": source_index,
                "hook_anchor": hook_anchor,
                "duration_sec": duration_sec,
            }
        )
        idx += 1
    return beats, idx


def _episode_section_lines(md_text: str, episode_id: str) -> list[str]:
    ep_num = episode_id.split("E")[-1]
    ep_tag = f"EP{ep_num}"
    ep_tag_int = f"EP{int(ep_num)}"
    lines = md_text.splitlines()
    start = 0
    end = len(lines)
    for i, line in enumerate(lines):
        if (
            re.search(rf"##\s+{re.escape(ep_tag)}\b", line, re.I)
            or re.search(rf"##\s+{re.escape(ep_tag_int)}\b", line, re.I)
            or re.search(rf"##\s+.*\b{re.escape(episode_id)}\b", line, re.I)
        ):
            start = i
            break
    for i in range(start + 1, len(lines)):
        if re.match(r"##\s+EP\d+", lines[i], re.I) and i > start:
            end = i
            break
    if start == 0 and end == len(lines):
        return lines
    return lines[start:end]


def parse_beat_sheet_md(md_text: str, *, episode_id: str = "S1E01") -> dict[str, Any]:
    section = _episode_section_lines(md_text, episode_id)
    episode_goal = ""
    emotion_curve = ""
    hook_landing = ""
    duration_budget_sec = None

    for line in section:
        stripped = line.strip()
        if stripped.startswith("**集情**") or stripped.startswith("**episode_goal**"):
            episode_goal = stripped.split("：", 1)[-1].split(":", 1)[-1].strip().strip("*")
        if "本集目标" in stripped or "episode_goal" in stripped.lower():
            episode_goal = episode_goal or stripped.split("：", 1)[-1].split(":", 1)[-1].strip().strip("*")
        if "情绪弧线" in stripped or "情绪曲线" in stripped:
            emotion_curve = stripped.split("：", 1)[-1].split(":", 1)[-1].strip()
        if "钩子落点" in stripped or "集尾钩子" in stripped or "hook_landing" in stripped.lower():
            hook_landing = stripped.split("：", 1)[-1].split(":", 1)[-1].strip().strip("*")
        if "时长预算" in stripped or "duration_budget" in stripped.lower():
            dur_match = re.search(r"(\d+)", stripped)
            if dur_match:
                duration_budget_sec = int(dur_match.group(1))

    beats: list[dict[str, Any]] = []
    idx = 0
    while idx < len(section):
        if section[idx].strip().startswith("|"):
            table_beats, idx = _parse_table_rows(section, idx)
            beats.extend(table_beats)
            continue
        idx += 1

    # De-dupe by beat_id while preserving order
    seen: set[int] = set()
    unique_beats: list[dict[str, Any]] = []
    for beat in beats:
        bid = beat["beat_id"]
        if bid in seen:
            continue
        seen.add(bid)
        unique_beats.append(beat)

    return {
        "episode_id": episode_id,
        "episode_goal": episode_goal,
        "emotion_curve": emotion_curve,
        "hook_landing": hook_landing,
        "duration_budget_sec": duration_budget_sec,
        "beats": unique_beats,
    }


def check_s4_beat_sheet(
    data: dict[str, Any],
    *,
    episode_spec: dict[str, Any] | None = None,
    adaptation_notes: list[dict[str, Any]] | None = None,
    info_ledger: list[dict[str, Any]] | None = None,
    source_chapters: list[int] | None = None,
) -> CheckerReport:
    report = CheckerReport(stage="S4", passed=True)
    beats = data.get("beats") or []
    n = len(beats)
    if n < 4 or n > 8:
        report.add_issue(f"Beat count {n} not in range 4-8")
    from novelscript.checkers.dialogue import check_causal_chain, check_english_dialogue

    dial = check_english_dialogue(beats)
    for issue in dial.issues:
        report.add_issue(issue)
    causal = check_causal_chain(
        beats, adaptation_notes=adaptation_notes, tier="beat_sheet"
    )
    for issue in causal.issues:
        report.add_issue(issue)

    if source_chapters and len(source_chapters) >= 2 and n <= 4:
        report.add_warning(
            f"Beat count {n} with {len(source_chapters)} source chapters — "
            "information density high; prefer merging chapters over compressing beats"
        )

    for beat in beats:
        if not beat.get("externalization"):
            report.add_issue(f"Beat {beat.get('beat_id')}: missing externalization")
        if not beat.get("dramatic_function"):
            report.add_issue(f"Beat {beat.get('beat_id')}: missing dramatic_function")
        if not beat.get("info_gap"):
            report.add_warning(f"Beat {beat.get('beat_id')}: missing info_gap")

    spec = episode_spec or build_episode_spec()
    beat_durations = [int(b["duration_sec"]) for b in beats if b.get("duration_sec")]
    if beat_durations:
        total = sum(beat_durations)
        budget = data.get("duration_budget_sec") or spec["duration_sec"]
        if total != int(budget):
            report.add_issue(f"Beat durations sum {total}s != budget {budget}s")
        if not duration_in_spec(total, spec):
            report.add_issue(f"Beat durations sum {total}s outside {spec['min_sec']}-{spec['max_sec']}s")
    else:
        report.add_warning("Beat sheet missing per-beat duration column")

    budget = data.get("duration_budget_sec")
    if budget is not None and not duration_in_spec(int(budget), spec):
        report.add_issue(f"duration_budget_sec {budget}s outside spec range")

    if adaptation_notes is not None:
        from novelscript.checkers.adaptation import check_adaptation_notes

        if not adaptation_notes:
            report.add_warning(
                "adaptation_notes: missing ## 改编决策记录 table "
                "(add 5-column table at end of beat_sheet.md)"
            )
        else:
            adapt_report = check_adaptation_notes(adaptation_notes)
            for issue in adapt_report.issues:
                if adapt_report.hard_fail:
                    report.add_issue(issue)
                else:
                    report.add_warning(issue)

    if info_ledger is not None:
        from novelscript.checkers.info_ledger import check_info_ledger

        if not info_ledger:
            report.add_warning(
                "info_ledger: missing ## 本集信息账本 section "
                "(add 3-6 rows before ## 改编决策记录)"
            )
        else:
            beat_ids = {str(b.get("beat_id")) for b in beats}
            ledger_report = check_info_ledger(info_ledger, beat_ids=beat_ids)
            for issue in ledger_report.issues:
                if ledger_report.hard_fail:
                    report.add_issue(issue)
                else:
                    report.add_warning(issue)

    if not report.hard_fail:
        report.passed = True
    return report

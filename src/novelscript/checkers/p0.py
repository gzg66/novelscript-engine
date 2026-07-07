from __future__ import annotations

import re

from novelscript.checkers.base import CheckerReport

REQUIRED_SECTIONS = ("改写档位", "忠实对象", "目标形态", "口味旋钮", "禁区")
TASTE_KNOBS = ("节奏", "主角主动性", "感情线", "世界观", "内容边界")
MODE_MARKERS = ("M1", "M2", "精编", "深度改编", "多本改写", "多本重构", "保主线", "保体验")
FIDELITY_MARKERS = ("忠实", "主线", "名场面", "体验", "原著", "角色", "CP", "识别")
FORBIDDEN_ACTION = re.compile(r"不可|不得|不能|禁止|必须保留|须保留|保留|不可改|不可删|不可拆")
VAGUE_FORBIDDEN = re.compile(
    r"^(?:要|尽量|力求|追求|打造|呈现|保证|确保)?.*(?:优质|精彩|好看|爆款|精品|高质量|口碑|出圈|大火)$"
)
CONFLICT_PAIRS: list[tuple[str, str]] = [
    (r"少解释|不多解释|零设定|外化|No Info-dump", r"详细解释|设定倾倒|长篇旁白|世界观解说|完整设定"),
    (r"高忠实|严守|保主线|名场面必保|忠实于", r"大幅重构|自由删改|可删名场面|随意改编"),
    (r"慢节奏|细水长流|铺垫为主", r"强钩子|高密度爽点|每集.*反转|快节奏"),
]


def check_project_preference(md_text: str) -> CheckerReport:
    report = CheckerReport(stage="P0", passed=True)
    for section in REQUIRED_SECTIONS:
        if section not in md_text:
            report.add_issue(f"Missing section: {section}")

    _gate_mode_clear(report, md_text)
    _gate_fidelity_object_clear(report, md_text)
    _gate_taste_knobs(report, md_text)
    _gate_forbidden_executable(report, md_text)

    if not report.hard_fail:
        report.passed = True
    return report


def _gate_mode_clear(report: CheckerReport, md_text: str) -> None:
    """Gate 1: 模式是否说得清？"""
    body = _section_body(md_text, "改写档位")
    if not body.strip():
        report.add_issue("Gate1 模式：改写档位为空")
        return
    if not any(marker in body for marker in MODE_MARKERS):
        report.add_issue("Gate1 模式：改写档位须明确 M1/M2/精编/深度改编/保主线/保体验 等档位")
    if len(body.strip()) < 12:
        report.add_issue("Gate1 模式：改写档位描述过短，须说明改编任务性质")


def _gate_fidelity_object_clear(report: CheckerReport, md_text: str) -> None:
    """Gate 2: 忠实对象是否明确？"""
    body = _section_body(md_text, "忠实对象")
    if not body.strip():
        report.add_issue("Gate2 忠实对象：须单独说明忠实于什么（主线/名场面/体验/角色识别等）")
        return
    if not any(marker in body for marker in FIDELITY_MARKERS):
        report.add_issue("Gate2 忠实对象：须点明忠实对象，如主线、名场面、体验、角色识别、CP")
    bullets = _list_items(body)
    if not bullets:
        report.add_issue("Gate2 忠实对象：须用列表写出至少 1 条可执行的忠实对象")


def _gate_taste_knobs(report: CheckerReport, md_text: str) -> None:
    """Gate 3: 口味旋钮是否完整且互不冲突？"""
    body = _section_body(md_text, "口味旋钮")
    if not body.strip():
        report.add_issue("Gate3 口味旋钮：口味旋钮节为空")
        return
    for knob in TASTE_KNOBS:
        if knob not in body:
            report.add_warning(f"Missing taste knob: {knob}")
    for left, right in CONFLICT_PAIRS:
        if re.search(left, body, re.IGNORECASE) and re.search(right, body, re.IGNORECASE):
            report.add_issue(f"Gate3 口味旋钮冲突：同时出现「{left}」与「{right}」倾向")
    knob_lines = [ln for ln in body.splitlines() if ln.strip().startswith(("-", "*"))]
    if len(knob_lines) < 3:
        report.add_issue("Gate3 口味旋钮：至少 3 条带具体取向的旋钮（不可只写「优先」「加强」等空词）")
    for line in knob_lines:
        detail = re.sub(r"^[-*]\s*\*\*[^*]+\*\*[：:]\s*", "", line.strip())
        if len(detail) < 8:
            report.add_issue(f"Gate3 口味旋钮过泛：{line.strip()}")


def _gate_forbidden_executable(report: CheckerReport, md_text: str) -> None:
    """Gate 4: 禁区是否可执行，而不是空泛口号？"""
    forbidden = _list_items(_section_body(md_text, "禁区"))
    if not forbidden:
        report.add_issue("Gate4 禁区：列表为空 — 须写出可执行禁区，不可空喊口号")
        return
    for item in forbidden:
        if len(item) < 8:
            report.add_issue(f"Gate4 禁区过短不可执行：{item}")
        if not FORBIDDEN_ACTION.search(item):
            report.add_issue(f"Gate4 禁区缺少可执行约束（不可/不得/禁止/保留等）：{item}")
        if VAGUE_FORBIDDEN.match(item.strip()):
            report.add_issue(f"Gate4 禁区是空泛口号：{item}")


def _list_items(section_body: str) -> list[str]:
    items: list[str] = []
    for line in section_body.splitlines():
        m = re.match(r"[-*]\s+(.+)", line.strip())
        if m:
            items.append(m.group(1).strip())
    return items


def _section_body(md_text: str, heading: str) -> str:
    lines = md_text.splitlines()
    capture = False
    buf: list[str] = []
    for line in lines:
        if line.strip().startswith("## ") and heading in line:
            capture = True
            continue
        if capture and line.strip().startswith("## "):
            break
        if capture:
            buf.append(line)
    return "\n".join(buf)

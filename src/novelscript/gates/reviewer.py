from __future__ import annotations

import json
import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from novelscript.config import AppSettings
from novelscript.llm.client import LLMClient

PILOT_REVIEW_SYSTEM = """你是竖屏奇幻短剧审片人。评判标准必须高于 dragons-ice 手工样板（样板仅及格线）。

试播集强制「三成立」：
1. 主角成立：≥2场戏有主动选择或外化情绪；连续2场纯说明/旁白=fail
2. 世界成立：3集内观众能懂穿越事实、魔法=阶级、主角处境、短期目标
3. 想看下一集：集尾hook与下集目标形成因果悬念

可读性审（假设观众未读小说）：
- 随机抽 3 个含对白的 beat，追问「观众为何不觉得突兀？」
- 若发现「砍因果、留台词」（有回报台词无铺垫）→ fail

输出 ONLY JSON：
{
  "verdict": "pass|revise",
  "issues": ["必须引用 scene_id/beat_id 的具体问题"],
  "three_established": {"protagonist": true, "world": true, "hook": true},
  "beats_sample_quality": "below|meets|exceeds"
}
beats_sample_quality 低于 exceeds 时 verdict 应为 revise。"""

CHINESE_REVIEW_SYSTEM = """你是网文改编短剧的质量审校员。检查草稿是否忠实于输入材料、格式是否符合阶段要求。

输出 ONLY JSON：
{
  "verdict": "pass|revise",
  "issues": ["具体问题，引用 card_id/章节/角色名"],
  "three_established": {},
  "beats_sample_quality": "meets"
}
若存在事实漂移、遗漏 mk_* 裁决、季数不一致或格式硬伤，verdict 必须为 revise。"""

_CHINESE_REVIEW_STAGES = frozenset(
    {"s0_engine", "s2_season_map", "p1_source_cards", "p3_strategy", "s4_beats"}
)

S3_REVIEW_SYSTEM = """你是竖屏短剧分集策划审校员。检查分集清单是否为「可拍单元」而非「章节切片」。

强制「三闭环」：
1. 冲突闭环：每集有明确核心冲突，不是设定说明集
2. 变化闭环：每集有不可逆的状态/关系/信息变化
3. 钩子闭环：集尾钩子视觉化，给观众明确「看下集」理由
4. 推进链闭环：EPn 集尾钩子是否给 EPn+1 一句话集情提供明确观看动机

额外检查：
- 是否「一章一集」流水线切分（坏）
- 是否只推设定不推人（水集）
- 时长目标是否在规格容差内

输出 ONLY JSON：
{
  "verdict": "pass|revise",
  "issues": ["引用 EPxx 的具体问题"],
  "three_established": {"conflict": true, "change": true, "hook": true},
  "beats_sample_quality": "meets"
}
任一闭环不成立或明显水集时 verdict 必须为 revise。"""


@dataclass
class ReviewResult:
    verdict: str
    issues: list[str]
    three_established: dict[str, bool]
    beats_sample_quality: str = "meets"

    @property
    def needs_revise(self) -> bool:
        return self.verdict != "pass" or self.beats_sample_quality == "below"


def llm_review(
    *,
    settings: AppSettings,
    stage: str,
    draft: str,
    context: str = "",
    pilot: bool = False,
    cancel_check: Callable[[], None] | None = None,
) -> ReviewResult:
    if pilot:
        system = PILOT_REVIEW_SYSTEM
    elif stage.startswith("s3_"):
        system = S3_REVIEW_SYSTEM
    elif stage in _CHINESE_REVIEW_STAGES:
        system = CHINESE_REVIEW_SYSTEM
    else:
        system = (
            "You are a script reviewer. Return ONLY JSON: "
            '{"verdict":"pass|revise","issues":[],"three_established":{},"beats_sample_quality":"exceeds"}'
        )
    user = f"Stage: {stage}\n\nContext:\n{context[:16000]}\n\nDraft:\n{draft[:50000]}"
    client = LLMClient(settings, llm_config=settings.conversion_llm)
    raw = client.generate_text(system=system, user=user, stream=False, cancel_check=cancel_check)
    return _parse_review(raw)


def _parse_review(raw: str) -> ReviewResult:
    match = re.search(r"\{[\s\S]*\}", raw)
    if not match:
        return ReviewResult(verdict="revise", issues=["review JSON parse failed"], three_established={})
    try:
        data = json.loads(match.group(0))
    except json.JSONDecodeError:
        return ReviewResult(verdict="revise", issues=["review JSON decode failed"], three_established={})
    return ReviewResult(
        verdict=str(data.get("verdict", "pass")),
        issues=[str(i) for i in data.get("issues") or []],
        three_established=dict(data.get("three_established") or {}),
        beats_sample_quality=str(data.get("beats_sample_quality", "meets")),
    )

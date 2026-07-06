from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

from novelscript.config import AppSettings
from novelscript.llm.client import LLMClient

PILOT_REVIEW_SYSTEM = """你是竖屏奇幻短剧审片人。评判标准必须高于 dragons-ice 手工样板（样板仅及格线）。

试播集强制「三成立」：
1. 主角成立：≥2场戏有主动选择或外化情绪；连续2场纯说明/旁白=fail
2. 世界成立：3集内观众能懂穿越事实、魔法=阶级、主角处境、短期目标
3. 想看下一集：集尾hook与下集目标形成因果悬念

输出 ONLY JSON：
{
  "verdict": "pass|revise",
  "issues": ["必须引用 scene_id/beat_id 的具体问题"],
  "three_established": {"protagonist": true, "world": true, "hook": true},
  "beats_sample_quality": "below|meets|exceeds"
}
beats_sample_quality 低于 exceeds 时 verdict 应为 revise。"""


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
) -> ReviewResult:
    system = PILOT_REVIEW_SYSTEM if pilot else (
        "You are a script reviewer. Return ONLY JSON: "
        '{"verdict":"pass|revise","issues":[],"three_established":{},"beats_sample_quality":"exceeds"}'
    )
    user = f"Stage: {stage}\n\nContext:\n{context[:4000]}\n\nDraft:\n{draft[:12000]}"
    client = LLMClient(settings, llm_config=settings.conversion_llm)
    raw = client.generate_text(system=system, user=user, stream=False)
    return _parse_review(raw)


def _parse_review(raw: str) -> ReviewResult:
    match = re.search(r"\{[\s\S]*\}", raw)
    if not match:
        return ReviewResult(verdict="pass", issues=[], three_established={})
    try:
        data = json.loads(match.group(0))
    except json.JSONDecodeError:
        return ReviewResult(verdict="pass", issues=[], three_established={})
    return ReviewResult(
        verdict=str(data.get("verdict", "pass")),
        issues=[str(i) for i in data.get("issues") or []],
        three_established=dict(data.get("three_established") or {}),
        beats_sample_quality=str(data.get("beats_sample_quality", "meets")),
    )

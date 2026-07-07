from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from novelscript.audit.decision_log import append_decision, save_decision_queue
from novelscript.checkers.base import CheckerReport
from novelscript.checkers.p0 import check_project_preference
from novelscript.checkers.p1 import cards_to_json, check_source_cards, parse_source_cards_md
from novelscript.checkers.p3 import check_adaptation_strategy
from novelscript.config import AppSettings
from novelscript.io.atomic import write_json
from novelscript.pipeline.context import ProjectContext
from novelscript.index.must_keep import build_must_keep_index
from novelscript.stages.source import SourceContextError, format_p1_source_block, load_source_context


def _default_preference(ctx: ProjectContext) -> str:
    title = ctx.root.name.replace("-", " ").title()
    return f"""# 项目偏好 · {title}

## 改写档位
精编生产（M1）· 忠实于单本主线与名场面功能

## 忠实对象
- 单本主线情节顺序与关键转折功能
- 主角核心识别点与关键 CP 关系张力
- 开篇三章已呈现的名场面情绪功能

## 目标形态
竖屏短剧 / AI 漫剧短集

## 口味旋钮
- **节奏**：前 3 集强钩子闭环，单集 5–7 场戏，每集结尾不可逆视觉悬念
- **主角主动性**：每集至少 2 个主动选择或外化行动的 Beat
- **感情线**：加强拉扯，台词去油，保留关键英文对白张力
- **世界观**：少解释，用事件与视觉外化魔法阶级与处境
- **内容边界**：不做低俗擦边，反派须有智商与压迫感

## 禁区
- 女主核心识别点不可改
- 关键 CP 不可拆
- 核心名场面情绪功能不可删
"""


def run_p0_preference(ctx: ProjectContext, settings: AppSettings, *, skip_llm: bool = False) -> dict[str, Any]:
    from novelscript.stages import _load_prompt, _run_stage_loop

    out = ctx.root / "project_preference.md"

    def checker(text: str) -> CheckerReport:
        return check_project_preference(text)

    if skip_llm and not out.exists():
        out.write_text(_default_preference(ctx), encoding="utf-8")
        return {"status": "seeded", "path": str(out)}

    meta = ctx.meta.get("genre", "竖屏短剧")
    novel_path = ctx.novel_path()
    if not novel_path.exists():
        raise SourceContextError(f"P0 需要小说原文，请确认 {novel_path} 存在")
    novel_text = novel_path.read_text(encoding="utf-8")
    if not novel_text.strip():
        raise SourceContextError(f"P0 需要小说原文，{novel_path} 为空")
    novel_block = f"## 小说原文\n\n{novel_text}"
    user = (
        f"改编模式：M1 精编生产\n"
        f"权利依据：{ctx.rights_basis}\n"
        f"题材：{meta}\n\n"
        f"{novel_block}\n\n"
        "根据上述小说原文，输出 project_preference.md。\n"
        "口味旋钮须贴合本书主角、冲突与名场面，不得写成与原文无关的泛化口号。\n"
        "锁定模式、忠实对象、口味旋钮与可执行禁区。"
    )
    return _run_stage_loop(
        ctx,
        settings,
        stage="p0_preference",
        out_path=out,
        checker=checker,
        system_prompt=_load_prompt("p0_preference/v1.md"),
        user_prompt=user,
        skip_llm=skip_llm,
    )


def run_p1_source_cards(ctx: ProjectContext, settings: AppSettings, *, skip_llm: bool = False) -> dict[str, Any]:
    from novelscript.stages import _load_prompt, _run_stage_loop

    cards_dir = ctx.root / "source_cards"
    cards_dir.mkdir(parents=True, exist_ok=True)
    out = cards_dir / "index.md"

    def checker(text: str) -> CheckerReport:
        return check_source_cards(text)

    src = load_source_context(ctx)
    user = (
        f"{format_p1_source_block(ctx, src)}\n\n"
        "根据上述大纲、角色库与全书正文抽样，输出 source_cards/index.md。"
        "事件卡须覆盖全书主要情节节点，每条标注 Ch 来源与戏剧功能。"
    )
    result = _run_stage_loop(
        ctx,
        settings,
        stage="p1_source_cards",
        out_path=out,
        checker=checker,
        system_prompt=_load_prompt("p1_source_cards/v1.md"),
        user_prompt=user,
        skip_llm=skip_llm,
        allow_best_effort=skip_llm,
    )
    if out.exists():
        cards = parse_source_cards_md(out.read_text(encoding="utf-8"))
        write_json(cards_dir / "index.json", cards_to_json(cards))
        from novelscript.pipeline.stage_deps import persist_stage_hashes

        persist_stage_hashes(ctx, "P1")
    return result


def run_p3_strategy(ctx: ProjectContext, settings: AppSettings, *, skip_llm: bool = False) -> dict[str, Any]:
    from novelscript.stages import _load_prompt, _run_stage_loop
    from novelscript.stages.source import load_source_cards_index

    out = ctx.root / "adaptation_strategy.md"

    def checker(text: str) -> CheckerReport:
        return check_adaptation_strategy(text)

    pref = (ctx.root / "project_preference.md").read_text(encoding="utf-8") if (ctx.root / "project_preference.md").exists() else ""
    engine = (ctx.root / "S0_story_engine.md").read_text(encoding="utf-8") if (ctx.root / "S0_story_engine.md").exists() else ""
    brief = (ctx.root / "S0_adaptation_brief.md").read_text(encoding="utf-8") if (ctx.root / "S0_adaptation_brief.md").exists() else ""
    cards_json = load_source_cards_index(ctx)
    cards_md_path = ctx.root / "source_cards" / "index.md"
    cards_block = json.dumps(cards_json, ensure_ascii=False, indent=2) if cards_json else (
        cards_md_path.read_text(encoding="utf-8") if cards_md_path.exists() else ""
    )
    user = (
        f"项目偏好：\n{pref}\n\n"
        f"改编简报：\n{brief}\n\n"
        f"故事引擎：\n{engine}\n\n"
        f"素材卡（完整 index.json）：\n{cards_block}\n\n"
        "输出 M1 精编生产的 adaptation_strategy.md，含可选「策略修订」节。"
    )
    result = _run_stage_loop(
        ctx,
        settings,
        stage="p3_strategy",
        out_path=out,
        checker=checker,
        system_prompt=_load_prompt("p3_strategy/v1.md"),
        user_prompt=user,
        skip_llm=skip_llm,
        allow_best_effort=skip_llm,
    )
    if out.exists() and result.get("status") in ("ok", "cached"):
        engine_path = ctx.root / "S0_story_engine.md"
        if engine_path.exists():
            from novelscript.index.must_keep import (
                load_must_keep,
                parse_strategy_must_keep_revisions,
            )

            scenes = build_must_keep_index(engine_path, ctx.index_dir, strategy_path=out)
            revisions = parse_strategy_must_keep_revisions(out.read_text(encoding="utf-8"))
            for card_id, action in revisions.items():
                append_decision(
                    ctx.audit_dir,
                    {
                        "stage": "P3",
                        "source_ref": card_id,
                        "adaptation_action": action,
                        "dramatic_reason": "策略修订回写 must_keep 索引",
                        "risk": "降级/升保影响季图谱落点",
                        "impact": "must_keep_scenes.json",
                        "rollback_to": "P3",
                    },
                )
            result["must_keep_count"] = len(scenes or load_must_keep(ctx.index_dir / "must_keep_scenes.json"))
        append_decision(
            ctx.audit_dir,
            {
                "stage": "P3",
                "source_ref": "S0_story_engine",
                "adaptation_action": "策略锁定",
                "dramatic_reason": "M1 精编删改规则落盘",
                "risk": "策略与偏好冲突时需回 P0",
                "impact": "S2–S5 全局",
                "rollback_to": "P3",
            },
        )
        from novelscript.pipeline.stage_deps import persist_stage_hashes

        persist_stage_hashes(ctx, "P3")
    return result


def build_decision_queue_from_s2(ctx: ProjectContext) -> list[dict[str, Any]]:
    s2_path = ctx.root / "S2_season_map.md"
    if not s2_path.exists():
        return []
    text = s2_path.read_text(encoding="utf-8")
    items: list[dict[str, Any]] = []
    if "S1|S2" in text or "Ch30" in text:
        items.append(
            {
                "id": "dq_s1_boundary",
                "question": "S1 季断点是否落在 Ch30（求活→立足完成）？",
                "recommendation": "保持 Ch30 断点，与手工样板一致",
                "options": ["A 保持 Ch30", "B 前移断点", "C 后移断点"],
                "evidence": {"structural": "S2 季图谱", "textual": "Ch30 分院/立威"},
                "impact": {"seasons": ["S1", "S2"], "episodes": []},
                "status": "pending",
            }
        )
    if "献丝带" in text or "丝带" in text:
        items.append(
            {
                "id": "dq_ribbon_placement",
                "question": "献丝带名场面是否保留在 S1 并承担双男主张力点火？",
                "recommendation": "保留功能，集次可在 S3 微调",
                "options": ["A 严格保留 Ch7-9 映射", "B 允许前置伏笔", "C 仅保留功能不重排"],
                "evidence": {"dramatic": "双男主拉扯 + 主角主动性"},
                "impact": {"lines": ["爱情线", "逆袭线"]},
                "status": "pending",
            }
        )
    return items[:10]


def run_p6_pilot_review(ctx: ProjectContext, settings: AppSettings, *, skip_llm: bool = False) -> dict[str, Any]:
    from novelscript.gates.reviewer import llm_review

    out = ctx.audit_dir / "review_cards_S1_pilot.md"
    revision = ctx.audit_dir / "revision_log.md"
    scripts: list[str] = []
    for ep in (1, 2, 3):
        p = ctx.episode_dir("S1", ep) / "script.md"
        if p.exists():
            scripts.append(p.read_text(encoding="utf-8"))
    if not scripts:
        return {"status": "skipped", "reason": "no pilot scripts"}

    combined = "\n\n---\n\n".join(scripts)
    dims = [
        "开头抓人",
        "主角主动性",
        "世界能看懂",
        "集尾想看",
        "爽点密度",
        "关系张力",
        "反派压力",
        "世界观负担",
    ]
    rollback = "P5"
    review_text = ""
    if not skip_llm:
        from novelscript.stages.source import build_review_context, format_must_keep_block, load_must_keep_scenes

        pilot_ctx = format_must_keep_block(load_must_keep_scenes(ctx), season_id="S1")
        review = llm_review(
            settings=settings,
            stage="p6_pilot",
            draft=combined,
            context=pilot_ctx,
            pilot=True,
        )
        review_text = "\n".join(f"- {i}" for i in review.issues)
        if review.verdict != "pass":
            rollback = "P4" if any("hook" in i.lower() or "季" in i for i in review.issues) else "P5"

    lines = [
        "# 试播集观感卡 · S1 EP01–03",
        "",
        "| 维度 | 评级 | 备注 |",
        "|---|---|---|",
    ]
    for dim in dims:
        lines.append(f"| {dim} | 待人工 | 绿/黄/红 |")
    lines.extend(["", "## LLM 审片备注", review_text or "- （无）", "", f"## 建议返工层\n`{rollback}`"])
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines), encoding="utf-8")
    with revision.open("a", encoding="utf-8") as fh:
        fh.write(f"\n## Pilot review\n- rollback_layer: {rollback}\n")
    return {"status": "ok", "path": str(out), "rollback_layer": rollback}

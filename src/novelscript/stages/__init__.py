from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from novelscript.checkers.base import CheckerReport, passes_gate
from novelscript.config import AppSettings
from novelscript.io.atomic import atomic_write
from novelscript.llm.client import LLMClient
from novelscript.logging import get_logger
from novelscript.pipeline.cancel import cancel_check, check_cancelled
from novelscript.pipeline.context import ProjectContext
from novelscript.progress import emit
from novelscript.index.episode_spec import format_episode_spec_block, resolve_episode_spec
from novelscript.index.season_plan import (
    check_cross_stage_season_consistency,
    resolve_season_count,
)
from novelscript.stages.source import (
    build_review_context,
    format_adaptation_input_bundle,
    format_chapter_source_block,
    format_chapter_toc,
    format_must_keep_block,
    format_source_block,
    load_chapter_range_excerpt,
    load_episode_chapter_texts,
    load_must_keep_scenes,
    load_source_context,
)

log = get_logger("stages")

STAGE_FORMAT_HINTS: dict[str, str] = {
    "p0_preference": (
        "格式提醒：须有「忠实对象」节；口味旋钮每条 ≥8 字且贴合原著；"
        "禁区须含不可/不得/禁止/保留；不可写空泛口号或与旋钮冲突的取向。"
    ),
    "s0_engine": (
        "格式提醒：标题须含「四台核心发动机」「素材裁决表」；"
        "发动机编号用「引擎 1」…「引擎 4」；"
        "裁决表必须覆盖所有 mk_* 卡，列名 card_id|裁决|理由|服务引擎。"
    ),
    "s1_premise": (
        "格式提醒：须有「一句话」标题；"
        "主角逐季蜕变表行数必须等于改编简报季数，季 ID 为 | **S1** | … | **Sn** |。"
    ),
    "s1_bible": (
        "格式提醒：每位主角须含 **想要**、**不愿承认**、**会改变** 三字段；"
        "须有配角合并章节。"
    ),
    "s2_season_map": (
        "格式提醒：季总表 8 列，季 ID 必须是 S1–Sn（禁止 Season 1）；"
        "章节列如 1–30；按故事断点切季，各季断点理由须引用具体剧情节点；"
        "最后一季须覆盖全书最后一章，无缺口。"
        "须含「时间线鱼骨图」「多线推进表」「名场面落点」三节标题。"
    ),
    "s3_episodes": (
        "格式提醒：全文中文；表头八列「集|一句话集情|覆盖|核心冲突|主角的选择|本集变化|时长目标|集尾钩子」；"
        "集号 **EP01** 格式；覆盖列是素材索引 Ch1 或 Ch5–7；禁止默认一章一集；时长如 150s。"
    ),
    "s4_beats": (
        "格式提醒：元数据中文；对白/声音列全部英文（Freya (V.O.): / SFX:）；"
        "beat 须含外化处理与时长列；duration_budget_sec 默认 150s；"
        "文末须有 ## 改编决策记录（至少一条 adapt:*）；新角色/道具无铺垫则 adapt:defer。"
    ),
    "s5_script": (
        "格式提醒：元数据中文；对白/声音列全部英文；场次时长之和须在单集规格容差内（目标150s）；"
        "最后一场 hook ≥ hook_sec；EP01 不写家族/戒指线；必保锚点保真。"
    ),
}


def _format_hint(stage: str) -> str | None:
    if stage in STAGE_FORMAT_HINTS:
        return STAGE_FORMAT_HINTS[stage]
    if stage.startswith("s3_"):
        return STAGE_FORMAT_HINTS.get("s3_episodes")
    if stage.startswith("s4_"):
        return STAGE_FORMAT_HINTS.get("s4_beats")
    if stage.startswith("s5_"):
        return STAGE_FORMAT_HINTS.get("s5_script")
    return None


def _run_stage_loop(
    ctx: ProjectContext,
    settings: AppSettings,
    *,
    stage: str,
    out_path: Path,
    checker: Any,
    system_prompt: str,
    user_prompt: str,
    temperature: float = 0.5,
    skip_llm: bool = False,
    allow_best_effort: bool = True,
) -> dict[str, Any]:
    from novelscript.pipeline.stage_deps import persist_stage_hashes, stage_inputs_valid

    stage_key = stage
    if stage.startswith("s3_"):
        stage_key = "S3"
    elif stage.startswith("s4_"):
        stage_key = "S4"
    elif stage.startswith("s5_"):
        stage_key = "S5"
    elif stage in ("p0_preference",):
        stage_key = "P0"
    elif stage in ("p1_source_cards",):
        stage_key = "P1"
    elif stage in ("p3_strategy",):
        stage_key = "P3"
    elif stage in ("s0_engine",):
        stage_key = "S0"
    elif stage in ("s1_premise", "s1_bible"):
        stage_key = "S1"
    elif stage in ("s2_season_map",):
        stage_key = "S2"

    if out_path.exists() and out_path.stat().st_size > 0 and stage_inputs_valid(ctx, stage_key):
        report = checker(out_path.read_text(encoding="utf-8"))
        if passes_gate(report):
            emit(f"  ✓ {stage}：缓存命中（{out_path.name}）")
            log.info("%s: cache hit %s", stage, out_path.name)
            return {"status": "cached", "path": str(out_path)}

    if skip_llm:
        log.info("%s: skipped (skip_llm)", stage)
        return {"status": "skipped", "path": str(out_path)}

    llm_cfg = settings.llm
    if temperature != llm_cfg.temperature:
        from dataclasses import replace

        llm_cfg = replace(llm_cfg, temperature=temperature)
    client = LLMClient(settings, llm_config=llm_cfg)
    on_cancel = cancel_check(ctx.root)

    run_dir = ctx.runs_dir / stage
    run_dir.mkdir(parents=True, exist_ok=True)
    partial = out_path.with_suffix(out_path.suffix + ".partial")

    last_report: CheckerReport | None = None
    for attempt in range(1, settings.pipeline.max_attempts + 1):
        check_cancelled(ctx.root)
        feedback = ""
        if last_report and last_report.issues:
            feedback = "\n\nFix these issues:\n" + "\n".join(f"- {i}" for i in last_report.issues)
            hint = _format_hint(stage)
            if hint:
                feedback += f"\n\n{hint}"

        log.info("%s: LLM attempt %s/%s -> %s", stage, attempt, settings.pipeline.max_attempts, out_path.name)
        emit(f"  → {stage}：LLM 第 {attempt}/{settings.pipeline.max_attempts} 次尝试（{out_path.name}）")
        client.generate_text(
            system=system_prompt,
            user=user_prompt + feedback,
            write_path=partial,
            stream=True,
            cancel_check=on_cancel,
        )
        text = partial.read_text(encoding="utf-8")
        atomic_write(out_path, text)
        last_report = checker(text)
        if passes_gate(last_report) and stage.startswith("s5_"):
            from novelscript.checkers.s5 import parse_script_md
            from novelscript.quality.rubric import check_script_quality

            ep_id = stage.replace("s5_", "", 1)
            ep_num = int(ep_id.split("E")[-1])
            script = parse_script_md(text, episode_id=ep_id, global_episode_id=f"EP{ep_num:03d}")
            spec = resolve_episode_spec(ctx)
            q = check_script_quality(script, tier="production", episode_spec=spec)
            if not passes_gate(q):
                last_report = q
        audit = {"attempt": attempt, "passed": passes_gate(last_report), "issues": last_report.issues}
        (run_dir / f"attempt_{attempt}.json").write_text(json.dumps(audit, ensure_ascii=False, indent=2), encoding="utf-8")
        if passes_gate(last_report):
            emit(f"  ✓ {stage}：校验通过（第 {attempt} 次）")
            log.info("%s: checker passed on attempt %s", stage, attempt)
            from novelscript.gates.reviewer import llm_review

            review = llm_review(
                settings=settings,
                stage=stage,
                draft=text,
                context=build_review_context(ctx, stage, user_prompt),
                pilot=stage.startswith("s5_S1E0") and stage[-1] in "123",
                cancel_check=on_cancel,
            )
            (run_dir / f"review_{attempt}.json").write_text(
                json.dumps(
                    {
                        "verdict": review.verdict,
                        "issues": review.issues,
                        "three_established": review.three_established,
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )
            if review.needs_revise and attempt < settings.pipeline.max_attempts:
                last_report = CheckerReport(stage=stage, passed=False, hard_fail=False)
                for issue in review.issues:
                    last_report.add_issue(f"review: {issue}", hard=False)
                continue
            persist_stage_hashes(ctx, stage_key)
            return {"status": "ok", "path": str(out_path), "attempts": attempt}
        emit(f"  ✗ {stage}：第 {attempt} 次失败 — {last_report.issues[:2]}")
        log.warning("%s: attempt %s failed: %s", stage, attempt, last_report.issues[:3])
        partial.unlink(missing_ok=True)

    issues = last_report.issues if last_report else []
    log.error("%s: failed after %s attempts: %s", stage, settings.pipeline.max_attempts, issues[:3])
    if not allow_best_effort:
        return {"status": "failed", "path": str(out_path), "issues": issues}
    atomic_write(out_path, text)
    return {"status": "best_effort", "path": str(out_path), "issues": issues}


def _load_prompt(name: str) -> str:
    from novelscript.config import PROJECT_ROOT

    parts = [PROJECT_ROOT / "prompts" / "QUALITY_BAR.md"]
    path = PROJECT_ROOT / "prompts" / name
    if path.exists():
        parts.append(path)
    return "\n\n---\n\n".join(p.read_text(encoding="utf-8") for p in parts if p.exists())


def run_s0_engine(ctx: ProjectContext, settings: AppSettings) -> dict[str, Any]:
    from novelscript.checkers.s0 import check_s0_story_engine
    from novelscript.stages.source import format_source_cards_summary, load_source_cards_index

    cards = load_source_cards_index(ctx)

    def checker(text: str) -> CheckerReport:
        return check_s0_story_engine(text, source_cards=cards or None)

    src = load_source_context(ctx)
    source = format_source_block(src, include_characters=False)
    cards_block = format_source_cards_summary(ctx)
    cards_json_path = ctx.root / "source_cards" / "index.json"
    if cards_json_path.exists():
        cards_block = cards_json_path.read_text(encoding="utf-8")
    user = (
        f"{source}\n\n"
        f"## P1 素材卡（权威事实层）\n{cards_block}\n\n"
        "仅根据上述素材卡与原著材料分析，不得编造与原文无关的故事、角色或世界观。\n"
        "不得独立枚举名场面清单——用 card_id 在素材裁决表中引用 mk_*/red_*/evt_*。\n\n"
        "输出 S0_story_engine.md，含 4 台故事发动机与素材裁决表。"
    )
    return _run_stage_loop(
        ctx,
        settings,
        stage="s0_engine",
        out_path=ctx.root / "S0_story_engine.md",
        checker=checker,
        system_prompt=_load_prompt("s0_engine/v1.md"),
        user_prompt=user,
    )


def _project_total_chapters(ctx: ProjectContext) -> int:
    chapters_path = ctx.index_dir / "chapters.json"
    if chapters_path.exists():
        return int(json.loads(chapters_path.read_text(encoding="utf-8")).get("total", 132))
    return 132


def _project_season_count(ctx: ProjectContext, *, total_chapters: int | None = None) -> int:
    total = total_chapters or _project_total_chapters(ctx)
    brief_path = ctx.root / "S0_adaptation_brief.md"
    brief_md = brief_path.read_text(encoding="utf-8") if brief_path.exists() else ""
    return resolve_season_count(brief_md=brief_md or None, total_chapters=total)


def run_s1_premise(ctx: ProjectContext, settings: AppSettings) -> dict[str, Any]:
    from novelscript.checkers.s1 import check_s1_premise
    from novelscript.stages.source import format_source_cards_summary

    season_count = _project_season_count(ctx)

    def checker(text: str) -> CheckerReport:
        return check_s1_premise(text, expected_seasons=season_count)

    brief = (ctx.root / "S0_adaptation_brief.md").read_text(encoding="utf-8") if (ctx.root / "S0_adaptation_brief.md").exists() else ""
    engine = (ctx.root / "S0_story_engine.md").read_text(encoding="utf-8") if (ctx.root / "S0_story_engine.md").exists() else ""
    cards_summary = format_source_cards_summary(ctx)
    source = format_source_block(load_source_context(ctx), include_characters=False)
    return _run_stage_loop(
        ctx,
        settings,
        stage="s1_premise",
        out_path=ctx.root / "S1_series_premise.md",
        checker=checker,
        system_prompt=_load_prompt("s1_premise/v1.md"),
        user_prompt=(
            f"{source}\n\n改编简报（季数真相源）：\n{brief[:4000]}\n\n"
            f"season_count={season_count}（主角逐季蜕变表必须恰好 {season_count} 行）\n\n"
            f"故事引擎（一句话命题须改写自引擎）：\n{engine}\n\n"
            f"P1 素材卡摘要：\n{cards_summary}\n\n"
            "忠于上述原著材料，输出 S1_series_premise.md。"
        ),
    )


def run_s1_bible(ctx: ProjectContext, settings: AppSettings) -> dict[str, Any]:
    from novelscript.checkers.s1 import check_s1_bible
    from novelscript.stages.source import load_source_cards_index

    def checker(text: str) -> CheckerReport:
        return check_s1_bible(text)

    cards = load_source_cards_index(ctx)
    cards_block = json.dumps(cards.get("characters") or [], ensure_ascii=False, indent=2) if cards else ""
    premise = (ctx.root / "S1_series_premise.md").read_text(encoding="utf-8") if (ctx.root / "S1_series_premise.md").exists() else ""
    src = load_source_context(ctx)
    return _run_stage_loop(
        ctx,
        settings,
        stage="s1_bible",
        out_path=ctx.root / "S1_character_bible.md",
        checker=checker,
        system_prompt=_load_prompt("s1_bible/v1.md"),
        user_prompt=(
            f"## P1 角色卡\n{cards_block or src['characters']}\n\n"
            f"系列命题：\n{premise[:4000]}\n\n"
            "从 P1 角色卡扩展，不得替换为虚构主角。输出 S1_character_bible.md。"
        ),
    )


def run_s2_season_map(ctx: ProjectContext, settings: AppSettings) -> dict[str, Any]:
    from novelscript.checkers.s2 import check_s2_season_map, parse_season_map_md
    from novelscript.checkers.base import CheckerReport
    from novelscript.checkers.cross_stage import check_s2_must_keep_coverage
    from novelscript.stages.source import format_source_cards_summary

    total = _project_total_chapters(ctx)
    season_count = _project_season_count(ctx, total_chapters=total)
    must_keep = load_must_keep_scenes(ctx)
    brief = (ctx.root / "S0_adaptation_brief.md").read_text(encoding="utf-8") if (ctx.root / "S0_adaptation_brief.md").exists() else ""

    def checker(text: str) -> CheckerReport:
        seasons = parse_season_map_md(text)
        report = check_s2_season_map(
            seasons,
            total_chapters=total,
            expected_seasons=season_count,
            must_keep=must_keep or None,
            md_text=text,
        )
        if brief and (ctx.root / "S1_series_premise.md").exists():
            s1 = (ctx.root / "S1_series_premise.md").read_text(encoding="utf-8")
            cross = check_cross_stage_season_consistency(
                brief_md=brief,
                s1_md=s1,
                s2_md=text,
                total_chapters=total,
            )
            report.issues.extend(cross.issues)
            if cross.hard_fail:
                report.hard_fail = True
                report.passed = False
        mk_cross = check_s2_must_keep_coverage(text, must_keep or [])
        report.issues.extend(mk_cross.issues)
        if mk_cross.hard_fail:
            report.hard_fail = True
            report.passed = False
        return report

    s0 = (ctx.root / "S0_story_engine.md").read_text(encoding="utf-8") if (ctx.root / "S0_story_engine.md").exists() else ""
    s1 = (ctx.root / "S1_series_premise.md").read_text(encoding="utf-8") if (ctx.root / "S1_series_premise.md").exists() else ""
    strategy = (ctx.root / "adaptation_strategy.md").read_text(encoding="utf-8") if (ctx.root / "adaptation_strategy.md").exists() else ""
    cards_summary = format_source_cards_summary(ctx)
    outline = load_source_context(ctx)["outline"]
    toc = format_chapter_toc(ctx)
    prompt_parts = []
    if toc:
        prompt_parts.append(toc)
    prompt_parts.append(f"故事大纲：\n{outline}")
    if brief:
        prompt_parts.append(f"改编简报（季数真相源）：\n{brief[:5000]}")
    prompt_parts.extend(
        [
            f"S0 故事引擎：\n{s0}",
            f"S1 系列命题：\n{s1}",
            f"创作策略（完整）：\n{strategy}",
            f"P1 素材卡与裁决摘要：\n{cards_summary}",
        ]
    )
    mk_block = format_must_keep_block(must_keep)
    if mk_block:
        prompt_parts.append(mk_block)
    prompt_parts.append(
        f"将 {total} 章原著映射为 S2_season_map.md（{season_count} 季，以改编简报为准）。"
        f"章节范围必须连续覆盖 1–{total}，最后一季结束于第 {total} 章。"
        "优先对齐 stage0 outline 章节组断点；季断点须「渴望被满足 + 更大威胁被打开」。"
        "须含各季四线推进表（A/B/C/D）、多线推进、名场面落点、各季断点理由与时间线鱼骨图。"
    )
    system_prompt = (
        _load_prompt("s2_season_map/v1.md")
        .replace("{season_count}", str(season_count))
        .replace("{total_chapters}", str(total))
    )
    return _run_stage_loop(
        ctx,
        settings,
        stage="s2_season_map",
        out_path=ctx.root / "S2_season_map.md",
        checker=checker,
        system_prompt=system_prompt,
        user_prompt="\n\n".join(prompt_parts),
    )


def run_s3_episodes(ctx: ProjectContext, season_id: str, settings: AppSettings) -> dict[str, Any]:
    from novelscript.checkers.base import CheckerReport
    from novelscript.checkers.s2 import parse_season_map_md
    from novelscript.checkers.s3 import check_s3_episode_list, parse_episode_list_md

    episode_spec = resolve_episode_spec(ctx)
    s2 = (ctx.root / "S2_season_map.md").read_text(encoding="utf-8")
    seasons = parse_season_map_md(s2)
    season = next((s for s in seasons if s["season_id"] == season_id), None)
    ch_range = season["chapter_range"] if season else []

    def checker(text: str) -> CheckerReport:
        eps = parse_episode_list_md(text, season_id=season_id)
        return check_s3_episode_list(
            eps,
            season_chapters=ch_range,
            must_keep=load_must_keep_scenes(ctx) or None,
            episode_spec=episode_spec,
        )

    out = ctx.season_dir(season_id) / "episode_list.md"
    ch_start = ch_range[0] if ch_range else 1
    ch_end = ch_range[-1] if ch_range else ch_start
    season_excerpt = load_chapter_range_excerpt(ctx, ch_start, ch_end)
    s0_path = ctx.root / "S0_story_engine.md"
    premise_path = ctx.root / "S1_series_premise.md"
    bible_path = ctx.root / "S1_character_bible.md"
    s0 = s0_path.read_text(encoding="utf-8") if s0_path.exists() else ""
    premise = premise_path.read_text(encoding="utf-8") if premise_path.exists() else ""
    bible = bible_path.read_text(encoding="utf-8") if bible_path.exists() else ""
    strategy_path = ctx.root / "adaptation_strategy.md"
    strategy = strategy_path.read_text(encoding="utf-8") if strategy_path.exists() else ""
    parts = [format_episode_spec_block(episode_spec), f"S2 季图谱：\n{s2[:4000]}"]
    if s0:
        parts.append(f"S0 故事引擎：\n{s0[:2000]}")
    if premise:
        parts.append(f"S1 系列命题：\n{premise[:2000]}")
    if bible:
        parts.append(f"S1 人物圣经：\n{bible[:3000]}")
    if strategy:
        parts.append(f"创作策略：\n{strategy[:4000]}")
    adapt_bundle = format_adaptation_input_bundle(
        ctx,
        excerpt=season_excerpt,
        excerpt_title=f"{season_id} 原著参考摘录（Ch{ch_start}–{ch_end}）",
        season_id=season_id,
        chapter_numbers=ch_range,
        strategy_md=strategy,
    )
    if adapt_bundle:
        parts.append(adapt_bundle)
    parts.append(
        f"请为 **{season_id}** 输出 episode_list.md，覆盖第 {ch_start}–{ch_end} 章。"
        "按故事引擎与冲突密度切分为可拍单元，禁止默认一章一集。"
        "必保锚点须落入合适集数；非锚点素材可合并删减。"
        "全文中文；若引用原著对白或独白，保留英文原文。"
    )
    return _run_stage_loop(
        ctx,
        settings,
        stage=f"s3_{season_id}",
        out_path=out,
        checker=checker,
        system_prompt=_load_prompt("s3_episodes/v1.md"),
        user_prompt="\n\n".join(parts),
        allow_best_effort=False,
    )


def _persist_adaptation_notes(beat_text: str, notes_path: Path) -> None:
    from novelscript.checkers.adaptation import extract_adaptation_section

    section = extract_adaptation_section(beat_text)
    if section.strip():
        notes_path.write_text(section.strip() + "\n", encoding="utf-8")


def run_s4_beats(ctx: ProjectContext, season_id: str, ep_num: int, settings: AppSettings) -> dict[str, Any]:
    from novelscript.checkers.adaptation import extract_adaptation_section, parse_adaptation_notes_md
    from novelscript.checkers.base import CheckerReport
    from novelscript.checkers.info_ledger import parse_info_ledger_md
    from novelscript.checkers.s3 import parse_episode_list_md
    from novelscript.checkers.s4 import check_s4_beat_sheet, parse_beat_sheet_md

    ep_id = f"{season_id}E{ep_num:02d}"
    episode_spec = resolve_episode_spec(ctx)
    ep_dir = ctx.episode_dir(season_id, ep_num)
    notes_path = ep_dir / "adaptation_notes.md"

    def checker(text: str) -> CheckerReport:
        data = parse_beat_sheet_md(text, episode_id=ep_id)
        adapt_section = extract_adaptation_section(text)
        notes = parse_adaptation_notes_md(adapt_section) if adapt_section else []
        ledger = parse_info_ledger_md(text)
        return check_s4_beat_sheet(
            data,
            episode_spec=episode_spec,
            adaptation_notes=notes,
            info_ledger=ledger,
            source_chapters=source_chs,
        )

    ep_list = (ctx.season_dir(season_id) / "episode_list.md").read_text(encoding="utf-8")
    ep_row = next(
        (ep for ep in parse_episode_list_md(ep_list, season_id=season_id) if ep["episode_id"] == ep_id),
        None,
    )
    source_chs = (ep_row or {}).get("source_chapters") or []
    strategy_path = ctx.root / "adaptation_strategy.md"
    strategy = strategy_path.read_text(encoding="utf-8") if strategy_path.exists() else ""
    adapt_bundle = format_adaptation_input_bundle(
        ctx,
        excerpt=load_episode_chapter_texts(ctx, source_chs),
        excerpt_title=f"{ep_id} 本集原著参考摘录",
        episode_id=ep_id,
        chapter_numbers=source_chs,
        strategy_md=strategy,
    )
    ep_duration = (ep_row or {}).get("duration_target_sec") or episode_spec["duration_sec"]
    parts = [
        format_episode_spec_block(episode_spec),
        f"本集时长预算：**{ep_duration} 秒**",
        f"分集清单：\n{ep_list}",
    ]
    if adapt_bundle:
        parts.append(adapt_bundle)
    parts.append(
        f"请为 {ep_id} 输出 beat_sheet.md（含文末 ## 改编决策记录 与 ## 本集信息账本）。"
        "元数据中文；对白/声音列全部英文。"
        "必保锚点严格保真；非锚点可精编删减并在改编决策表记录。"
    )
    result = _run_stage_loop(
        ctx,
        settings,
        stage=f"s4_{ep_id}",
        out_path=ep_dir / "beat_sheet.md",
        checker=checker,
        system_prompt=_load_prompt("s4_beats/v1.md"),
        user_prompt="\n\n".join(parts),
        temperature=0.5,
        allow_best_effort=False,
    )
    beat_path = ep_dir / "beat_sheet.md"
    if beat_path.exists():
        _persist_adaptation_notes(beat_path.read_text(encoding="utf-8"), notes_path)
    return result


def run_s5_script(ctx: ProjectContext, season_id: str, ep_num: int, settings: AppSettings) -> dict[str, Any]:
    from novelscript.checkers.adaptation import check_adaptation_notes, parse_adaptation_notes_md
    from novelscript.checkers.base import CheckerReport
    from novelscript.checkers.s3 import parse_episode_list_md
    from novelscript.checkers.s5 import check_s5_script, parse_script_md
    from novelscript.quality.rubric import check_script_quality

    ep_id = f"{season_id}E{ep_num:02d}"
    global_id = f"EP{ep_num:03d}"
    episode_spec = resolve_episode_spec(ctx)
    ep_dir = ctx.episode_dir(season_id, ep_num)
    out_md = ep_dir / "script.md"
    out_json = ep_dir / "script.json"
    notes_path = ep_dir / "adaptation_notes.md"
    quality_tier = settings.pipeline.s5_quality_tier

    def checker(text: str) -> CheckerReport:
        script = parse_script_md(text, episode_id=ep_id, global_episode_id=global_id)
        notes: list[dict[str, Any]] = []
        if notes_path.exists():
            notes = parse_adaptation_notes_md(notes_path.read_text(encoding="utf-8"))
        report = check_s5_script(script, episode_chapters=source_chs, adaptation_notes=notes)
        if notes:
            adapt = check_adaptation_notes(notes)
            for issue in adapt.issues:
                if adapt.hard_fail:
                    report.add_issue(issue)
                else:
                    report.add_warning(issue)
        else:
            report.add_issue(f"{ep_id}: missing adaptation_notes.md (produce in S4)")
        if quality_tier and quality_tier != "baseline":
            quality = check_script_quality(script, tier=quality_tier, episode_spec=episode_spec)
            for issue in quality.issues:
                report.add_issue(issue)
        return report

    beats = (ep_dir / "beat_sheet.md").read_text(encoding="utf-8")
    ep_list_path = ctx.season_dir(season_id) / "episode_list.md"
    source_chs: list[int] = []
    strategy = ""
    if (ctx.root / "adaptation_strategy.md").exists():
        strategy = (ctx.root / "adaptation_strategy.md").read_text(encoding="utf-8")
    if ep_list_path.exists():
        ep_list = ep_list_path.read_text(encoding="utf-8")
        ep_row = next(
            (ep for ep in parse_episode_list_md(ep_list, season_id=season_id) if ep["episode_id"] == ep_id),
            None,
        )
        source_chs = (ep_row or {}).get("source_chapters") or []
    adapt_bundle = format_adaptation_input_bundle(
        ctx,
        excerpt=load_episode_chapter_texts(ctx, source_chs),
        excerpt_title=f"{ep_id} 本集原著参考摘录",
        episode_id=ep_id,
        chapter_numbers=source_chs,
        strategy_md=strategy,
    )
    parts = [
        format_episode_spec_block(episode_spec),
        f"节拍表：\n{beats}",
    ]
    if notes_path.exists():
        parts.append(f"改编决策记录：\n{notes_path.read_text(encoding='utf-8')}")
    if adapt_bundle:
        parts.append(adapt_bundle)
    parts.append(
        f"请为 {ep_id} 输出 script.md。元数据中文；对白/声音列全部英文（海外受众）。"
        f"场次时长之和须在 {episode_spec['min_sec']}–{episode_spec['max_sec']} 秒内；"
        f"最后一场 hook 预算 ≥ {episode_spec['hook_sec']} 秒。"
        "必保锚点严格保真；非锚点精编须与改编决策记录一致。"
    )
    result = _run_stage_loop(
        ctx,
        settings,
        stage=f"s5_{ep_id}",
        out_path=out_md,
        checker=checker,
        system_prompt=_load_prompt("s5_script/v1.md"),
        user_prompt="\n\n".join(parts),
        temperature=0.5,
        allow_best_effort=False,
    )
    if out_md.exists():
        from novelscript.convert.schema import script_md_to_json
        from novelscript.io.atomic import write_json as wj

        script = script_md_to_json(out_md, episode_id=ep_id, global_episode_id=global_id)
        wj(out_json, script)
    return result

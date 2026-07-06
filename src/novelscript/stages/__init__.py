from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from novelscript.checkers.base import CheckerReport, passes_gate
from novelscript.config import AppSettings
from novelscript.io.atomic import atomic_write
from novelscript.llm.client import LLMClient
from novelscript.logging import get_logger
from novelscript.pipeline.context import ProjectContext
from novelscript.progress import emit
from novelscript.stages.source import format_source_block, load_source_context

log = get_logger("stages")

STAGE_FORMAT_HINTS: dict[str, str] = {
    "s0_engine": (
        "格式提醒：标题须含「核心爽点」「名场面必保清单」；"
        "发动机编号用「引擎 1」…「引擎 4」；"
        "必保清单必须是 | # | 名场面 | 原著位置 | 为什么不能压缩 | 表格，≥12 行。"
    ),
    "s1_premise": (
        "格式提醒：须有「一句话」标题；"
        "主角逐季蜕变表 5 行，季 ID 为 | **S1** | … | **S5** |。"
    ),
    "s1_bible": (
        "格式提醒：每位主角须含 **想要**、**不愿承认**、**会改变** 三字段；"
        "须有配角合并章节。"
    ),
    "s2_season_map": (
        "格式提醒：五季总表 8 列，季 ID 必须是 S1–S5（禁止 Season 1）；"
        "章节列如 1–30；最后一季须覆盖全书最后一章，无缺口。"
    ),
    "s3_episodes": (
        "格式提醒：全文中文；表头必须是「集|一句话集情|覆盖|核心冲突|主角的选择|集尾钩子」；"
        "集号 **EP01** 格式；覆盖列 Ch1 或 Ch5–6；禁止英文 Logline/Conflict 列名。"
    ),
    "s4_beats": "格式提醒：全文中文；beat 须含外化处理；集尾留视觉悬念。",
    "s5_script": (
        "格式提醒：全文中文；关键英文对白/独白保留原文；"
        "画面动作可拍；集尾须视觉化钩子。"
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
) -> dict[str, Any]:
    if out_path.exists() and out_path.stat().st_size > 0:
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

    run_dir = ctx.runs_dir / stage
    run_dir.mkdir(parents=True, exist_ok=True)
    partial = out_path.with_suffix(out_path.suffix + ".partial")

    last_report: CheckerReport | None = None
    for attempt in range(1, settings.pipeline.max_attempts + 1):
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
            q = check_script_quality(script, tier="production")
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
                context=user_prompt[:2000],
                pilot=stage.startswith("s5_S1E0") and stage[-1] in "123",
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
            return {"status": "ok", "path": str(out_path), "attempts": attempt}
        emit(f"  ✗ {stage}：第 {attempt} 次失败 — {last_report.issues[:2]}")
        log.warning("%s: attempt %s failed: %s", stage, attempt, last_report.issues[:3])
        partial.unlink(missing_ok=True)

    atomic_write(out_path, text)
    log.error("%s: best effort after %s attempts: %s", stage, settings.pipeline.max_attempts, last_report.issues[:3] if last_report else [])
    return {"status": "best_effort", "path": str(out_path), "issues": last_report.issues if last_report else []}


def _load_prompt(name: str) -> str:
    from novelscript.config import PROJECT_ROOT

    parts = [PROJECT_ROOT / "prompts" / "QUALITY_BAR.md"]
    path = PROJECT_ROOT / "prompts" / name
    if path.exists():
        parts.append(path)
    return "\n\n---\n\n".join(p.read_text(encoding="utf-8") for p in parts if p.exists())


def run_s0_engine(ctx: ProjectContext, settings: AppSettings) -> dict[str, Any]:
    from novelscript.checkers.s0 import check_s0_story_engine

    def checker(text: str) -> CheckerReport:
        return check_s0_story_engine(text)

    src = load_source_context(ctx)
    source = format_source_block(src)
    user = (
        f"{source}\n\n"
        "仅根据上述原著材料分析，不得编造与原文无关的故事、角色或世界观。\n\n"
        "输出 S0_story_engine.md，含 4 台故事发动机与名场面必保清单（≥10 条）。"
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


def run_s1_premise(ctx: ProjectContext, settings: AppSettings) -> dict[str, Any]:
    from novelscript.checkers.s1 import check_s1_premise

    def checker(text: str) -> CheckerReport:
        return check_s1_premise(text)

    engine = (ctx.root / "S0_story_engine.md").read_text(encoding="utf-8") if (ctx.root / "S0_story_engine.md").exists() else ""
    source = format_source_block(load_source_context(ctx), include_characters=False)
    return _run_stage_loop(
        ctx,
        settings,
        stage="s1_premise",
        out_path=ctx.root / "S1_series_premise.md",
        checker=checker,
        system_prompt=_load_prompt("s1_premise/v1.md"),
        user_prompt=(
            f"{source}\n\n故事引擎：\n{engine}\n\n"
            "忠于上述原著材料，输出 S1_series_premise.md。"
        ),
    )


def run_s1_bible(ctx: ProjectContext, settings: AppSettings) -> dict[str, Any]:
    from novelscript.checkers.s1 import check_s1_bible

    def checker(text: str) -> CheckerReport:
        return check_s1_bible(text)

    src = load_source_context(ctx)
    premise = (ctx.root / "S1_series_premise.md").read_text(encoding="utf-8") if (ctx.root / "S1_series_premise.md").exists() else ""
    source = format_source_block(src)
    return _run_stage_loop(
        ctx,
        settings,
        stage="s1_bible",
        out_path=ctx.root / "S1_character_bible.md",
        checker=checker,
        system_prompt=_load_prompt("s1_bible/v1.md"),
        user_prompt=(
            f"{source}\n\n系列命题：\n{premise[:4000]}\n\n"
            "使用上述角色库中的角色，不得替换为虚构主角。输出 S1_character_bible.md。"
        ),
    )


def run_s2_season_map(ctx: ProjectContext, settings: AppSettings) -> dict[str, Any]:
    from novelscript.checkers.s2 import check_s2_season_map, parse_season_map_md
    from novelscript.checkers.base import CheckerReport

    total = 132
    chapters_path = ctx.index_dir / "chapters.json"
    if chapters_path.exists():
        total = int(json.loads(chapters_path.read_text(encoding="utf-8")).get("total", total))

    def checker(text: str) -> CheckerReport:
        seasons = parse_season_map_md(text)
        return check_s2_season_map(seasons, total_chapters=total, expected_seasons=5)

    s0 = (ctx.root / "S0_story_engine.md").read_text(encoding="utf-8") if (ctx.root / "S0_story_engine.md").exists() else ""
    s1 = (ctx.root / "S1_series_premise.md").read_text(encoding="utf-8") if (ctx.root / "S1_series_premise.md").exists() else ""
    outline = load_source_context(ctx)["outline"][:3000]
    return _run_stage_loop(
        ctx,
        settings,
        stage="s2_season_map",
        out_path=ctx.root / "S2_season_map.md",
        checker=checker,
        system_prompt=_load_prompt("s2_season_map/v1.md"),
        user_prompt=(
            f"故事大纲：\n{outline}\n\nS0：\n{s0}\n\nS1：\n{s1}\n\n"
            f"将 {total} 章原著映射为 S2_season_map.md（5 季）。"
            f"章节范围必须连续覆盖 1–{total}，最后一季结束于第 {total} 章。"
        ),
    )


def run_s3_episodes(ctx: ProjectContext, season_id: str, settings: AppSettings) -> dict[str, Any]:
    from novelscript.checkers.base import CheckerReport
    from novelscript.checkers.s2 import parse_season_map_md
    from novelscript.checkers.s3 import check_s3_episode_list, parse_episode_list_md

    s2 = (ctx.root / "S2_season_map.md").read_text(encoding="utf-8")
    seasons = parse_season_map_md(s2)
    season = next((s for s in seasons if s["season_id"] == season_id), None)
    ch_range = season["chapter_range"] if season else []

    def checker(text: str) -> CheckerReport:
        eps = parse_episode_list_md(text)
        return check_s3_episode_list(eps, season_chapters=ch_range)

    out = ctx.season_dir(season_id) / "episode_list.md"
    ch_start = ch_range[0] if ch_range else 1
    ch_end = ch_range[-1] if ch_range else ch_start
    s0_path = ctx.root / "S0_story_engine.md"
    premise_path = ctx.root / "S1_series_premise.md"
    bible_path = ctx.root / "S1_character_bible.md"
    s0 = s0_path.read_text(encoding="utf-8") if s0_path.exists() else ""
    premise = premise_path.read_text(encoding="utf-8") if premise_path.exists() else ""
    bible = bible_path.read_text(encoding="utf-8") if bible_path.exists() else ""
    parts = [f"S2 季图谱：\n{s2[:4000]}"]
    if s0:
        parts.append(f"S0 故事引擎：\n{s0[:2000]}")
    if premise:
        parts.append(f"S1 系列命题：\n{premise[:2000]}")
    if bible:
        parts.append(f"S1 人物圣经：\n{bible[:3000]}")
    parts.append(
        f"请为 **{season_id}** 输出 episode_list.md，覆盖第 {ch_start}–{ch_end} 章。"
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
    )


def run_s4_beats(ctx: ProjectContext, season_id: str, ep_num: int, settings: AppSettings) -> dict[str, Any]:
    from novelscript.checkers.base import CheckerReport
    from novelscript.checkers.s4 import check_s4_beat_sheet, parse_beat_sheet_md

    ep_id = f"{season_id}E{ep_num:02d}"

    def checker(text: str) -> CheckerReport:
        data = parse_beat_sheet_md(text, episode_id=ep_id)
        return check_s4_beat_sheet(data)

    ep_list = (ctx.season_dir(season_id) / "episode_list.md").read_text(encoding="utf-8")
    return _run_stage_loop(
        ctx,
        settings,
        stage=f"s4_{ep_id}",
        out_path=ctx.episode_dir(season_id, ep_num) / "beat_sheet.md",
        checker=checker,
        system_prompt=_load_prompt("s4_beats/v1.md"),
        user_prompt=(
            f"分集清单：\n{ep_list}\n\n"
            f"请为 {ep_id} 输出 beat_sheet.md。全文中文；引用对白/独白时保留英文原文。"
        ),
        temperature=0.5,
    )


def run_s5_script(ctx: ProjectContext, season_id: str, ep_num: int, settings: AppSettings) -> dict[str, Any]:
    from novelscript.checkers.base import CheckerReport
    from novelscript.checkers.s5 import check_s5_script, parse_script_md

    ep_id = f"{season_id}E{ep_num:02d}"
    global_id = f"EP{ep_num:03d}"
    out_md = ctx.episode_dir(season_id, ep_num) / "script.md"
    out_json = ctx.episode_dir(season_id, ep_num) / "script.json"

    def checker(text: str) -> CheckerReport:
        script = parse_script_md(text, episode_id=ep_id, global_episode_id=global_id)
        return check_s5_script(script)

    beats = (ctx.episode_dir(season_id, ep_num) / "beat_sheet.md").read_text(encoding="utf-8")
    result = _run_stage_loop(
        ctx,
        settings,
        stage=f"s5_{ep_id}",
        out_path=out_md,
        checker=checker,
        system_prompt=_load_prompt("s5_script/v1.md"),
        user_prompt=(
            f"节拍表：\n{beats}\n\n"
            f"请为 {ep_id} 输出 script.md。全文中文；关键英文对白/独白保留原文。"
        ),
        temperature=0.5,
    )
    if out_md.exists():
        from novelscript.convert.schema import script_md_to_json
        from novelscript.io.atomic import write_json as wj

        script = script_md_to_json(out_md, episode_id=ep_id, global_episode_id=global_id)
        wj(out_json, script)
    return result

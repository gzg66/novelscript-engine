from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from novelscript.config import AppSettings, PROJECT_ROOT
from novelscript.index.chapters import Chapter, novel_preamble, split_chapters
from novelscript.io.atomic import atomic_write
from novelscript.llm.client import LLMClient
from novelscript.logging import get_logger
from novelscript.pipeline.cancel import cancel_check, check_cancelled
from novelscript.progress import emit
from novelscript.pipeline.context import ProjectContext
from novelscript.index.season_plan import check_adaptation_brief, infer_season_count

log = get_logger("stage0")


def _load_prompt(name: str) -> str:
    return (PROJECT_ROOT / "prompts" / "stage0_upstream" / name).read_text(encoding="utf-8")


def _pick_chapter_indices(total: int, *, max_samples: int = 8) -> list[int]:
    if total <= max_samples:
        return list(range(total))
    picks = {0, 1, 2, total - 2, total - 1}
    step = max(1, total // (max_samples - len(picks)))
    for i in range(3, total - 2, step):
        picks.add(i)
        if len(picks) >= max_samples:
            break
    return sorted(picks)[:max_samples]


def _load_chapters(ctx: ProjectContext) -> tuple[str, list[Chapter]]:
    text = ctx.novel_path().read_text(encoding="utf-8")
    return text, split_chapters(text)


def build_outline_source(ctx: ProjectContext, *, per_chapter_chars: int = 600) -> tuple[str, int]:
    """全书目录 + 每章摘要（用于 outline 步，覆盖全部章节）。"""
    text, chapters = _load_chapters(ctx)
    total = len(chapters)
    lines = [f"全书共 {total} 章\n"]
    preamble = novel_preamble(text, max_chars=2000)
    if preamble:
        lines.extend(["## 作品简介", "", preamble, ""])
    lines.append("## 章节目录与摘要\n")
    for ch in chapters:
        preview = ch.text.replace("\n", " ").strip()[:per_chapter_chars]
        lines.append(f"### Chapter {ch.number}\n{preview}\n")
    return "\n".join(lines), total


def build_novel_digest(ctx: ProjectContext, *, per_chapter_chars: int = 3500) -> tuple[str, int]:
    """抽样章节正文摘录（用于 characters 步）。"""
    text, chapters = _load_chapters(ctx)
    total = len(chapters)
    lines = [f"全书共 {total} 章\n", "## 正文摘录\n"]
    for idx in _pick_chapter_indices(total):
        ch = chapters[idx]
        body = ch.text[:per_chapter_chars]
        lines.append(f"### Chapter {ch.number}\n{body}\n")
    return "\n".join(lines), total


def _preference_block(ctx: ProjectContext, *, max_chars: int = 8000) -> str:
    path = ctx.root / "project_preference.md"
    if not path.exists() or path.stat().st_size == 0:
        return ""
    return f"\n\n## 项目偏好\n\n{path.read_text(encoding='utf-8')[:max_chars]}"


def _step_done(path: Path, *, min_chars: int, must_contain: tuple[str, ...]) -> bool:
    if not path.exists() or path.stat().st_size < min_chars:
        return False
    text = path.read_text(encoding="utf-8")
    return len(text) >= min_chars and all(token in text for token in must_contain)


def _generate_step(
    *,
    client: LLMClient,
    system: str,
    user: str,
    out_path: Path,
    min_chars: int,
    must_contain: tuple[str, ...],
    project_root: Path,
    on_cancel: Callable[[], None],
) -> None:
    partial = out_path.with_suffix(out_path.suffix + ".partial")
    for attempt in range(1, 3):
        check_cancelled(project_root)
        client.generate_text(system=system, user=user, write_path=partial, stream=True, cancel_check=on_cancel)
        text = partial.read_text(encoding="utf-8")
        if len(text) >= min_chars and all(token in text for token in must_contain):
            atomic_write(out_path, text)
            partial.unlink(missing_ok=True)
            return
        user = user + f"\n\n上次输出不合格（attempt {attempt}），请补全缺失章节并加长内容。"
    text = partial.read_text(encoding="utf-8")
    atomic_write(out_path, text)
    partial.unlink(missing_ok=True)


def run_stage0_upstream(ctx: ProjectContext, settings: AppSettings) -> dict[str, str]:
    from novelscript.stages.source import persist_stage0_hash, stage0_cache_valid

    stage0_dir = ctx.input_dir / "stage0"
    stage0_dir.mkdir(parents=True, exist_ok=True)
    outline_path = stage0_dir / "outline.md"
    chars_path = stage0_dir / "characters.md"

    if stage0_cache_valid(ctx):
        emit("  ✓ stage0：已有大纲与角色库，跳过生成")
        return {"status": "cached", "outline": str(outline_path)}

    outline_source, total = build_outline_source(ctx)
    digest, _ = build_novel_digest(ctx)
    client = LLMClient(settings)
    on_cancel = cancel_check(ctx.root)
    log.info("stage0 开始生成，全书 %s 章", total)

    if _step_done(outline_path, min_chars=800, must_contain=("Logline", "章节组")):
        emit("  ✓ stage0：故事大纲已存在，跳过生成")
    else:
        emit(f"  → stage0：正在分析小说（{total} 章）并生成故事大纲…")
        _generate_step(
            client=client,
            system=_load_prompt("outline.md"),
            user=f"全书 {total} 章。\n\n{outline_source}",
            out_path=outline_path,
            min_chars=800,
            must_contain=("Logline", "章节组"),
            project_root=ctx.root,
            on_cancel=on_cancel,
        )
        emit("  ✓ stage0：故事大纲已生成")
    outline = outline_path.read_text(encoding="utf-8")

    if _step_done(chars_path, min_chars=500, must_contain=("role=",)):
        emit("  ✓ stage0：角色库已存在，跳过生成")
    else:
        emit("  → stage0：正在生成角色库…")
        _generate_step(
            client=client,
            system=_load_prompt("characters.md"),
            user=f"## 故事大纲\n{outline[:12000]}\n\n## 小说摘录\n{digest[:20000]}",
            out_path=chars_path,
            min_chars=500,
            must_contain=("role=",),
            project_root=ctx.root,
            on_cancel=on_cancel,
        )
        emit("  ✓ stage0：角色库已生成")

    persist_stage0_hash(ctx)
    from novelscript.pipeline.stage_deps import persist_stage_hashes

    persist_stage_hashes(ctx, "stage0")
    log.info("stage0 完成 outline=%s characters=%s", outline_path, chars_path)
    return {"status": "ok", "outline": str(outline_path), "characters": str(chars_path)}


def _source_cards_summary(ctx: ProjectContext) -> str:
    from novelscript.stages.source import format_source_cards_summary

    return format_source_cards_summary(ctx)


def _engine_one_liner(ctx: ProjectContext) -> str:
    engine_path = ctx.root / "S0_story_engine.md"
    if not engine_path.exists():
        return ""
    for line in engine_path.read_text(encoding="utf-8").splitlines():
        if line.strip().startswith("> **"):
            return line.strip()
    return ""


def run_adaptation_brief(ctx: ProjectContext, settings: AppSettings) -> dict[str, Any]:
    """Generate S0_adaptation_brief.md after P1 + S0 (no Ch-level must-keep table)."""
    from novelscript.pipeline.stage_deps import persist_stage_hashes, stage_inputs_valid

    brief_path = ctx.root / "S0_adaptation_brief.md"
    stage0_dir = ctx.input_dir / "stage0"
    outline_path = stage0_dir / "outline.md"
    if not outline_path.exists():
        return {"status": "skipped", "reason": "missing outline"}

    outline = outline_path.read_text(encoding="utf-8")
    _, total = build_outline_source(ctx)
    recommended = infer_season_count(total)

    if (
        _step_done(brief_path, min_chars=400, must_contain=("竖屏", "季间叙事原则", "全剧规模"))
        and stage_inputs_valid(ctx, "brief")
    ):
        emit("  ✓ brief：改编简报已存在，跳过生成")
        return {"status": "cached", "path": str(brief_path)}

    cards_summary = _source_cards_summary(ctx)
    engine_line = _engine_one_liner(ctx)
    brief_user = (
        f"全书共 {total} 章。推荐季数：{recommended} 季"
        f"（须结合大纲「章节组」天然断点微调 ±1，须在 PRD 4–6 季范围内）。\n"
        f"单季集数固定 20–30 集，全剧规模必须为多季（禁止在全剧规模行写「单季完结」）。\n\n"
        f"## 故事大纲\n{outline[:15000]}"
        f"{_preference_block(ctx)}\n\n"
        f"## 素材卡摘要\n{cards_summary}\n\n"
        f"## S0 一句话引擎\n{engine_line or '（见故事引擎全文）'}\n\n"
        "不要输出 Ch 级必保名场面表；名场面权威源是 P1 素材卡。"
    )
    client = LLMClient(settings)
    on_cancel = cancel_check(ctx.root)
    emit("  → brief：正在生成改编简报…")
    _generate_step(
        client=client,
        system=_load_prompt("brief.md"),
        user=brief_user,
        out_path=brief_path,
        min_chars=400,
        must_contain=("竖屏", "季间叙事原则", "全剧规模"),
        project_root=ctx.root,
        on_cancel=on_cancel,
    )
    brief_text = brief_path.read_text(encoding="utf-8")
    brief_report = check_adaptation_brief(brief_text, total_chapters=total)
    if not brief_report.passed:
        emit(f"  ⚠ 改编简报校验未过，重试一次：{'; '.join(brief_report.issues[:3])}")
        _generate_step(
            client=client,
            system=_load_prompt("brief.md"),
            user=(
                brief_user
                + f"\n\n上次输出问题：{'; '.join(brief_report.issues)}。"
                "请修正：全剧规模须为多季（如「5 季 × 24 集」），单季 20–30 集，含季间叙事原则；"
                "不要写 Ch 级必保名场面表。"
            ),
            out_path=brief_path,
            min_chars=400,
            must_contain=("竖屏", "季间叙事原则", "全剧规模"),
            project_root=ctx.root,
            on_cancel=on_cancel,
        )
    emit("  ✓ brief：改编简报已生成")
    persist_stage_hashes(ctx, "brief")
    return {"status": "ok", "path": str(brief_path)}

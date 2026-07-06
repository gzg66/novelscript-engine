from __future__ import annotations

from pathlib import Path

from novelscript.config import AppSettings, PROJECT_ROOT
from novelscript.index.chapters import split_chapters
from novelscript.io.atomic import atomic_write
from novelscript.llm.client import LLMClient
from novelscript.logging import get_logger
from novelscript.pipeline.context import ProjectContext
from novelscript.progress import emit

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


def build_novel_digest(ctx: ProjectContext, *, per_chapter_chars: int = 3500) -> tuple[str, int]:
    text = ctx.novel_path().read_text(encoding="utf-8")
    chapters = split_chapters(text)
    total = len(chapters)
    lines = [f"全书共 {total} 章\n"]
    lines.append("## 章节目录\n")
    for ch in chapters:
        preview = ch.text.replace("\n", " ")[:80]
        lines.append(f"- Chapter {ch.number}: {preview}…")
    lines.append("\n## 正文摘录\n")
    for idx in _pick_chapter_indices(total):
        ch = chapters[idx]
        body = ch.text[:per_chapter_chars]
        lines.append(f"### Chapter {ch.number}\n{body}\n")
    return "\n".join(lines), total


def _generate_step(
    *,
    client: LLMClient,
    system: str,
    user: str,
    out_path: Path,
    min_chars: int,
    must_contain: tuple[str, ...],
) -> None:
    partial = out_path.with_suffix(out_path.suffix + ".partial")
    for attempt in range(1, 3):
        client.generate_text(system=system, user=user, write_path=partial, stream=True)
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
    stage0_dir = ctx.input_dir / "stage0"
    stage0_dir.mkdir(parents=True, exist_ok=True)
    outline_path = stage0_dir / "outline.md"
    chars_path = stage0_dir / "characters.md"
    brief_path = ctx.root / "S0_adaptation_brief.md"

    if (
        outline_path.exists()
        and chars_path.exists()
        and brief_path.exists()
        and outline_path.stat().st_size > 200
        and chars_path.stat().st_size > 200
        and brief_path.stat().st_size > 200
    ):
        emit("  ✓ stage0：已有大纲/角色/改编简报，跳过生成")
        return {"status": "cached", "outline": str(outline_path)}

    digest, total = build_novel_digest(ctx)
    client = LLMClient(settings)
    log.info("stage0 开始生成，全书 %s 章", total)

    emit(f"  → stage0：正在分析小说（{total} 章）并生成故事大纲…")
    _generate_step(
        client=client,
        system=_load_prompt("outline.md"),
        user=f"全书 {total} 章。\n\n{digest[:50000]}",
        out_path=outline_path,
        min_chars=800,
        must_contain=("Logline", "章节组"),
    )
    outline = outline_path.read_text(encoding="utf-8")
    emit("  ✓ stage0：故事大纲已生成")

    emit("  → stage0：正在生成角色库…")
    _generate_step(
        client=client,
        system=_load_prompt("characters.md"),
        user=f"## 故事大纲\n{outline[:12000]}\n\n## 小说摘录\n{digest[:20000]}",
        out_path=chars_path,
        min_chars=500,
        must_contain=("role=",),
    )
    emit("  ✓ stage0：角色库已生成")

    emit("  → stage0：正在生成改编简报…")
    _generate_step(
        client=client,
        system=_load_prompt("brief.md"),
        user=f"## 故事大纲\n{outline[:15000]}",
        out_path=brief_path,
        min_chars=400,
        must_contain=("竖屏", "必保"),
    )
    emit("  ✓ stage0：改编简报已生成")

    log.info("stage0 完成 outline=%s characters=%s brief=%s", outline_path, chars_path, brief_path)
    return {"status": "ok", "outline": str(outline_path), "characters": str(chars_path), "brief": str(brief_path)}

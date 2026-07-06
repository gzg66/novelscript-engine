from __future__ import annotations

from novelscript.index.chapters import split_chapters
from novelscript.pipeline.context import ProjectContext


class SourceContextError(ValueError):
    pass


def _read(path) -> str:
    return path.read_text(encoding="utf-8") if path.exists() else ""


def _novel_excerpt(ctx: ProjectContext, *, max_chars: int = 8000, chapter_count: int = 3) -> str:
    novel = ctx.novel_path()
    if not novel.exists():
        return ""
    text = novel.read_text(encoding="utf-8")
    try:
        chunks = [ch.text for ch in split_chapters(text)[:chapter_count]]
    except ValueError:
        return text[:max_chars]
    return "\n\n".join(chunks)[:max_chars]


def load_source_context(ctx: ProjectContext) -> dict[str, str]:
    stage0 = ctx.input_dir / "stage0"
    return {
        "brief": _read(ctx.root / "S0_adaptation_brief.md"),
        "outline": _read(stage0 / "outline.md"),
        "characters": _read(stage0 / "characters.md"),
        "novel_excerpt": _novel_excerpt(ctx),
    }


def _seed_minimal_stage0(ctx: ProjectContext, src: dict[str, str]) -> None:
    """测试/skip_llm 用的最小 stage0 占位。"""
    stage0 = ctx.input_dir / "stage0"
    stage0.mkdir(parents=True, exist_ok=True)
    excerpt = src["novel_excerpt"] or "待分析"
    (stage0 / "outline.md").write_text(
        f"# 故事大纲\n\n## Logline\n{excerpt[:500]}\n\n## 章节组 Beats\n### 第 1 章\n",
        encoding="utf-8",
    )
    (stage0 / "characters.md").write_text(
        f"# 角色库\n\n## 主角 (id=`hero`, role=`protagonist`)\n{excerpt[:300]}\n",
        encoding="utf-8",
    )
    (ctx.root / "S0_adaptation_brief.md").write_text(
        "# 改编简报\n\n## 目标形态硬约束\n\n| 形态 | 竖屏短剧 |\n\n## 必保清单\n\n1. 开篇\n",
        encoding="utf-8",
    )


def ensure_source_context(ctx: ProjectContext, settings=None, *, skip_llm: bool = False) -> dict[str, str]:
    """确保 stage0 底稿存在；缺失时从小说原文自动生成。"""
    src = load_source_context(ctx)
    if src["brief"].strip() and src["outline"].strip() and src["characters"].strip():
        return src
    if not src["novel_excerpt"].strip():
        raise SourceContextError(
            f"无法解析小说原文，请确认 {ctx.novel_path()} 含有 Chapter N 格式的章节标题"
        )
    if skip_llm:
        _seed_minimal_stage0(ctx, src)
        return load_source_context(ctx)
    if settings is None:
        from novelscript.config import load_settings

        settings = load_settings()
    from novelscript.stages.stage0_upstream import run_stage0_upstream

    run_stage0_upstream(ctx, settings)
    src = load_source_context(ctx)
    if not src["outline"].strip():
        raise SourceContextError("stage0 自动生成失败：故事大纲为空")
    return src


def require_source_context(ctx: ProjectContext) -> dict[str, str]:
    """兼容旧调用；仅检查不自动生成。"""
    src = load_source_context(ctx)
    if not src["outline"].strip() and not src["brief"].strip():
        raise SourceContextError("缺少 stage0 底稿，请先运行 pipeline 或提供 input/stage0/")
    if not src["novel_excerpt"].strip():
        raise SourceContextError(f"无法解析小说：{ctx.novel_path()}")
    return src


def format_source_block(src: dict[str, str], *, include_characters: bool = True) -> str:
    parts: list[str] = []
    if src["brief"].strip():
        parts.append(f"## 改编简报\n{src['brief'][:4000]}")
    if src["outline"].strip():
        parts.append(f"## 故事大纲\n{src['outline'][:6000]}")
    if include_characters and src["characters"].strip():
        parts.append(f"## 角色库\n{src['characters'][:4000]}")
    if src["novel_excerpt"].strip():
        parts.append(f"## 小说开篇摘录\n{src['novel_excerpt']}")
    return "\n\n".join(parts)

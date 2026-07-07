from __future__ import annotations

import hashlib
import json
from typing import Any

from novelscript.index.chapters import Chapter, novel_preamble, split_chapters
from novelscript.index.must_keep import load_must_keep
from novelscript.pipeline.context import ProjectContext

_FIDELITY_RULE = (
    "改编铁律：节拍/场次必须源自下方「原著摘录」中的事件与对白；"
    "不得发明摘录中不存在的情节；不得把其他章节的名场面提前到本集。"
)


class SourceContextError(ValueError):
    pass


def _read(path) -> str:
    return path.read_text(encoding="utf-8") if path.exists() else ""


def novel_content_hash(ctx: ProjectContext) -> str:
    novel = ctx.novel_path()
    if not novel.exists():
        return ""
    return hashlib.sha256(novel.read_bytes()).hexdigest()


def persist_stage0_hash(ctx: ProjectContext) -> None:
    from novelscript.io.atomic import write_json

    meta = dict(ctx.meta)
    meta["stage0_novel_hash"] = novel_content_hash(ctx)
    write_json(ctx.root / "project.meta.json", meta)
    ctx.meta = meta


def stage0_cache_valid(ctx: ProjectContext, src: dict[str, str] | None = None) -> bool:
    """True when stage0 outline+characters exist and match novel + preference hashes."""
    src = src or load_source_context(ctx)
    if not (src["outline"].strip() and src["characters"].strip()):
        return False
    stage0 = ctx.input_dir / "stage0"
    for name in ("outline.md", "characters.md"):
        path = stage0 / name
        if not path.exists() or path.stat().st_size <= 200:
            return False
    stored = ctx.meta.get("stage0_novel_hash")
    current = novel_content_hash(ctx)
    if not stored:
        if current:
            persist_stage0_hash(ctx)
        return bool(current)
    if stored != current:
        return False
    from novelscript.pipeline.stage_deps import compute_input_hashes

    hashes = compute_input_hashes(ctx)
    pref_stored = (ctx.meta.get("stage_input_hashes") or {}).get("stage0", {}).get("preference_hash")
    if pref_stored and pref_stored != hashes.get("preference_hash"):
        return False
    return True


def load_novel_excerpt(ctx: ProjectContext, *, max_chars: int = 8000, chapter_count: int = 3) -> str:
    """Return opening chapter text from input/novel.txt for upstream prompts (P0, stage0)."""
    novel = ctx.novel_path()
    if not novel.exists():
        return ""
    text = novel.read_text(encoding="utf-8")
    try:
        chunks = [ch.text for ch in split_chapters(text)[:chapter_count]]
    except ValueError:
        return text[:max_chars]
    return "\n\n".join(chunks)[:max_chars]


def _novel_excerpt(ctx: ProjectContext, *, max_chars: int = 8000, chapter_count: int = 3) -> str:
    return load_novel_excerpt(ctx, max_chars=max_chars, chapter_count=chapter_count)


def format_novel_excerpt_block(excerpt: str, *, title: str = "小说开篇摘录") -> str:
    if not excerpt.strip():
        return ""
    return f"## {title}\n\n{excerpt}"


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
    if stage0_cache_valid(ctx, src):
        return src
    if not src["novel_excerpt"].strip():
        raise SourceContextError(
            f"无法解析小说原文，请确认 {ctx.novel_path()} 含有 Chapter N 格式的章节标题"
        )
    if skip_llm:
        _seed_minimal_stage0(ctx, src)
        persist_stage0_hash(ctx)
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


def _chapter_map(ctx: ProjectContext) -> dict[int, Chapter]:
    novel = ctx.novel_path()
    if not novel.exists():
        return {}
    try:
        return {ch.number: ch for ch in split_chapters(novel.read_text(encoding="utf-8"))}
    except ValueError:
        return {}


def load_chapter_texts(
    ctx: ProjectContext,
    chapter_numbers: list[int],
    *,
    max_chars_per_chapter: int = 12000,
    max_total_chars: int = 28000,
) -> str:
    """Return markdown blocks of chapter excerpts for LLM prompts."""
    chapters = _chapter_map(ctx)
    if not chapters:
        return ""

    parts: list[str] = []
    total = 0
    for num in sorted({n for n in chapter_numbers if n > 0}):
        ch = chapters.get(num)
        if ch is None:
            continue
        body = ch.text[:max_chars_per_chapter]
        block = f"### Chapter {num}\n{body}"
        if total + len(block) > max_total_chars:
            remaining = max_total_chars - total
            if remaining > 300:
                parts.append(block[:remaining] + "\n…（截断）")
            break
        parts.append(block)
        total += len(block)
    return "\n\n".join(parts)


def load_chapter_range_excerpt(
    ctx: ProjectContext,
    ch_start: int,
    ch_end: int,
    *,
    per_chapter_chars: int = 2500,
    max_total_chars: int = 45000,
) -> str:
    if ch_end < ch_start:
        return ""
    return load_chapter_texts(
        ctx,
        list(range(ch_start, ch_end + 1)),
        max_chars_per_chapter=per_chapter_chars,
        max_total_chars=max_total_chars,
    )


def format_chapter_source_block(excerpt: str, *, title: str = "原著摘录") -> str:
    if not excerpt.strip():
        return ""
    return f"## {title}\n\n{_FIDELITY_RULE}\n\n{excerpt}"


def format_source_block(src: dict[str, str], *, include_characters: bool = True, compact: bool = False) -> str:
    def _clip(text: str, limit: int) -> str:
        return text[:limit] if compact else text

    parts: list[str] = []
    if src["brief"].strip():
        parts.append(f"## 改编简报\n{_clip(src['brief'], 4000)}")
    if src["outline"].strip():
        parts.append(f"## 故事大纲\n{_clip(src['outline'], 6000)}")
    if include_characters and src["characters"].strip():
        parts.append(f"## 角色库\n{_clip(src['characters'], 4000)}")
    if src["novel_excerpt"].strip():
        parts.append(f"## 小说开篇摘录\n{src['novel_excerpt']}")
    return "\n\n".join(parts)


def format_chapter_toc(ctx: ProjectContext) -> str:
    path = ctx.index_dir / "chapters.json"
    if not path.exists():
        return ""
    data = json.loads(path.read_text(encoding="utf-8"))
    chapters = data.get("chapters") or []
    total = int(data.get("total") or len(chapters) or 0)
    if not chapters:
        return ""
    lines = [f"## 章节目录（共 {total} 章）", ""]
    for ch in chapters:
        num = ch.get("number")
        title = str(ch.get("title") or "").strip()
        lines.append(f"- Ch{num}: {title}" if title else f"- Ch{num}")
    return "\n".join(lines)


def load_source_cards_index(ctx: ProjectContext) -> dict[str, Any]:
    path = ctx.root / "source_cards" / "index.json"
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return {}


def format_source_cards_summary(ctx: ProjectContext, *, max_items: int = 20) -> str:
    """Compact summary of P1 cards (+ optional S0 rulings) for brief/S2/S3 prompts."""
    cards = load_source_cards_index(ctx)
    if not cards:
        md_path = ctx.root / "source_cards" / "index.md"
        if md_path.exists():
            return md_path.read_text(encoding="utf-8")[:6000]
        return "（素材卡尚未生成）"

    lines = [
        f"事件卡 {len(cards.get('events') or [])} 条；"
        f"名场面卡 {len(cards.get('must_keep') or [])} 条；"
        f"冗余卡 {len(cards.get('redundant') or [])} 条；"
        f"角色卡 {len(cards.get('characters') or [])} 条",
        "",
    ]
    rulings: dict[str, dict[str, str]] = {}
    engine_path = ctx.root / "S0_story_engine.md"
    if engine_path.exists():
        from novelscript.index.must_keep import parse_rulings_from_story_engine

        rulings = parse_rulings_from_story_engine(engine_path.read_text(encoding="utf-8"))

    if cards.get("must_keep"):
        lines.append("### 名场面卡与裁决")
        for card in cards["must_keep"][:max_items]:
            card_id = str(card.get("id", "?")).lower()
            ruling = rulings.get(card_id, {})
            verdict = ruling.get("verdict") or "—"
            engine = ruling.get("engine") or ""
            suffix = f" → {verdict}" + (f" ({engine})" if engine and engine != "—" else "")
            lines.append(
                f"- {card_id}: {card.get('title', '')} @ {card.get('source_ref', '')}{suffix}"
            )
    if cards.get("redundant") and rulings:
        dropped = [
            c
            for c in cards["redundant"][:max_items]
            if "删除" in rulings.get(str(c.get("id", "")).lower(), {}).get("verdict", "")
        ]
        if dropped:
            lines.append("")
            lines.append("### 冗余卡（已裁决删除/合并）")
            for card in dropped:
                card_id = str(card.get("id", "?")).lower()
                verdict = rulings.get(card_id, {}).get("verdict", "删除")
                lines.append(f"- {card_id}: {card.get('title', '')} → {verdict}")
    return "\n".join(lines)


def extract_strategy_constraints(strategy_md: str) -> str:
    """Extract P3 禁止改动 block for S3 prompts."""
    if not strategy_md.strip():
        return ""
    lines = ["## 创作策略 · 禁止改动摘要", ""]
    in_forbidden = False
    for line in strategy_md.splitlines():
        if "禁止改动" in line:
            in_forbidden = True
            lines.append(line)
            continue
        if in_forbidden:
            if line.startswith("## ") and "禁止" not in line:
                break
            lines.append(line)
    if len(lines) <= 2:
        return ""
    return "\n".join(lines)


def format_p1_source_block(ctx: ProjectContext, src: dict[str, str]) -> str:
    """P1 专用：完整大纲/角色 + 全书抽样正文，覆盖中后段情节。"""
    from novelscript.stages.stage0_upstream import build_novel_digest

    digest, total = build_novel_digest(ctx)
    parts: list[str] = []
    if src["outline"].strip():
        parts.append(f"## 故事大纲\n{src['outline']}")
    if src["characters"].strip():
        parts.append(f"## 角色库（P1 角色卡输入参考）\n{src['characters']}")
    parts.append(f"## 全书正文抽样（全书 {total} 章）\n{digest}")
    if src["novel_excerpt"].strip():
        parts.append(f"## 小说开篇摘录\n{src['novel_excerpt']}")
    return "\n\n".join(parts)


def load_must_keep_scenes(ctx: ProjectContext) -> list[dict[str, Any]]:
    path = ctx.index_dir / "must_keep_scenes.json"
    if not path.exists():
        return []
    return load_must_keep(path)


def _must_keep_matches(
    scene: dict[str, Any],
    *,
    season_id: str | None,
    episode_id: str | None,
    chapter_numbers: set[int],
) -> bool:
    if episode_id and scene.get("episode_id") == episode_id:
        return True
    if season_id and scene.get("season_id") == season_id:
        return True
    scene_chs = set(scene.get("source_chapters") or [])
    return bool(chapter_numbers and scene_chs & chapter_numbers)


def format_must_keep_block(
    scenes: list[dict[str, Any]],
    *,
    season_id: str | None = None,
    episode_id: str | None = None,
    chapter_numbers: list[int] | None = None,
) -> str:
    if not scenes:
        return ""
    ch_set = {n for n in (chapter_numbers or []) if n > 0}
    if not season_id and not episode_id and not ch_set:
        selected = scenes
    else:
        selected = [
            s
            for s in scenes
            if _must_keep_matches(s, season_id=season_id, episode_id=episode_id, chapter_numbers=ch_set)
        ]
        if not selected and ch_set:
            selected = [s for s in scenes if set(s.get("source_chapters") or []) & ch_set]
    if not selected:
        return ""

    lines = [
        "## 名场面必保清单（本阶段须覆盖）",
        "",
        "| card_id | 名场面 | 原著位置 | 为什么不能压缩 |",
        "|---|---|---|---|",
    ]
    for scene in selected:
        chs = scene.get("source_chapters") or []
        loc = ", ".join(f"Ch{c}" for c in chs[:6]) or "—"
        why = str(scene.get("why_irreducible") or "")[:160]
        card_id = scene.get("card_id") or scene.get("id") or ""
        lines.append(f"| {card_id} | {scene.get('name', '')} | {loc} | {why} |")
    return "\n".join(lines)


def load_episode_chapter_texts(ctx: ProjectContext, chapter_numbers: list[int]) -> str:
    """Per-episode chapter excerpts with budget scaled to episode span."""
    nums = sorted({n for n in chapter_numbers if n > 0})
    if not nums:
        return ""
    per_ch = 12000
    total_cap = min(120000, per_ch * len(nums))
    return load_chapter_texts(ctx, nums, max_chars_per_chapter=per_ch, max_total_chars=total_cap)


def build_review_context(ctx: ProjectContext, stage: str, user_prompt: str) -> str:
    """Structured context for llm_review: prompt essentials + must_keep for the stage."""
    parts = [user_prompt[:12000]]
    scenes = load_must_keep_scenes(ctx)
    mk = ""
    if stage.startswith("s3_"):
        season_id = stage.replace("s3_", "", 1)
        mk = format_must_keep_block(scenes, season_id=season_id) or format_must_keep_block(scenes)
    elif stage.startswith("s4_") or stage.startswith("s5_"):
        ep_id = stage.split("_", 1)[1]
        mk = format_must_keep_block(scenes, episode_id=ep_id) or format_must_keep_block(scenes)
    elif stage in ("s0_engine", "s2_season_map", "p3_strategy"):
        mk = format_must_keep_block(scenes)
    if mk:
        parts.append(mk)
    return "\n\n".join(parts)[:16000]

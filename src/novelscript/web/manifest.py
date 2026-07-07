from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any

STAGE_SPECS: list[tuple[str, str, list[tuple[str, str, str]]]] = [
    (
        "P0",
        "模式与口味校准",
        [("preference", "project_preference.md", "项目偏好")],
    ),
    (
        "stage0",
        "故事大纲与角色库",
        [
            ("outline", "input/stage0/outline.md", "故事大纲"),
            ("characters", "input/stage0/characters.md", "角色库"),
        ],
    ),
    (
        "P1",
        "素材拆解",
        [("cards", "source_cards/index.md", "素材卡索引")],
    ),
    (
        "S0",
        "故事引擎",
        [("engine", "S0_story_engine.md", "故事引擎")],
    ),
    (
        "brief",
        "改编简报",
        [("brief", "S0_adaptation_brief.md", "改编简报")],
    ),
    (
        "P3",
        "创作策略",
        [("strategy", "adaptation_strategy.md", "改编策略")],
    ),
    (
        "S1",
        "系列定位 & 人物圣经",
        [
            ("premise", "S1_series_premise.md", "系列定位"),
            ("bible", "S1_character_bible.md", "人物圣经"),
        ],
    ),
    (
        "S2",
        "季图谱",
        [("season-map", "S2_season_map.md", "五季规划")],
    ),
    (
        "S3",
        "分集清单",
        [],
    ),
    (
        "S4",
        "分集节拍表",
        [],
    ),
    (
        "S5",
        "场次剧本",
        [],
    ),
    (
        "P6",
        "试播集观感卡",
        [("review", "audit/review_cards_S1_pilot.md", "试播观感卡")],
    ),
]

RUNNABLE_STAGE_IDS = frozenset(sid for sid, _, _ in STAGE_SPECS)

DEFAULT_ENGINES = [
    {"id": "I", "name": "亲情守护与阶级逆袭", "symbol": "❄"},
    {"id": "II", "name": "冰火暗三角拉扯", "symbol": "△"},
    {"id": "III", "name": "现代灵魂 vs 封建皇权", "symbol": "⚔"},
    {"id": "IV", "name": "深渊阴谋与末日救赎", "symbol": "◎"},
]


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _chapter_count(project_root: Path) -> int:
    chapters_path = project_root / "index" / "chapters.json"
    if chapters_path.exists():
        data = _read_json(chapters_path)
        return len(data.get("chapters", []))
    novel = project_root / "input" / "novel.txt"
    if novel.exists():
        return max(1, novel.read_text(encoding="utf-8", errors="replace").count("\n") // 80)
    return 0


def _stage_status(project_root: Path, docs: list[dict[str, str]], spec_count: int) -> str:
    if not docs:
        extra = _scan_stage_glob(project_root, docs)
        if extra:
            return "partial" if len(extra) < 1 else "complete"
        return "pending"
    if len(docs) >= spec_count:
        return "complete"
    return "partial"


def _scan_stage_glob(project_root: Path, existing_docs: list[dict[str, str]]) -> list[dict[str, str]]:
    del existing_docs
    return []


def _collect_stage_docs(project_root: Path, stage_id: str, spec: list[tuple[str, str, str]]) -> list[dict[str, str]]:
    docs: list[dict[str, str]] = []
    for doc_id, filename, title in spec:
        if (project_root / filename).exists():
            docs.append({"id": doc_id, "title": title, "file": filename})

    if stage_id == "S3":
        for path in sorted(project_root.glob("S3_episode_list_*.md")):
            sid = path.stem.replace("S3_episode_list_", "").upper()
            docs.append({"id": path.stem, "title": f"分集清单 {sid}", "file": path.name})
        for path in sorted((project_root / "seasons").glob("**/episode_list.md")) if (project_root / "seasons").exists() else []:
            rel = path.relative_to(project_root).as_posix()
            season_match = re.search(r"seasons/s(\d+)/", rel, re.I)
            sid = f"S{season_match.group(1)}" if season_match else rel
            docs.append({"id": rel.replace("/", "-"), "title": f"分集清单 {sid.upper()}", "file": rel})
    elif stage_id == "S4":
        for path in sorted(project_root.glob("S4_beat_sheet*.md")):
            docs.append({"id": path.stem, "title": path.stem.replace("_", " "), "file": path.name})
        for path in sorted((project_root / "seasons").glob("**/beat_sheet.md")) if (project_root / "seasons").exists() else []:
            rel = path.relative_to(project_root).as_posix()
            docs.append({"id": rel.replace("/", "-"), "title": rel, "file": rel})
    elif stage_id == "S5":
        for path in sorted(project_root.glob("S5_script_ep*.md")):
            docs.append({"id": path.stem, "title": path.stem.replace("_", " "), "file": path.name})
        for path in sorted((project_root / "seasons").glob("**/script.md")) if (project_root / "seasons").exists() else []:
            rel = path.relative_to(project_root).as_posix()
            docs.append({"id": rel.replace("/", "-"), "title": rel, "file": rel})

    return docs


def _strip_md_inline(text: str) -> str:
    return re.sub(r"\*\*([^*]+)\*\*", r"\1", text).strip()


def _parse_seasons_from_s2(project_root: Path) -> list[dict[str, Any]]:
    path = project_root / "S2_season_map.md"
    if not path.exists():
        return []

    text = path.read_text(encoding="utf-8")
    seasons: list[dict[str, Any]] = []
    for i, block in enumerate(re.split(r"^## Season \d+", text, flags=re.MULTILINE | re.IGNORECASE), start=1):
        if i == 1 and not block.strip().startswith(":"):
            continue
        title_match = re.search(r"\*\*Season Title\*\*:\s*(.+)", block)
        arc_match = re.search(r"\*\*情绪弧线.*?\*\*:\s*(.+)", block)
        hook_match = re.search(r"\*\*季尾悬念钩子.*?\*\*[\s\S]*?\*\s*(.+?)\*", block)
        chapter_match = re.search(r"Chapters?\s+(\d+\s*[-–]\s*\d+)", block, re.I)
        cn_title = re.search(r"Season Title\*\*:\s*([^\(]+)", block)
        title = (cn_title.group(1).strip() if cn_title else f"Season {i}")[:40]
        seasons.append(
            {
                "id": i,
                "title": title,
                "chapters": chapter_match.group(1).replace(" ", "") if chapter_match else "",
                "arc": arc_match.group(1).strip() if arc_match else "",
                "hook": hook_match.group(1).strip() if hook_match else "",
            }
        )
        if len(seasons) >= 5:
            break

    if not seasons:
        table_rows = re.findall(r"\|\s*\*\*Season (\d+)\*\*\s*\|[^|]+\|\s*\*\*(.+?)\*\*", text)
        for num, title in table_rows[:5]:
            seasons.append({"id": int(num), "title": title.strip(), "chapters": "", "arc": "", "hook": ""})

    if not seasons:
        for line in text.splitlines():
            m = re.match(r"^\|\s*\*\*S(\d+)\*\*\s*\|(.+)$", line)
            if not m:
                continue
            parts = [p.strip() for p in m.group(2).split("|")]
            if len(parts) < 2:
                continue
            hook = ""
            if len(parts) > 6:
                hook_match = re.search(r"\*\*钩子\*\*[：:](.+?)(?:\*\*|$)", parts[6])
                if hook_match:
                    hook = hook_match.group(1).strip().rstrip("*").strip()
            seasons.append(
                {
                    "id": int(m.group(1)),
                    "title": parts[0][:60],
                    "chapters": parts[1].replace(" ", ""),
                    "arc": _strip_md_inline(parts[2])[:120] if len(parts) > 2 else "",
                    "hook": hook[:120],
                }
            )
            if len(seasons) >= 5:
                break
    return seasons


def _parse_characters_from_bible(project_root: Path) -> list[dict[str, Any]]:
    path = project_root / "S1_character_bible.md"
    if not path.exists():
        return []

    text = path.read_text(encoding="utf-8")
    section = re.search(r"## 一线角色.*?(?=\n## |\Z)", text, re.DOTALL)
    scope = section.group(0) if section else text

    chars: list[dict[str, Any]] = []
    pattern = r"^###\s+(.+?)\s*——\s*(.+?)\s*\(id=`([^`]+)`,\s*role=`([^`]+)`\)"
    for m in re.finditer(pattern, scope, re.MULTILINE):
        name = re.sub(r"\s*\([^)]+\)\s*$", "", m.group(1).strip()).strip()
        role = m.group(2).strip()
        char_id = (m.group(3) or name).split("-")[0]
        chars.append({"id": char_id, "name": name, "role": role})
        if len(chars) >= 3:
            break
    return chars


_STAGE_TO_PHASE = {
    "P0": "P0",
    "stage0": "stage0",
    "P1": "P1",
    "S0": "S0",
    "brief": "brief",
    "P3": "P3",
    "S1": "S1",
    "S2": "S2",
    "S3": "S3",
    "S4": "S4/S5",
    "S5": "S4/S5",
    "P6": "P6",
}


def _manifest_resume_state(manifest: dict[str, Any]) -> tuple[str, int, str]:
    stages = manifest.get("stages", [])
    complete = [s for s in stages if s.get("status") == "complete"]
    total = len(stages)
    done = len(complete)
    chapters = manifest.get("project", {}).get("chapters") or 0

    if done >= total and done > 0:
        return "done", 100, "全部阶段已完成"
    if not complete:
        if chapters:
            return "index", _PHASE_PROGRESS["index"], f"章节索引已完成（{chapters} 章）· 点击「开始精编」启动 P0→S5 全流程"
        return "idle", 0, "等待启动精编管线"

    last_id = complete[-1]["id"]
    phase = _STAGE_TO_PHASE.get(last_id, "stage0")
    progress = _PHASE_PROGRESS.get(phase, 0)
    message = f"已完成 {done}/{total} 个阶段，可继续精编或单独重跑某一阶段"
    return phase, progress, message


def _project_title(project_root: Path, meta: dict[str, Any]) -> str:
    if meta.get("display_title"):
        return str(meta["display_title"])
    for name in ("S0_adaptation_brief.md", "S1_series_premise.md"):
        path = project_root / name
        if not path.exists():
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line.startswith("# ") and "·" in line:
                parts = [p.strip() for p in line.lstrip("# ").split("·")]
                generic = {"改编简报", "S1 系列定位", "S1 角色圣经", "S0 故事引擎"}
                for part in reversed(parts):
                    if not part or part in generic or re.match(r"^S[0-9]\b", part):
                        continue
                    return part.split("→")[0].split("(")[0].strip()
            if line.startswith("# ") and len(line) > 3:
                return line.lstrip("# ").split("(")[0].strip()
    return project_root.name.replace("-", " ").title()


def _mtime(project_root: Path) -> str | None:
    candidates = [project_root / "pipeline.log", project_root / "project.meta.json"]
    latest: float | None = None
    for path in candidates:
        if path.exists():
            latest = max(latest or 0, path.stat().st_mtime)
    if latest is None:
        return None
    return datetime.fromtimestamp(latest).isoformat(timespec="seconds")


def build_manifest(project_root: Path) -> dict[str, Any]:
    meta = _read_json(project_root / "project.meta.json")
    slug = project_root.name
    chapters = _chapter_count(project_root)

    stages: list[dict[str, Any]] = []
    for stage_id, label, spec in STAGE_SPECS:
        docs = _collect_stage_docs(project_root, stage_id, spec)
        expected = len(spec) if spec else (1 if docs else 0)
        status = "complete" if docs and (not spec or len(docs) >= len(spec)) else ("partial" if docs else "pending")
        if stage_id in ("S3", "S4", "S5") and docs:
            status = "partial" if len(docs) < 3 else "complete"
        elif stage_id in ("S3", "S4", "S5") and not docs:
            status = "pending"
        stages.append({"id": stage_id, "label": label, "status": status, "docs": docs})

    seasons = _parse_seasons_from_s2(project_root)
    has_s0 = (project_root / "S0_story_engine.md").exists()

    overlay_path = project_root / "web" / "data" / "manifest.json"
    overlay: dict[str, Any] = _read_json(overlay_path) if overlay_path.exists() else {}

    characters = overlay.get("characters") or meta.get("characters") or _parse_characters_from_bible(project_root)
    engines = overlay.get("engines") or (DEFAULT_ENGINES if has_s0 or (project_root / "S0_adaptation_brief.md").exists() else [])
    if overlay.get("seasons"):
        seasons = overlay["seasons"]

    return {
        "project": {
            "id": slug,
            "title": _project_title(project_root, meta),
            "subtitle": meta.get("subtitle", slug),
            "mode": meta.get("mode", "M1"),
            "chapters": chapters,
            "seasons": len(seasons) or 5,
            "episodesPerSeason": meta.get("episodes_per_season", 30),
            "aspectRatio": meta.get("aspect_ratio", "9:16"),
            "genre": meta.get("genre", "竖屏短剧 · M1 标准精编"),
        },
        "stages": stages,
        "characters": characters,
        "seasons": seasons,
        "engines": engines,
    }


def list_projects(projects_dir: Path) -> list[dict[str, Any]]:
    if not projects_dir.is_dir():
        return []

    items: list[dict[str, Any]] = []
    for path in sorted(projects_dir.iterdir()):
        if not path.is_dir() or not (path / "project.meta.json").exists():
            continue
        meta = _read_json(path / "project.meta.json")
        manifest = build_manifest(path)
        completed = sum(1 for s in manifest["stages"] if s["status"] == "complete")
        items.append(
            {
                "slug": path.name,
                "title": manifest["project"]["title"],
                "chapters": manifest["project"]["chapters"],
                "mode": manifest["project"]["mode"],
                "stagesComplete": completed,
                "stagesTotal": len(manifest["stages"]),
                "updatedAt": _mtime(path),
            }
        )
    items.sort(key=lambda x: x.get("updatedAt") or "", reverse=True)
    return items


_STAGE_LABELS = {sid: label for sid, label, _ in STAGE_SPECS}

_PHASE_PROGRESS: dict[str, int] = {
    "index": 4,
    "stage0": 8,
    "P0": 10,
    "P1": 16,
    "S0": 22,
    "brief": 26,
    "P3": 30,
    "S1": 38,
    "S2": 48,
    "S3": 58,
    "S4/S5": 72,
    "fidelity": 86,
    "P6": 94,
    "done": 100,
}


def _log_message(line: str) -> str:
    m = re.search(r"\] (.+)$", line)
    return m.group(1).strip() if m else line.strip()


def _friendly_activity(msg: str) -> str | None:
    rules: list[tuple[str, str]] = [
        (r"Stage index: building", "正在建立章节索引…"),
        (r"Stage index: done \((\d+) chapters\)", r"章节索引完成 · \1 章"),
        (r"stage0 开始生成", "正在生成故事大纲与改编底稿…"),
        (r"stage0 完成", "故事大纲与改编底稿已就绪"),
        (r"Stage P0: project preference", "P0 · 模式与口味校准"),
        (r"Stage P1: source cards", "P1 · 素材拆解"),
        (r"Stage S0: story engine", "S0 · 故事引擎"),
        (r"Stage brief:", "改编简报"),
        (r"Stage P3: adaptation strategy", "P3 · 创作策略"),
        (r"Stage S1: premise", "S1 · 系列定位"),
        (r"Stage S1: character bible", "S1 · 人物圣经"),
        (r"Stage S2: season map", "S2 · 季图谱"),
        (r"Stage S3: episode lists", "S3 · 分集清单"),
        (r"Stage S4/S5: (\d+) episodes", r"S4/S5 · 精编 \1 集剧本"),
        (r"Episode (\S+): done", r"✓ \1 剧本完成"),
        (r"Running fidelity audit", "忠实度审计"),
        (r"Pipeline finished stages=.*\bS5\b", "全部阶段已完成"),
        (r"Pipeline finished", "本批次阶段已完成"),
        (r"Pipeline start", "精编管线已启动"),
        (r"LLM 流式输出中… (\d+) 字", r"AI 生成中 · \1 字"),
        (r"LLM 完成：(\d+) 字", r"AI 输出完成 · \1 字"),
        (r"s\d+_\w+: LLM attempt (\d+)/(\d+)", r"第 \1/\2 次 AI 生成"),
        (r"s\d+_\w+: attempt (\d+) failed", r"第 \1 次校验未通过，重试中"),
        (r"Blocked at", "已暂停，等待人工审批"),
        (r"等待人工审批", "等待人工审批"),
        (r"Pipeline cancelled", "用户已中断精编"),
        (r"用户已中断", "用户已中断精编"),
        (r"Web pipeline session ended", "精编会话已结束"),
        (r"Web pipeline session started", "精编管线已启动"),
    ]
    for pattern, repl in rules:
        m = re.search(pattern, msg)
        if m:
            if r"\1" in repl or r"\2" in repl:
                return re.sub(pattern, repl, msg)
            return repl
    return None


def _log_timestamp(line: str) -> datetime | None:
    m = re.match(r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})", line)
    if not m:
        return None
    try:
        return datetime.strptime(m.group(1), "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return None


_PIPELINE_LOG_MARKERS = ("[novelscript.pipeline]", "[novelscript.stages]", "[novelscript.llm]", "[pipeline]")


def _log_is_stale(lines: list[str], *, max_age_seconds: int = 90) -> bool:
    for line in reversed(lines):
        if not any(marker in line for marker in _PIPELINE_LOG_MARKERS):
            continue
        ts = _log_timestamp(line)
        if ts is None:
            continue
        return (datetime.now() - ts).total_seconds() > max_age_seconds
    return True


def _parse_pipeline_progress(lines: list[str]) -> dict[str, Any]:
    phase = "idle"
    current_stage: str | None = None
    message = "等待启动精编管线"
    episodes_total = 0
    episodes_done = 0
    started_at: str | None = None
    running = False

    for line in lines:
        msg = _log_message(line)
        ts_match = re.match(r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})", line)
        if "Pipeline start" in msg:
            running = True
            phase = "index"
            message = "精编管线已启动"
            if ts_match:
                started_at = ts_match.group(1)
        elif "Stage index: building" in msg:
            phase = "index"
            current_stage = None
            message = "正在建立章节索引…"
        elif "Stage index: done" in msg:
            phase = "stage0"
            message = msg.replace("Stage index: done", "章节索引完成").replace("chapters", "章")
        elif "Stage P0:" in msg:
            phase = "P0"
            current_stage = "P0"
            message = "P0 · 模式与口味校准"
        elif "stage0 开始" in msg:
            phase = "stage0"
            message = "正在生成故事大纲与改编底稿…"
        elif "stage0 完成" in msg:
            phase = "S0"
            message = "故事大纲与改编底稿已就绪"
        elif "Stage S0:" in msg:
            phase = "S0"
            current_stage = "S0"
            message = "S0 · 故事引擎"
        elif "Stage P1:" in msg:
            phase = "P1"
            current_stage = "P1"
            message = "P1 · 素材拆解"
        elif "Stage P3:" in msg:
            phase = "P3"
            current_stage = "P3"
            message = "P3 · 创作策略"
        elif "Stage S1: premise" in msg:
            phase = "S1"
            current_stage = "S1"
            message = "S1 · 系列定位"
        elif "Stage S1: character bible" in msg:
            phase = "S1"
            current_stage = "S1"
            message = "S1 · 人物圣经"
        elif "Stage S2:" in msg:
            phase = "S2"
            current_stage = "S2"
            message = "S2 · 季图谱"
        elif "Stage S3:" in msg:
            phase = "S3"
            current_stage = "S3"
            message = "S3 · 分集清单"
        elif "Stage S4/S5:" in msg:
            phase = "S4/S5"
            current_stage = "S4"
            m = re.search(r"(\d+) episodes", msg)
            if m:
                episodes_total = int(m.group(1))
            message = f"S4/S5 · 精编 {episodes_total or '多'} 集剧本"
        elif "Episode " in msg and ": done" in msg:
            episodes_done += 1
            ep = re.search(r"Episode (\S+): done", msg)
            if ep:
                message = f"✓ {ep.group(1)} 剧本完成"
        elif "fidelity audit" in msg.lower() or "忠实度审计" in msg:
            phase = "fidelity"
            current_stage = None
            message = "忠实度审计"
        elif "Stage P6" in msg or "试播集观感卡" in msg:
            phase = "P6"
            current_stage = "P6"
            message = "P6 · 试播集观感卡"
        elif "Pipeline finished" in msg:
            running = False
            phase = "done"
            current_stage = None
            message = "全部阶段已完成"
        elif "Pipeline cancelled" in msg or "用户已中断" in msg:
            running = False
            message = "用户已中断精编"
        elif "Web pipeline session ended" in msg:
            running = False
            message = "精编已停止"
        elif "Blocked at" in msg or "已暂停" in msg:
            running = False
            friendly = _friendly_activity(msg)
            if friendly:
                message = friendly

        if "LLM 流式输出中" in msg or "LLM 完成" in msg:
            friendly = _friendly_activity(msg)
            if friendly:
                message = friendly
        elif "LLM attempt" in msg or "attempt" in msg and "failed" in msg:
            friendly = _friendly_activity(msg)
            if friendly:
                message = friendly

    if running and any("Pipeline finished" in _log_message(l) for l in lines[-3:]):
        running = False
        phase = "done"
        message = "全部阶段已完成"

    if running and _log_is_stale(lines):
        running = False
        message = "精编已停止"

    activity: list[str] = []
    for line in reversed(lines):
        msg = _log_message(line)
        friendly = _friendly_activity(msg)
        if friendly and (not activity or activity[-1] != friendly):
            activity.append(friendly)
        if len(activity) >= 8:
            break
    activity.reverse()

    progress = _PHASE_PROGRESS.get(phase, 0)
    if phase == "S4/S5" and episodes_total > 0:
        span = _PHASE_PROGRESS["fidelity"] - _PHASE_PROGRESS["S4/S5"]
        progress = _PHASE_PROGRESS["S4/S5"] + int(span * episodes_done / episodes_total)

    return {
        "phase": phase,
        "currentStage": current_stage,
        "currentLabel": _STAGE_LABELS.get(current_stage or "", "") if current_stage else None,
        "message": message,
        "progress": progress,
        "episodesDone": episodes_done,
        "episodesTotal": episodes_total,
        "startedAt": started_at,
        "running": running,
        "activity": activity,
    }


GATE_RESUME_FROM: dict[str, str] = {"S2": "S3", "s1_pilot": "S4"}

GATE_LABELS: dict[str, str] = {"S2": "季图谱", "s1_pilot": "试播集"}


def detect_pending_gate(project_root: Path) -> dict[str, Any] | None:
    """Return a pending gate when the pipeline is paused before the next stage."""
    from novelscript.pipeline.context import load_project
    from novelscript.pipeline.orchestrator import Pipeline

    ctx = load_project(project_root)

    s2_path = project_root / "S2_season_map.md"
    s1_eps = ctx.season_dir("S1") / "episode_list.md"
    if s2_path.exists() and not s1_eps.exists():
        approved = ctx.is_approved("S2")
        issues: list[str] = []
        passed = True
        try:
            report = Pipeline(ctx).check("S2")
            issues = report.issues[:6]
            passed = report.passed
        except Exception:
            passed = False
            issues = ["无法解析季图谱产物"]
        if approved:
            message = "季图谱已就绪，但分集清单尚未生成。请审阅后点击继续精编"
        elif passed:
            message = "五季规划已生成，请审阅后批准继续分集清单与剧本精编"
        else:
            message = "季图谱校验未完全通过，请审阅后决定是否继续或重新生成"
        return {
            "gate": "S2",
            "label": GATE_LABELS["S2"],
            "stageId": "S2",
            "docFile": "S2_season_map.md",
            "passed": passed,
            "issues": issues,
            "resumeFrom": GATE_RESUME_FROM["S2"],
            "approved": approved,
            "resumeOnly": approved,
            "message": message,
        }

    if s1_eps.exists():
        ep1 = ctx.episode_dir("S1", 1) / "script.json"
        if not ep1.exists():
            approved = ctx.is_approved("s1_pilot")
            message = (
                "试播集审批已通过，但剧本尚未生成。点击继续精编"
                if approved
                else "分集清单已就绪，请审阅后批准试播集（EP01–03）剧本精编"
            )
            return {
                "gate": "s1_pilot",
                "label": GATE_LABELS["s1_pilot"],
                "stageId": "S3",
                "docFile": "seasons/s1/episode_list.md",
                "passed": True,
                "issues": [],
                "resumeFrom": GATE_RESUME_FROM["s1_pilot"],
                "approved": approved,
                "resumeOnly": approved,
                "message": message,
            }

    return None


def pipeline_status(project_root: Path) -> dict[str, Any]:
    from novelscript.pipeline.cancel import is_pipeline_active

    log_path = project_root / "pipeline.log"
    lines: list[str] = []
    if log_path.exists():
        lines = log_path.read_text(encoding="utf-8", errors="replace").splitlines()

    parsed = _parse_pipeline_progress(lines) if lines else {
        "phase": "idle",
        "currentStage": None,
        "currentLabel": None,
        "message": "等待启动精编管线",
        "progress": 0,
        "episodesDone": 0,
        "episodesTotal": 0,
        "startedAt": None,
        "running": False,
        "activity": [],
    }

    manifest = build_manifest(project_root)
    done = sum(1 for s in manifest["stages"] if s["status"] == "complete")
    total = len(manifest["stages"])

    if not parsed["running"]:
        if done == total and done > 0:
            parsed["phase"] = "done"
            parsed["message"] = "全部阶段已完成"
            parsed["progress"] = 100
        elif parsed["phase"] == "done" or (parsed["phase"] == "idle" and done > 0):
            resume_phase, resume_progress, resume_message = _manifest_resume_state(manifest)
            parsed["phase"] = resume_phase
            parsed["progress"] = resume_progress
            parsed["message"] = resume_message
            if done < total:
                parsed["activity"] = [a for a in parsed["activity"] if a != "全部阶段已完成"]

    pending_gate = detect_pending_gate(project_root)
    if pending_gate:
        parsed["running"] = False
        parsed["phase"] = pending_gate["stageId"]
        parsed["currentStage"] = pending_gate["stageId"]
        parsed["currentLabel"] = pending_gate["label"]
        parsed["message"] = pending_gate["message"]
        parsed["progress"] = _PHASE_PROGRESS.get(pending_gate["stageId"], parsed["progress"])

    from novelscript.audit.decision_log import load_decision_queue

    decision_queue = load_decision_queue(project_root / "audit")

    parsed["running"] = parsed["running"] and is_pipeline_active(project_root)

    return {
        "running": parsed["running"],
        "phase": parsed["phase"],
        "currentStage": parsed["currentStage"],
        "currentLabel": parsed["currentLabel"],
        "message": parsed["message"],
        "progress": parsed["progress"],
        "episodesDone": parsed["episodesDone"],
        "episodesTotal": parsed["episodesTotal"],
        "startedAt": parsed["startedAt"],
        "activity": parsed["activity"],
        "stagesComplete": done,
        "stagesTotal": total,
        "logTail": [_log_message(l) for l in lines[-6:]],
        "stages": manifest["stages"],
        "pendingGate": pending_gate,
        "decisionQueue": decision_queue,
    }

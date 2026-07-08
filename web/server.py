from __future__ import annotations

import json
import re
import shutil
import sys
import threading
from http import HTTPStatus
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

ENGINE_ROOT = Path(__file__).resolve().parents[1]
WEB_DIR = Path(__file__).resolve().parent
PROJECTS_DIR = ENGINE_ROOT / "projects"
SRC_DIR = ENGINE_ROOT / "src"
PORTAL_BUILD = "20260706k"

if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from novelscript.config import load_settings  # noqa: E402
from novelscript.logging import setup_logging  # noqa: E402
from novelscript.pipeline.cancel import (  # noqa: E402
    PipelineCancelled,
    acquire_run_lock,
    clear_cancel,
    is_pipeline_active,
    mark_stopped,
    release_run_lock,
    request_cancel,
)
from novelscript.pipeline.context import init_project, load_project  # noqa: E402
from novelscript.pipeline.orchestrator import Pipeline  # noqa: E402

_running: set[str] = set()
_run_lock = threading.Lock()


def _manifest_api():
    """Reload manifest on each API call so code edits apply without server restart."""
    import importlib

    import novelscript.web.manifest as manifest_mod

    return importlib.reload(manifest_mod)


def _normalize_stage_id(stage: str) -> str:
    """Align API/UI stage ids (brief, stage0) with manifest RUNNABLE_STAGE_IDS."""
    s = stage.strip()
    lower = s.lower()
    if lower in ("stage0", "brief", "index"):
        return lower
    return s.upper()


def _parse_multipart(body: bytes, content_type: str) -> dict[str, tuple[str | None, bytes]]:
    boundary = content_type.split("boundary=", 1)[1].strip().strip('"').encode()
    delimiter = b"--" + boundary
    parts = body.split(delimiter)
    fields: dict[str, tuple[str | None, bytes]] = {}

    for part in parts:
        if not part or part in (b"--", b"--\r\n"):
            continue
        chunk = part.lstrip(b"\r\n")
        if chunk.endswith(b"--"):
            chunk = chunk[:-2].rstrip(b"\r\n")
        header_blob, _, payload = chunk.partition(b"\r\n\r\n")
        headers = header_blob.decode("utf-8", errors="replace")
        name_match = re.search(r'name="([^"]+)"', headers)
        if not name_match:
            continue
        name = name_match.group(1)
        filename_match = re.search(r'filename="([^"]*)"', headers)
        filename = filename_match.group(1) if filename_match else None
        if payload.endswith(b"\r\n"):
            payload = payload[:-2]
        fields[name] = (filename, payload)
    return fields


def _json_response(handler: SimpleHTTPRequestHandler, status: int, payload: dict | list) -> None:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


def _read_json_body(handler: SimpleHTTPRequestHandler) -> dict:
    length = int(handler.headers.get("Content-Length", 0))
    if length <= 0:
        return {}
    raw = handler.rfile.read(length)
    return json.loads(raw.decode("utf-8"))


def _safe_slug(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", Path(name).stem.lower()).strip("-")
    return slug or "novel"


def _project_root(slug: str) -> Path | None:
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]*", slug):
        return None
    root = (PROJECTS_DIR / slug).resolve()
    if PROJECTS_DIR.resolve() not in root.parents:
        return None
    if not root.is_dir():
        return None
    return root


def _create_project(
    upload_name: str,
    content: bytes,
    *,
    display_title: str = "",
    mode: str = "M1",
    pilot_test: bool = False,
) -> dict:
    slug = _safe_slug(upload_name)
    project_root = PROJECTS_DIR / slug
    if project_root.exists() and (project_root / "input" / "novel.txt").exists():
        n = 2
        while (PROJECTS_DIR / f"{slug}-{n}").exists():
            n += 1
        slug = f"{slug}-{n}"
        project_root = PROJECTS_DIR / slug

    project_root.mkdir(parents=True, exist_ok=True)
    temp_novel = project_root / "_upload.txt"
    temp_novel.write_bytes(content)

    ctx = init_project(project_root, novel_src=temp_novel, mode=mode)
    temp_novel.unlink(missing_ok=True)

    meta_path = project_root / "project.meta.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    if display_title:
        meta["display_title"] = display_title
    else:
        meta["display_title"] = Path(upload_name).stem
    if pilot_test:
        meta["pilot_test"] = True
    meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")

    setup_logging(project_root=ctx.root)
    chapters = 0
    try:
        pipe = Pipeline(ctx, load_settings())
        index_result = pipe._run_index()
        chapters = index_result.get("total_chapters", 0)
    except Exception as exc:
        import logging

        logging.getLogger("novelscript.web").warning("index skipped: %s", exc)

    return {
        "slug": slug,
        "title": meta["display_title"],
        "chapters": chapters,
        "redirect": f"/project.html?slug={slug}",
    }


def _project_is_running(slug: str, root: Path | None) -> bool:
    if slug in _running:
        return True
    if root is not None and is_pipeline_active(root):
        return True
    return False


def _enrich_running_item(item: dict, slug: str, root: Path, manifest_mod) -> None:
    st = manifest_mod.pipeline_status(root)
    item["running"] = True
    item["phase"] = st.get("phase", "index")
    item["message"] = st.get("message", "精编运行中…")
    item["progress"] = st.get("progress", 0)


def _run_pipeline(slug: str, *, through: str | None = "S5", from_stage: str | None = None, skip_llm: bool = False) -> None:
    import logging

    from novelscript.progress import emit

    web_log = logging.getLogger("novelscript.web")

    with _run_lock:
        if slug in _running:
            return
        _running.add(slug)

    root: Path | None = None
    try:
        root = _project_root(slug)
        if root is None:
            return
        clear_cancel(root)
        acquire_run_lock(root, slug=slug)
        ctx = load_project(root)
        setup_logging(project_root=ctx.root)
        settings = load_settings()
        web_log.info("Web pipeline session started slug=%s", slug)
        logging.getLogger("pipeline").info("Web pipeline session started slug=%s", slug)
        pipe = Pipeline(ctx, settings)
        pilot_test = bool(ctx.meta.get("pilot_test"))
        result = pipe.run(
            through=through or "S5",
            from_stage=from_stage,
            skip_llm=skip_llm,
            auto_approve=pilot_test,
            stop_after_pilot=pilot_test,
        )
        if result.get("cancelled"):
            web_log.info("Pipeline cancelled for %s", slug)
        elif result.get("blocked"):
            web_log.warning("Pipeline blocked for %s: %s", slug, result["blocked"])
    except PipelineCancelled:
        logging.getLogger("pipeline").info("⏹ 用户已中断精编")
        logging.getLogger("pipeline").info("Web pipeline session ended slug=%s", slug)
        emit("⏹ 用户已中断精编")
        web_log.info("Pipeline cancelled for %s", slug)
        if root is not None:
            mark_stopped(root)
    except Exception as exc:
        web_log.exception("Pipeline failed for %s: %s", slug, exc)
    finally:
        if root is not None:
            release_run_lock(root)
            try:
                setup_logging(project_root=root)
                web_log.info("Web pipeline session ended slug=%s", slug)
                logging.getLogger("pipeline").info("Web pipeline session ended slug=%s", slug)
            except Exception:
                pass
        with _run_lock:
            _running.discard(slug)


def _delete_project(slug: str) -> dict:
    root = _project_root(slug)
    if root is None:
        return {"error": "project not found"}
    if _project_is_running(slug, root):
        return {"error": "项目正在精编，请先停止后再删除"}
    shutil.rmtree(root)
    with _run_lock:
        _running.discard(slug)
    return {"ok": True, "slug": slug}


def _cancel_pipeline(slug: str) -> dict:
    import logging

    from novelscript.progress import emit

    root = _project_root(slug)
    if root is None:
        return {"error": "project not found"}
    request_cancel(root)
    active = _project_is_running(slug, root)
    setup_logging(project_root=root)
    logging.getLogger("pipeline").info("⏹ 用户已中断精编")
    logging.getLogger("pipeline").info("Web pipeline session ended slug=%s", slug)
    emit("⏹ 用户已中断精编")
    mark_stopped(root)
    logging.getLogger("novelscript.web").info("Cancel requested for %s (active=%s)", slug, active)
    return {
        "status": "cancelling" if active else "stopped",
        "slug": slug,
        "running": active,
    }


def _approve_gate(slug: str, gate: str, *, resume: bool = True, resume_only: bool = False) -> dict:
    manifest_mod = _manifest_api()
    GATE_RESUME_FROM = manifest_mod.GATE_RESUME_FROM

    root = _project_root(slug)
    if root is None:
        return {"error": "project not found"}
    if gate not in GATE_RESUME_FROM:
        return {"error": "invalid gate"}

    if not resume_only:
        approved_dir = root / "approved"
        approved_dir.mkdir(parents=True, exist_ok=True)
        (approved_dir / f"{gate}.approved").write_text("", encoding="utf-8")

    resume_from = GATE_RESUME_FROM[gate]
    if resume:
        threading.Thread(
            target=_run_pipeline,
            args=(slug,),
            kwargs={"through": "S5", "from_stage": resume_from},
            daemon=True,
        ).start()

    return {"status": "approved", "gate": gate, "resumeFrom": resume_from}


def _stage_output_paths(root: Path, stage: str) -> list[Path]:
    stage = _normalize_stage_id(stage)
    paths: list[Path] = []
    if stage == "P0":
        paths.append(root / "project_preference.md")
    elif stage == "stage0":
        paths.extend(
            [
                root / "input" / "stage0" / "outline.md",
                root / "input" / "stage0" / "characters.md",
            ]
        )
    elif stage == "P1":
        paths.extend([root / "source_cards" / "index.md", root / "source_cards" / "index.json"])
    elif stage == "P3":
        paths.extend([root / "adaptation_strategy.md", root / "index" / "must_keep_scenes.json"])
    elif stage == "P6":
        paths.append(root / "audit" / "review_cards_S1_pilot.md")
    elif stage == "S0":
        paths.extend([root / "S0_story_engine.md"])
    elif stage == "brief":
        paths.append(root / "S0_adaptation_brief.md")
    elif stage == "S1":
        paths.extend([root / "S1_series_premise.md", root / "S1_character_bible.md"])
    elif stage == "S2":
        paths.append(root / "S2_season_map.md")
    elif stage == "S3":
        paths.extend(root.glob("S3_episode_list_*.md"))
        if (root / "seasons").is_dir():
            paths.extend((root / "seasons").glob("**/episode_list.md"))
    elif stage == "S4":
        paths.extend(root.glob("S4_beat_sheet*.md"))
        if (root / "seasons").is_dir():
            paths.extend((root / "seasons").glob("**/beat_sheet.md"))
    elif stage == "S5":
        paths.extend(root.glob("S5_script_ep*.md"))
        if (root / "seasons").is_dir():
            paths.extend((root / "seasons").glob("**/script.md"))
            paths.extend((root / "seasons").glob("**/script.json"))
    return paths


def _ensure_web_stage_prereqs(
    pipe: Pipeline,
    ctx,
    stage: str,
) -> None:
    from novelscript.pipeline.cancel import check_cancelled
    from novelscript.stages.source import require_source_context

    stage = _normalize_stage_id(stage)
    # 单阶段重跑只校验前置产物，不触发 stage0 / 索引等上游阶段的再生成
    if stage in ("P0", "stage0", "S0", "brief", "P6"):
        return
    check_cancelled(ctx.root)
    if not (ctx.root / "index" / "chapters.json").exists():
        pipe._run_index(rebuild_must_keep=False)
    require_source_context(ctx)
    if (ctx.root / "adaptation_strategy.md").exists() or (ctx.root / "S0_story_engine.md").exists():
        pipe._rebuild_must_keep_index()


def _run_stage(slug: str, stage: str, *, skip_llm: bool = False) -> None:
    from concurrent.futures import ThreadPoolExecutor, as_completed

    from novelscript.stages.pre_pipeline import (
        run_p0_preference,
        run_p1_source_cards,
        run_p3_strategy,
        run_p6_pilot_review,
    )
    from novelscript.stages import (
        run_s0_engine,
        run_s1_bible,
        run_s1_premise,
        run_s2_season_map,
        run_s3_episodes,
        run_s4_beats,
        run_s5_script,
    )
    from novelscript.stages.source import require_source_context
    from novelscript.stages.stage0_upstream import run_adaptation_brief, run_stage0_upstream

    with _run_lock:
        if slug in _running:
            return
        _running.add(slug)

    root: Path | None = None
    try:
        root = _project_root(slug)
        if root is None:
            return
        clear_cancel(root)
        acquire_run_lock(root, slug=slug)
        ctx = load_project(root)
        setup_logging(project_root=ctx.root)
        settings = load_settings()
        pipe = Pipeline(ctx, settings)
        stage = _normalize_stage_id(stage)

        for path in _stage_output_paths(root, stage):
            path.unlink(missing_ok=True)

        from novelscript.pipeline.stage_deps import invalidate_downstream

        invalidate_downstream(ctx, stage)

        _ensure_web_stage_prereqs(pipe, ctx, stage)

        from novelscript.pipeline.cancel import PipelineCancelled, check_cancelled

        if stage == "P0":
            check_cancelled(root)
            run_p0_preference(ctx, settings, skip_llm=skip_llm)
        elif stage == "stage0":
            check_cancelled(root)
            run_stage0_upstream(ctx, settings)
        elif stage == "P1":
            check_cancelled(root)
            run_p1_source_cards(ctx, settings, skip_llm=skip_llm)
        elif stage == "S0":
            check_cancelled(root)
            require_source_context(ctx)
            run_s0_engine(ctx, settings)
        elif stage == "brief":
            check_cancelled(root)
            require_source_context(ctx)
            run_adaptation_brief(ctx, settings)
        elif stage == "P3":
            check_cancelled(root)
            run_p3_strategy(ctx, settings, skip_llm=skip_llm)
            pipe._rebuild_must_keep_index()
        elif stage == "S1":
            check_cancelled(root)
            run_s1_premise(ctx, settings)
            run_s1_bible(ctx, settings)
        elif stage == "S2":
            check_cancelled(root)
            run_s2_season_map(ctx, settings)
        elif stage == "S3":
            seasons = pipe._load_seasons()
            with ThreadPoolExecutor(max_workers=ctx.max_workers) as pool:
                futures = [pool.submit(run_s3_episodes, ctx, s, settings) for s in seasons]
                for fut in as_completed(futures):
                    check_cancelled(root)
                    fut.result()
            pipe._update_must_keep_after_s3()
        elif stage in ("S4", "S5"):
            eps = pipe._episodes_for_s4_s5("S1")
            with ThreadPoolExecutor(max_workers=ctx.max_workers) as pool:
                if stage == "S4":
                    futures = {
                        pool.submit(run_s4_beats, ctx, ep.split("E")[0], int(ep.split("E")[-1]), settings): ep
                        for ep in eps
                    }
                else:
                    futures = {
                        pool.submit(run_s5_script, ctx, ep.split("E")[0], int(ep.split("E")[-1]), settings): ep
                        for ep in eps
                    }
                for fut in as_completed(futures):
                    check_cancelled(root)
                    fut.result()
            if stage == "S5":
                for ep in (1, 2, 3):
                    script_path = ctx.episode_dir("S1", ep) / "script.json"
                    if script_path.exists():
                        pipe._update_must_keep_after_s5(json.loads(script_path.read_text(encoding="utf-8")))
        elif stage == "P6":
            check_cancelled(root)
            run_p6_pilot_review(ctx, settings, skip_llm=skip_llm)
    except PipelineCancelled:
        import logging

        from novelscript.progress import emit

        if root is not None:
            setup_logging(project_root=root)
            emit("⏹ 用户已中断精编")
        logging.getLogger("novelscript.web").info("Stage run cancelled for %s", slug)
    finally:
        if root is not None:
            release_run_lock(root)
        with _run_lock:
            _running.discard(slug)


class PortalHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(WEB_DIR), **kwargs)

    def end_headers(self) -> None:
        path = urlparse(self.path).path
        if path.endswith((".html", ".js", ".css")):
            self.send_header("Cache-Control", "no-cache, must-revalidate")
        super().end_headers()

    def log_message(self, fmt: str, *args) -> None:
        if str(args[0]).startswith("GET /api/"):
            return
        super().log_message(fmt, *args)

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path

        if path == "/api/health":
            return _json_response(
                self,
                HTTPStatus.OK,
                {"ok": True, "build": PORTAL_BUILD, "projectsDir": str(PROJECTS_DIR)},
            )

        if path == "/api/projects":
            manifest_mod = _manifest_api()
            items = manifest_mod.list_projects(PROJECTS_DIR)
            for item in items:
                slug = item["slug"]
                root = _project_root(slug)
                if _project_is_running(slug, root):
                    if root is not None:
                        _enrich_running_item(item, slug, root, manifest_mod)
                else:
                    item["running"] = False
            return _json_response(self, HTTPStatus.OK, items)

        m = re.fullmatch(r"/api/projects/([a-z0-9-]+)/manifest", path)
        if m:
            root = _project_root(m.group(1))
            if root is None:
                return _json_response(self, HTTPStatus.NOT_FOUND, {"error": "project not found"})
            return _json_response(self, HTTPStatus.OK, _manifest_api().build_manifest(root))

        m = re.fullmatch(r"/api/projects/([a-z0-9-]+)/status", path)
        if m:
            root = _project_root(m.group(1))
            if root is None:
                return _json_response(self, HTTPStatus.NOT_FOUND, {"error": "project not found"})
            status = _manifest_api().pipeline_status(root)
            slug = m.group(1)
            status["running"] = _project_is_running(slug, root)
            return _json_response(self, HTTPStatus.OK, status)

        m = re.fullmatch(r"/api/projects/([a-z0-9-]+)/doc", path)
        if m:
            root = _project_root(m.group(1))
            if root is None:
                return _json_response(self, HTTPStatus.NOT_FOUND, {"error": "project not found"})
            qs = parse_qs(parsed.query)
            rel = unquote(qs.get("file", [""])[0])
            if not rel or ".." in rel.replace("\\", "/"):
                return _json_response(self, HTTPStatus.BAD_REQUEST, {"error": "invalid file"})
            doc_path = (root / rel).resolve()
            if root.resolve() not in doc_path.parents and doc_path != root.resolve():
                return _json_response(self, HTTPStatus.BAD_REQUEST, {"error": "invalid file"})
            if not doc_path.is_file() or doc_path.suffix.lower() not in {".md", ".txt", ".json"}:
                return _json_response(self, HTTPStatus.NOT_FOUND, {"error": "file not found"})
            body = doc_path.read_bytes()
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return

        if path == "/project.html":
            qs = parse_qs(parsed.query)
            if qs.get("slug"):
                return super().do_GET()

        return super().do_GET()

    def do_DELETE(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path

        m = re.fullmatch(r"/api/projects/([a-z0-9-]+)", path)
        if m:
            result = _delete_project(m.group(1))
            if result.get("error") == "project not found":
                return _json_response(self, HTTPStatus.NOT_FOUND, result)
            if result.get("error"):
                return _json_response(self, HTTPStatus.CONFLICT, result)
            return _json_response(self, HTTPStatus.OK, result)

        return _json_response(self, HTTPStatus.NOT_FOUND, {"error": "not found"})

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path

        if path == "/api/projects":
            return self._handle_create_project()

        m = re.fullmatch(r"/api/projects/([a-z0-9-]+)/approve", path)
        if m:
            slug = m.group(1)
            if _project_root(slug) is None:
                return _json_response(self, HTTPStatus.NOT_FOUND, {"error": "project not found"})
            body = _read_json_body(self)
            gate = str(body.get("gate", "")).strip()
            if not gate:
                return _json_response(self, HTTPStatus.BAD_REQUEST, {"error": "gate is required"})
            resume = bool(body.get("resume", True))
            resume_only = bool(body.get("resumeOnly", False))
            if slug in _running:
                return _json_response(self, HTTPStatus.CONFLICT, {"error": "pipeline already running"})
            result = _approve_gate(slug, gate, resume=resume, resume_only=resume_only)
            if result.get("error"):
                return _json_response(self, HTTPStatus.BAD_REQUEST, result)
            return _json_response(self, HTTPStatus.OK, result)

        m = re.fullmatch(r"/api/projects/([a-z0-9-]+)/decisions/([a-z0-9_-]+)/resolve", path)
        if m:
            slug, decision_id = m.group(1), m.group(2)
            root = _project_root(slug)
            if root is None:
                return _json_response(self, HTTPStatus.NOT_FOUND, {"error": "project not found"})
            body = _read_json_body(self)
            choice = str(body.get("choice", "")).strip()
            if not choice:
                return _json_response(self, HTTPStatus.BAD_REQUEST, {"error": "choice is required"})
            from novelscript.audit.decision_log import resolve_decision

            resolved = resolve_decision(
                root / "audit",
                decision_id,
                choice=choice,
                note=str(body.get("note", "")),
            )
            if resolved is None:
                return _json_response(self, HTTPStatus.NOT_FOUND, {"error": "decision not found"})
            return _json_response(self, HTTPStatus.OK, {"status": "resolved", "decision": resolved})

        m = re.fullmatch(r"/api/projects/([a-z0-9-]+)/cancel", path)
        if m:
            slug = m.group(1)
            result = _cancel_pipeline(slug)
            if result.get("error"):
                return _json_response(self, HTTPStatus.NOT_FOUND, result)
            return _json_response(self, HTTPStatus.OK, result)

        m = re.fullmatch(r"/api/projects/([a-z0-9-]+)/run", path)
        if m:
            slug = m.group(1)
            if _project_root(slug) is None:
                return _json_response(self, HTTPStatus.NOT_FOUND, {"error": "project not found"})
            body = _read_json_body(self)
            through = body.get("through")
            if through is not None:
                through = str(through)
            from_stage = body.get("from_stage")
            if from_stage is not None:
                from_stage = str(from_stage)
            skip_llm = bool(body.get("skip_llm", False))
            threading.Thread(
                target=_run_pipeline,
                args=(slug,),
                kwargs={"through": through or "S5", "from_stage": from_stage, "skip_llm": skip_llm},
                daemon=True,
            ).start()
            return _json_response(self, HTTPStatus.ACCEPTED, {"status": "started", "slug": slug})

        m = re.fullmatch(r"/api/projects/([a-z0-9-]+)/run/stage", path)
        if m:
            slug = m.group(1)
            if _project_root(slug) is None:
                return _json_response(self, HTTPStatus.NOT_FOUND, {"error": "project not found"})
            body = _read_json_body(self)
            stage = _normalize_stage_id(str(body.get("stage", "")))
            runnable = _manifest_api().RUNNABLE_STAGE_IDS
            if stage not in runnable:
                return _json_response(self, HTTPStatus.BAD_REQUEST, {"error": "invalid stage"})
            skip_llm = bool(body.get("skip_llm", False))
            threading.Thread(
                target=_run_stage,
                args=(slug, stage),
                kwargs={"skip_llm": skip_llm},
                daemon=True,
            ).start()
            return _json_response(self, HTTPStatus.ACCEPTED, {"status": "started", "slug": slug, "stage": stage})

        m = re.fullmatch(r"/api/projects/([a-z0-9-]+)/index", path)
        if m:
            slug = m.group(1)
            root = _project_root(slug)
            if root is None:
                return _json_response(self, HTTPStatus.NOT_FOUND, {"error": "project not found"})
            ctx = load_project(root)
            setup_logging(project_root=ctx.root)
            result = Pipeline(ctx, load_settings())._run_index()
            return _json_response(self, HTTPStatus.OK, result)

        return _json_response(self, HTTPStatus.NOT_FOUND, {"error": "not found"})

    def _handle_create_project(self) -> None:
        content_type = self.headers.get("Content-Type", "")
        if "multipart/form-data" not in content_type:
            return _json_response(self, HTTPStatus.BAD_REQUEST, {"error": "multipart form required"})

        length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(length)
        fields = _parse_multipart(raw, content_type)

        if "file" not in fields:
            return _json_response(self, HTTPStatus.BAD_REQUEST, {"error": "file is required"})

        filename, content = fields["file"]
        filename = filename or "novel.txt"
        if not filename.lower().endswith((".txt", ".text")):
            return _json_response(self, HTTPStatus.BAD_REQUEST, {"error": "only .txt novels supported"})

        if len(content) < 100:
            return _json_response(self, HTTPStatus.BAD_REQUEST, {"error": "file too small"})
        if len(content) > 50 * 1024 * 1024:
            return _json_response(self, HTTPStatus.BAD_REQUEST, {"error": "file exceeds 50MB"})

        title_field = fields.get("title", (None, b""))[1]
        mode_field = fields.get("mode", (None, b"M1"))[1]
        pilot_test_field = fields.get("pilot_test", (None, b""))[1]
        display_title = title_field.decode("utf-8", errors="replace").strip()
        mode = mode_field.decode("utf-8", errors="replace").strip() or "M1"
        pilot_test = pilot_test_field.decode("utf-8", errors="replace").strip().lower() in ("1", "true", "yes", "on")

        try:
            result = _create_project(
                filename,
                content,
                display_title=display_title,
                mode=mode,
                pilot_test=pilot_test,
            )
        except Exception as exc:
            return _json_response(self, HTTPStatus.INTERNAL_SERVER_ERROR, {"error": str(exc)})

        return _json_response(self, HTTPStatus.CREATED, result)


def run_server(port: int = 8765) -> None:
    PROJECTS_DIR.mkdir(parents=True, exist_ok=True)
    server = ThreadingHTTPServer(("127.0.0.1", port), PortalHandler)
    server.allow_reuse_address = True
    print(f"NovelScript Web Portal: http://127.0.0.1:{port}/  (build {PORTAL_BUILD})")
    print(f"Projects directory: {PROJECTS_DIR}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8765
    run_server(port)

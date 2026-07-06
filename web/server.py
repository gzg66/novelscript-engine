from __future__ import annotations

import json
import re
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
PORTAL_BUILD = "20260706e"

if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from novelscript.config import load_settings  # noqa: E402
from novelscript.logging import setup_logging  # noqa: E402
from novelscript.pipeline.context import init_project, load_project  # noqa: E402
from novelscript.pipeline.orchestrator import Pipeline  # noqa: E402

_running: set[str] = set()
_run_lock = threading.Lock()


def _manifest_api():
    """Reload manifest on each API call so code edits apply without server restart."""
    import importlib

    import novelscript.web.manifest as manifest_mod

    return importlib.reload(manifest_mod)


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


def _create_project(upload_name: str, content: bytes, *, display_title: str = "", mode: str = "M1") -> dict:
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


def _run_pipeline(slug: str, *, through: str | None = "S5", from_stage: str | None = None, skip_llm: bool = False) -> None:
    import logging

    web_log = logging.getLogger("novelscript.web")

    with _run_lock:
        if slug in _running:
            return
        _running.add(slug)

    try:
        root = _project_root(slug)
        if root is None:
            return
        ctx = load_project(root)
        setup_logging(project_root=ctx.root)
        settings = load_settings()
        pipe = Pipeline(ctx, settings)
        result = pipe.run(
            through=through or "S5",
            from_stage=from_stage,
            skip_llm=skip_llm,
            auto_approve=False,
        )
        if result.get("blocked"):
            web_log.warning("Pipeline blocked for %s: %s", slug, result["blocked"])
    except Exception as exc:
        web_log.exception("Pipeline failed for %s: %s", slug, exc)
    finally:
        with _run_lock:
            _running.discard(slug)


def _approve_gate(slug: str, gate: str, *, resume: bool = True) -> dict:
    manifest_mod = _manifest_api()
    GATE_RESUME_FROM = manifest_mod.GATE_RESUME_FROM

    root = _project_root(slug)
    if root is None:
        return {"error": "project not found"}
    if gate not in GATE_RESUME_FROM:
        return {"error": "invalid gate"}

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
    stage = stage.upper()
    paths: list[Path] = []
    if stage == "S0":
        paths.extend([root / "S0_story_engine.md"])
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


def _run_stage(slug: str, stage: str, *, skip_llm: bool = False) -> None:
    from concurrent.futures import ThreadPoolExecutor, as_completed

    from novelscript.stages import (
        run_s0_engine,
        run_s1_bible,
        run_s1_premise,
        run_s2_season_map,
        run_s3_episodes,
        run_s4_beats,
        run_s5_script,
    )
    from novelscript.stages.source import ensure_source_context

    with _run_lock:
        if slug in _running:
            return
        _running.add(slug)

    try:
        root = _project_root(slug)
        if root is None:
            return
        ctx = load_project(root)
        setup_logging(project_root=ctx.root)
        settings = load_settings()
        pipe = Pipeline(ctx, settings)
        stage = stage.upper()

        for path in _stage_output_paths(root, stage):
            path.unlink(missing_ok=True)

        if stage == "S0":
            ensure_source_context(ctx, settings, skip_llm=skip_llm)
            run_s0_engine(ctx, settings)
        elif stage == "S1":
            run_s1_premise(ctx, settings)
            run_s1_bible(ctx, settings)
        elif stage == "S2":
            run_s2_season_map(ctx, settings)
        elif stage == "S3":
            seasons = pipe._load_seasons()
            with ThreadPoolExecutor(max_workers=ctx.max_workers) as pool:
                futures = [pool.submit(run_s3_episodes, ctx, s, settings) for s in seasons]
                for fut in as_completed(futures):
                    fut.result()
            pipe._update_must_keep_after_s3()
        elif stage in ("S4", "S5"):
            pilot_only = not ctx.is_approved("s1_pilot")
            eps = pipe._pilot_episodes() if pilot_only else pipe._all_episodes("S1")
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
                    fut.result()
            if stage == "S5":
                for ep in (1, 2, 3):
                    script_path = ctx.episode_dir("S1", ep) / "script.json"
                    if script_path.exists():
                        pipe._update_must_keep_after_s5(json.loads(script_path.read_text(encoding="utf-8")))
    finally:
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
                if slug in _running:
                    item["running"] = True
                    root = _project_root(slug)
                    if root is not None:
                        st = manifest_mod.pipeline_status(root)
                        item["phase"] = st.get("phase", "index")
                        item["message"] = st.get("message", "精编运行中…")
                        item["progress"] = st.get("progress", 0)
                else:
                    item.setdefault("running", False)
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
            status["running"] = status["running"] or m.group(1) in _running
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
            if slug in _running:
                return _json_response(self, HTTPStatus.CONFLICT, {"error": "pipeline already running"})
            result = _approve_gate(slug, gate, resume=resume)
            if result.get("error"):
                return _json_response(self, HTTPStatus.BAD_REQUEST, result)
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
            stage = str(body.get("stage", "")).upper()
            if stage not in {"S0", "S1", "S2", "S3", "S4", "S5"}:
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
        display_title = title_field.decode("utf-8", errors="replace").strip()
        mode = mode_field.decode("utf-8", errors="replace").strip() or "M1"

        try:
            result = _create_project(filename, content, display_title=display_title, mode=mode)
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

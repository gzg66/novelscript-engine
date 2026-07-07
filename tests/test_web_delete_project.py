from __future__ import annotations

import importlib.util
import json
import sys
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

WEB_DIR = Path(__file__).resolve().parents[1] / "web"
SPEC = importlib.util.spec_from_file_location("web_server", WEB_DIR / "server.py")
assert SPEC and SPEC.loader
web_server = importlib.util.module_from_spec(SPEC)
sys.modules["web_server"] = web_server
SPEC.loader.exec_module(web_server)


def _make_project(projects_dir: Path, slug: str) -> Path:
    root = projects_dir / slug
    root.mkdir(parents=True)
    (root / "input").mkdir()
    (root / "index").mkdir()
    (root / "runs").mkdir()
    (root / "input" / "novel.txt").write_text("x" * 200, encoding="utf-8")
    (root / "project.meta.json").write_text(
        json.dumps({"mode": "M1", "display_title": f"Title {slug}"}, ensure_ascii=False),
        encoding="utf-8",
    )
    return root


@pytest.fixture
def projects_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    root = tmp_path / "projects"
    root.mkdir()
    monkeypatch.setattr(web_server, "PROJECTS_DIR", root)
    return root


@pytest.fixture
def api_server(projects_dir: Path):
    server = ThreadingHTTPServer(("127.0.0.1", 0), web_server.PortalHandler)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{port}"
    try:
        yield base
    finally:
        server.shutdown()
        thread.join(timeout=2)


def test_pipeline_skip_llm_no_import_error(api_server: str, projects_dir: Path) -> None:
    slug = "import-fix"
    root = projects_dir / slug
    root.mkdir(parents=True)
    (root / "input").mkdir()
    (root / "index").mkdir()
    (root / "input" / "novel.txt").write_text("Chapter 1\n\nFreya wakes.\n", encoding="utf-8")
    (root / "project.meta.json").write_text(
        json.dumps({"mode": "M1", "display_title": "Import Fix"}, ensure_ascii=False),
        encoding="utf-8",
    )

    req = urllib.request.Request(
        f"{api_server}/api/projects/{slug}/run",
        data=json.dumps({"through": "S1", "skip_llm": True}).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req) as resp:
        assert resp.status == 202

    import time

    for _ in range(40):
        time.sleep(0.25)
        status_req = urllib.request.Request(f"{api_server}/api/projects/{slug}/status")
        with urllib.request.urlopen(status_req) as resp:
            status = json.loads(resp.read().decode("utf-8"))
        if not status.get("running"):
            break
    else:
        pytest.fail("pipeline did not finish")

    log_path = root / "pipeline.log"
    log_text = log_path.read_text(encoding="utf-8") if log_path.exists() else ""
    assert "ImportError" not in log_text
    assert "cannot import name 'persist_stage0_hash'" not in log_text
    assert (root / "input" / "stage0" / "outline.md").exists()
    assert (root / "project.meta.json").read_text(encoding="utf-8").find("stage0_novel_hash") >= 0


def _delete_request(base: str, path: str) -> tuple[int, dict]:
    req = urllib.request.Request(f"{base}{path}", method="DELETE")
    try:
        with urllib.request.urlopen(req) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8")
        return exc.code, json.loads(body) if body else {}


def _list_slugs(base: str) -> list[str]:
    with urllib.request.urlopen(f"{base}/api/projects") as resp:
        items = json.loads(resp.read().decode("utf-8"))
    return [item["slug"] for item in items]


def test_delete_project_removes_directory(projects_dir: Path) -> None:
    slug = "demo-delete"
    root = _make_project(projects_dir, slug)
    assert root.is_dir()

    result = web_server._delete_project(slug)
    assert result == {"ok": True, "slug": slug}
    assert not root.exists()


def test_delete_project_not_found(projects_dir: Path) -> None:
    result = web_server._delete_project("missing-project")
    assert result == {"error": "project not found"}


def test_delete_project_rejects_running(projects_dir: Path) -> None:
    slug = "running-one"
    root = _make_project(projects_dir, slug)
    with web_server._run_lock:
        web_server._running.add(slug)

    result = web_server._delete_project(slug)
    assert result["error"] == "项目正在精编，请先停止后再删除"
    assert root.is_dir()

    with web_server._run_lock:
        web_server._running.discard(slug)


def test_delete_api_success(projects_dir: Path, api_server: str) -> None:
    slug = "api-delete"
    _make_project(projects_dir, slug)

    status, body = _delete_request(api_server, f"/api/projects/{slug}")

    assert status == 200
    assert body == {"ok": True, "slug": slug}
    assert not (projects_dir / slug).exists()
    assert slug not in _list_slugs(api_server)


def test_delete_api_not_found(projects_dir: Path, api_server: str) -> None:
    status, body = _delete_request(api_server, "/api/projects/missing-slug")

    assert status == 404
    assert body == {"error": "project not found"}


def test_delete_api_invalid_slug_returns_not_found(projects_dir: Path, api_server: str) -> None:
    status, body = _delete_request(api_server, "/api/projects/-bad-slug")

    assert status == 404
    assert body == {"error": "project not found"}


def test_delete_api_running_returns_conflict(projects_dir: Path, api_server: str) -> None:
    slug = "api-running"
    _make_project(projects_dir, slug)
    with web_server._run_lock:
        web_server._running.add(slug)

    try:
        status, body = _delete_request(api_server, f"/api/projects/{slug}")

        assert status == 409
        assert body["error"] == "项目正在精编，请先停止后再删除"
        assert (projects_dir / slug).exists()
    finally:
        with web_server._run_lock:
            web_server._running.discard(slug)


def test_list_projects_excludes_deleted(projects_dir: Path) -> None:
    from novelscript.web.manifest import list_projects

    slug = "listed-then-deleted"
    _make_project(projects_dir, slug)
    assert any(p["slug"] == slug for p in list_projects(projects_dir))

    web_server._delete_project(slug)
    assert not any(p["slug"] == slug for p in list_projects(projects_dir))

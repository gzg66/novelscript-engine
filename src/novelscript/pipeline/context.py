from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


def slug_from_novel(novel_path: Path) -> str:
    if novel_path.name == "novel.txt" and novel_path.parent.name == "input":
        return novel_path.parent.parent.name
    stem = novel_path.stem.lower()
    slug = re.sub(r"[^a-z0-9]+", "-", stem).strip("-")
    return slug or "novel"


def project_root_for_novel(novel_path: Path, *, projects_base: Path | None = None) -> Path:
    from novelscript.config import PROJECT_ROOT

    base = projects_base or PROJECT_ROOT / "projects"
    return base / slug_from_novel(novel_path)


def ensure_project(novel_path: Path, *, project_root: Path | None = None, mode: str = "M1") -> ProjectContext:
    from novelscript.io.atomic import write_json

    root = project_root or project_root_for_novel(novel_path)
    meta_path = root / "project.meta.json"
    if not meta_path.exists():
        if (root / "input" / "novel.txt").exists():
            write_json(
                meta_path,
                {
                    "mode": mode,
                    "rights_basis": "authorized",
                    "episode_id_strategy": "dual_index",
                    "museframe_schema": "museframe_scene.v1.json",
                    "source_novel": str(novel_path.resolve()),
                },
            )
            return load_project(root)
        stage0_src = novel_path.parent / "stage0"
        init_project(
            root,
            novel_src=novel_path,
            mode=mode,
            stage0_src=stage0_src if stage0_src.is_dir() else None,
        )
    return load_project(root)


@dataclass
class ProjectContext:
    root: Path
    mode: str = "M1"
    rights_basis: str = "authorized"
    max_workers: int = 4
    max_attempts: int = 3
    meta: dict[str, Any] = field(default_factory=dict)

    @property
    def input_dir(self) -> Path:
        return self.root / "input"

    @property
    def index_dir(self) -> Path:
        return self.root / "index"

    @property
    def approved_dir(self) -> Path:
        return self.root / "approved"

    @property
    def audit_dir(self) -> Path:
        return self.root / "audit"

    @property
    def runs_dir(self) -> Path:
        return self.root / ".runs"

    def novel_path(self) -> Path:
        return self.input_dir / "novel.txt"

    def brief_path(self) -> Path:
        return self.input_dir / "adaptation_brief.yaml"

    def is_approved(self, gate: str) -> bool:
        return (self.approved_dir / f"{gate}.approved").exists()

    def season_dir(self, season_id: str) -> Path:
        num = season_id.lstrip("S").lstrip("s")
        return self.root / "seasons" / f"s{num}"

    def episode_dir(self, season_id: str, ep_num: int) -> Path:
        return self.season_dir(season_id) / f"ep{ep_num:02d}"


def load_project(root: Path) -> ProjectContext:
    import json

    meta_path = root / "project.meta.json"
    meta: dict[str, Any] = {}
    if meta_path.exists():
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
    return ProjectContext(
        root=root,
        mode=meta.get("mode", "M1"),
        rights_basis=meta.get("rights_basis", "authorized"),
        max_workers=int(meta.get("max_workers", 4)),
        meta=meta,
    )


def init_project(
    root: Path,
    *,
    novel_src: Path,
    mode: str = "M1",
    rights_basis: str = "authorized",
    stage0_src: Path | None = None,
) -> ProjectContext:
    from novelscript.io.atomic import ensure_dir, write_json

    ensure_dir(root / "input" / "stage0")
    ensure_dir(root / "index")
    ensure_dir(root / "approved")
    ensure_dir(root / "audit")
    ensure_dir(root / ".runs")

    novel_dst = root / "input" / "novel.txt"
    if novel_src.resolve() != novel_dst.resolve():
        novel_dst.write_text(novel_src.read_text(encoding="utf-8"), encoding="utf-8")

    if stage0_src and stage0_src.exists():
        import shutil

        for item in stage0_src.iterdir():
            dst = root / "input" / "stage0" / item.name
            if item.is_file():
                shutil.copy2(item, dst)

    write_json(
        root / "project.meta.json",
        {
            "mode": mode,
            "rights_basis": rights_basis,
            "episode_id_strategy": "dual_index",
            "museframe_schema": "museframe_scene.v1.json",
            "source_novel": str(novel_src.resolve()),
        },
    )
    return load_project(root)

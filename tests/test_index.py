from __future__ import annotations

from pathlib import Path

import pytest

from novelscript.config import PROJECT_ROOT
from novelscript.index.chapters import index_novel, split_chapters


@pytest.fixture
def novel_text() -> str:
    return (PROJECT_ROOT / "input" / "novel.txt").read_text(encoding="utf-8")


def test_split_chapters_count(novel_text: str) -> None:
    chapters = split_chapters(novel_text)
    assert len(chapters) == 132
    assert chapters[0].number == 1
    assert chapters[-1].number >= 130


def test_index_novel(tmp_path: Path, novel_text: str) -> None:
    novel = tmp_path / "novel.txt"
    novel.write_text(novel_text, encoding="utf-8")
    result = index_novel(novel, tmp_path / "index")
    assert result["total_chapters"] == 132
    assert (tmp_path / "index" / "chapters.json").exists()
    assert (tmp_path / "index" / "source_lines.jsonl").exists()

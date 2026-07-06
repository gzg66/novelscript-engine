from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from novelscript.io.atomic import write_json


CHAPTER_RE = re.compile(r"^Chapter\s+(\d+)\s*$", re.MULTILINE | re.IGNORECASE)


@dataclass(frozen=True)
class Chapter:
    number: int
    title: str
    start_line: int
    end_line: int
    text: str


def split_chapters(novel_text: str) -> list[Chapter]:
    matches = list(CHAPTER_RE.finditer(novel_text))
    if not matches:
        raise ValueError("No chapters found in novel text (expected 'Chapter N' headers)")

    chapters: list[Chapter] = []
    seen: set[int] = set()
    lines = novel_text.splitlines(keepends=True)
    line_offsets: list[int] = []
    offset = 0
    for line in lines:
        line_offsets.append(offset)
        offset += len(line)

    for i, match in enumerate(matches):
        ch_num = int(match.group(1))
        if ch_num in seen:
            continue
        seen.add(ch_num)
        start = match.start()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(novel_text)
        chunk = novel_text[start:end].strip()
        start_line = novel_text[:start].count("\n") + 1
        end_line = novel_text[:end].count("\n")
        title_line = chunk.splitlines()[0] if chunk else f"Chapter {ch_num}"
        chapters.append(
            Chapter(
                number=ch_num,
                title=title_line.strip(),
                start_line=start_line,
                end_line=end_line,
                text=chunk,
            )
        )
    return chapters


def build_chapters_index(chapters: list[Chapter]) -> list[dict[str, Any]]:
    return [
        {
            "number": ch.number,
            "title": ch.title,
            "start_line": ch.start_line,
            "end_line": ch.end_line,
            "char_count": len(ch.text),
        }
        for ch in chapters
    ]


def total_chapter_count(chapters: list[Chapter]) -> int:
    return max((ch.number for ch in chapters), default=0)


def build_source_lines(novel_text: str, chapters: list[Chapter]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for ch in chapters:
        for line_no in range(ch.start_line, ch.end_line + 1):
            records.append({"chapter": ch.number, "line": line_no})
    return records


def index_novel(novel_path: Path, index_dir: Path) -> dict[str, Any]:
    text = novel_path.read_text(encoding="utf-8")
    chapters = split_chapters(text)
    index_dir.mkdir(parents=True, exist_ok=True)

    chapters_data = build_chapters_index(chapters)
    total = total_chapter_count(chapters)
    write_json(index_dir / "chapters.json", {"chapters": chapters_data, "total": total})

    source_lines = build_source_lines(text, chapters)
    source_path = index_dir / "source_lines.jsonl"
    with source_path.open("w", encoding="utf-8") as f:
        for rec in source_lines:
            f.write(f'{{"chapter": {rec["chapter"]}, "line": {rec["line"]}}}\n')

    return {"chapters": chapters_data, "total_chapters": total}

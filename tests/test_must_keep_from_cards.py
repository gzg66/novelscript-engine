from __future__ import annotations

from novelscript.index.must_keep import (
    build_must_keep_from_cards,
    parse_must_keep_from_story_engine,
    parse_rulings_from_story_engine,
    parse_strategy_must_keep_revisions,
)


def test_build_must_keep_from_cards_keeps_ruled_mk() -> None:
    cards = {
        "must_keep": [
            {"id": "mk_001", "title": "献丝带", "source_ref": "Ch7", "why_irreducible": "双男主张力"},
            {"id": "mk_002", "title": "分院", "source_ref": "Ch30", "why_irreducible": "逆袭节点"},
            {"id": "mk_003", "title": "删掉的", "source_ref": "Ch99", "why_irreducible": "x"},
        ]
    }
    rulings = {
        "mk_001": {"verdict": "保留", "reason": "核心", "engine": "引擎2"},
        "mk_002": {"verdict": "合并→mk_001", "reason": "可合并", "engine": "引擎1"},
        "mk_003": {"verdict": "删除", "reason": "冗余", "engine": "—"},
    }
    scenes = build_must_keep_from_cards(cards, rulings)
    assert len(scenes) == 2
    assert scenes[0]["card_id"] == "mk_001"
    assert scenes[0]["engines"] == ["引擎2"]
    assert scenes[1]["card_id"] == "mk_002"


def test_strategy_revision_drops_mk() -> None:
    cards = {"must_keep": [{"id": "mk_001", "title": "A", "source_ref": "Ch1", "why_irreducible": "x"}]}
    rulings = {"mk_001": {"verdict": "保留", "reason": "r", "engine": "引擎1"}}
    scenes = build_must_keep_from_cards(cards, rulings, strategy_revisions={"mk_001": "降级"})
    assert scenes == []


def test_parse_rulings_from_engine() -> None:
    md = """## 素材裁决表
| card_id | 裁决 | 理由 | 服务引擎 |
|---|---|---|---|
| mk_001 | 保留 | 核心 | 引擎1 |
| red_003 | 删除 | 重复 | — |
"""
    rulings = parse_rulings_from_story_engine(md)
    assert rulings["mk_001"]["verdict"] == "保留"
    assert rulings["red_003"]["verdict"] == "删除"


def test_parse_strategy_revisions() -> None:
    md = """## 策略修订
| card_id | 修订 | 理由 |
|---|---|---|
| mk_007 | 升保 | 粉丝向 |
"""
    rev = parse_strategy_must_keep_revisions(md)
    assert rev["mk_007"] == "升保"


def test_legacy_parse_must_keep_from_story_engine() -> None:
    md = """## 名场面必保清单
| # | 名场面 | 原著位置 | 为什么不能压缩 |
|---|---|---|---|
| 1 | 献丝带 | Ch7 | 双男主 |
"""
    scenes = parse_must_keep_from_story_engine(md)
    assert len(scenes) == 1
    assert scenes[0]["name"] == "献丝带"
    assert scenes[0]["card_id"] == "mk_001"

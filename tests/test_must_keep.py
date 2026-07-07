from novelscript.index.must_keep import _parse_chapter_refs


def test_parse_chapter_range() -> None:
    assert _parse_chapter_refs("Ch 1-10") == list(range(1, 11))
    assert _parse_chapter_refs("Ch 41-50") == list(range(41, 51))
    assert _parse_chapter_refs("Ch 11") == [11]

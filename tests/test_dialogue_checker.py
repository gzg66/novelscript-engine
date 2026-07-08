from __future__ import annotations

from novelscript.checkers.dialogue import (
    check_english_dialogue,
    check_narrative_clarity,
    contains_cjk,
)


def test_contains_cjk() -> None:
    assert contains_cjk("女主")
    assert not contains_cjk('Freya: "Hello"')


def test_english_dialogue_rejects_chinese() -> None:
    beats = [{"beat_id": 1, "dialogue": '女主（内心）："test"', "sound": ""}]
    report = check_english_dialogue(beats)
    assert not report.passed
    assert report.issues


def test_english_dialogue_accepts_vo() -> None:
    beats = [{"beat_id": 1, "dialogue": 'Freya (V.O.): "I can do this!"', "sound": "SFX: splash"}]
    report = check_english_dialogue(beats)
    assert report.passed, report.issues


def test_narrative_clarity_flags_ring_without_setup() -> None:
    beats = [
        {"beat_id": 1, "dialogue": 'Eliza: "Did you find the ring?"', "action": "runs in"},
    ]
    report = check_narrative_clarity(beats)
    assert not report.passed
    assert any("ring" in i for i in report.issues)


def test_narrative_clarity_allows_deferred_in_notes() -> None:
    beats = [
        {"beat_id": 1, "dialogue": 'Eliza: "Did you find the ring?"', "action": "runs in"},
    ]
    notes = [{"source_ref": "Ch1 ring", "action": "adapt:defer → EP02", "dramatic_reason": "ring task deferred"}]
    report = check_narrative_clarity(beats, adaptation_notes=notes)
    assert report.passed, report.issues

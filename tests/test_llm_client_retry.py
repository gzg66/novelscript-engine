from __future__ import annotations

import httpx
import pytest

from novelscript.config import load_settings
from novelscript.llm.client import LLMClient, _is_transient_llm_error


def test_is_transient_llm_error_detects_connect_error() -> None:
    assert _is_transient_llm_error(httpx.ConnectError("EOF occurred in violation of protocol"))


def test_is_transient_llm_error_detects_marker_text() -> None:
    assert _is_transient_llm_error(RuntimeError("[SSL: UNEXPECTED_EOF_WHILE_READING] EOF occurred"))


def test_is_transient_llm_error_rejects_validation_error() -> None:
    assert not _is_transient_llm_error(ValueError("bad output"))


def test_generate_text_retries_transient_disconnect(monkeypatch) -> None:
    settings = load_settings()
    client = LLMClient(settings)
    calls = {"n": 0}

    class FakeAdapter:
        def stream_text(self, *, system: str, messages: list) -> list[str]:
            calls["n"] += 1
            if calls["n"] == 1:
                raise httpx.ConnectError("EOF occurred in violation of protocol")
            yield "ok"

    monkeypatch.setattr(client, "_ensure_adapter", lambda: FakeAdapter())
    monkeypatch.setattr("novelscript.llm.client.time.sleep", lambda _s: None)

    text = client.generate_text(system="s", user="u", stream=False)
    assert text == "ok"
    assert calls["n"] == 2


def test_generate_text_does_not_retry_non_transient(monkeypatch) -> None:
    settings = load_settings()
    client = LLMClient(settings)

    class FakeAdapter:
        def stream_text(self, *, system: str, messages: list) -> list[str]:
            raise ValueError("checker failed")
            yield ""

    monkeypatch.setattr(client, "_ensure_adapter", lambda: FakeAdapter())

    with pytest.raises(ValueError, match="checker failed"):
        client.generate_text(system="s", user="u", stream=False)

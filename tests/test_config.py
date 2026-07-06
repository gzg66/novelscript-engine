from __future__ import annotations

import os

import pytest

from novelscript.config import MUSEFRAME_ROOT, PROJECT_ROOT, load_settings
from novelscript.llm.client import LLMClient


@pytest.mark.integration
def test_llm_ping() -> None:
    museframe_env = MUSEFRAME_ROOT / ".env"
    if not museframe_env.exists():
        pytest.skip("museframe .env not found")
    settings = load_settings(dotenv_path=museframe_env)
    assert settings.support_api.token
    client = LLMClient(settings, llm_config=settings.conversion_llm)
    reply = client.generate_text(system="Reply with exactly: ok", user="ping", stream=False)
    assert reply.strip()


def test_load_settings_with_museframe_env() -> None:
    museframe_env = MUSEFRAME_ROOT / ".env"
    if not museframe_env.exists():
        return
    settings = load_settings(dotenv_path=museframe_env)
    assert settings.support_api.token == "dev-internal-token"
    assert settings.llm_core_path.exists()
    assert settings.llm_core_path.name == "llm_core"

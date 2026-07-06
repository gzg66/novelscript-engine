from __future__ import annotations

import sys
import time
from pathlib import Path
from typing import Any, Iterator

from novelscript.config import AppSettings, LLMRuntimeConfig
from novelscript.logging import get_logger

log = get_logger("llm")


class LLMClient:
    """Thin wrapper around museframe4video's llm_core, configured via Support API."""

    def __init__(self, settings: AppSettings, *, llm_config: LLMRuntimeConfig | None = None) -> None:
        self.settings = settings
        self.llm_config = llm_config or settings.llm
        self._adapter: Any | None = None

    def _ensure_adapter(self) -> Any:
        if self._adapter is not None:
            return self._adapter
        llm_core_path = self.settings.llm_core_path
        if llm_core_path.exists():
            import_root = llm_core_path.parent if (llm_core_path / "__init__.py").is_file() else llm_core_path
            root_str = str(import_root.resolve())
            if root_str not in sys.path:
                sys.path.insert(0, root_str)

        try:
            from llm_core import LLMClient as CoreClient, LLMConfig, ModelRegistry, SupportAPIClient, SupportAPISettings
        except ModuleNotFoundError as exc:
            raise RuntimeError(
                f"llm_core not importable at {self.settings.llm_core_path}. "
                "Install llm_core or set llm_core.path in configs/app.json."
            ) from exc

        support_settings = SupportAPISettings(**self.settings.support_api.as_settings_dict())
        support = SupportAPIClient(support_settings)
        support_payload = support.get_configs()
        if not support_payload:
            raise RuntimeError("support_api returned no config. Check base_url, service_id, token.")

        llm_dict = dict(self.llm_config.as_llm_config_dict())
        registry = ModelRegistry.from_support_payload({"model_registry": support_payload.get("MODEL_REGISTRY", {})})
        resolved_model = registry.resolve_model_id(str(llm_dict.get("model", "")))
        resolved_provider = registry.resolve_provider(str(llm_dict.get("model", "")))
        if resolved_model:
            llm_dict["model"] = resolved_model
        if resolved_provider and not llm_dict.get("provider"):
            llm_dict["provider"] = resolved_provider

        client = CoreClient.from_support_api(support)
        config = LLMConfig(**llm_dict)
        self._adapter = _Adapter(client=client, config=config)
        return self._adapter

    def generate_text(
        self,
        *,
        system: str,
        user: str,
        write_path: Path | None = None,
        stream: bool = True,
    ) -> str:
        adapter = self._ensure_adapter()
        chunks: list[str] = []
        started = time.monotonic()
        last_emit = started
        for chunk in adapter.stream_text(system=system, messages=[{"role": "user", "content": user}]):
            chunks.append(chunk)
            if write_path and stream:
                write_path.parent.mkdir(parents=True, exist_ok=True)
                write_path.write_text("".join(chunks), encoding="utf-8")
            now = time.monotonic()
            total = sum(len(c) for c in chunks)
            if now - last_emit >= 8:
                log.info("LLM 流式输出中… %s 字（%.0f 秒）", total, now - started)
                last_emit = now
        text = "".join(chunks)
        log.info("LLM 完成：%s 字，耗时 %.1f 秒", len(text), time.monotonic() - started)
        if write_path:
            write_path.parent.mkdir(parents=True, exist_ok=True)
            partial = write_path.with_suffix(write_path.suffix + ".partial")
            partial.write_text(text, encoding="utf-8")
            if write_path.exists():
                write_path.unlink()
            partial.rename(write_path)
        return text


class _Adapter:
    def __init__(self, *, client: Any, config: Any) -> None:
        self.client = client
        self.config = config

    def stream_text(self, *, system: str, messages: list[dict[str, Any]]) -> Iterator[str]:
        result = self.client.invoke_stream(
            config=self.config,
            system=system,
            messages=messages,
            tools=None,
            task_id=None,
        )
        for chunk in result:
            if getattr(chunk, "type", None) == "text":
                yield str(getattr(chunk, "delta", "") or "")

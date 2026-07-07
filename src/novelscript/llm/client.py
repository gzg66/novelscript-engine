from __future__ import annotations

import sys
import threading
import time
from pathlib import Path
from collections.abc import Callable
from typing import Any, Iterator

from novelscript.config import AppSettings, LLMRuntimeConfig
from novelscript.logging import get_logger

log = get_logger("llm")

_TRANSIENT_MARKERS = (
    "EOF occurred",
    "Connection reset",
    "Server disconnected",
    "RemoteProtocolError",
    "Connection broken",
    "Connection aborted",
    "ReadError",
    "ConnectError",
    "UNEXPECTED_EOF",
    "timed out",
)
_TRANSIENT_MAX_ATTEMPTS = 4


def _is_transient_llm_error(exc: BaseException) -> bool:
    try:
        import httpx

        if isinstance(
            exc,
            (
                httpx.ConnectError,
                httpx.RemoteProtocolError,
                httpx.ReadError,
                httpx.ReadTimeout,
                httpx.NetworkError,
            ),
        ):
            return True
    except ImportError:
        pass
    text = str(exc)
    return any(marker in text for marker in _TRANSIENT_MARKERS)


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

    def _reset_adapter(self) -> None:
        self._adapter = None

    def generate_text(
        self,
        *,
        system: str,
        user: str,
        write_path: Path | None = None,
        stream: bool = True,
        cancel_check: Callable[[], None] | None = None,
    ) -> str:
        started = time.monotonic()
        chunks: list[str] = []

        for attempt in range(1, _TRANSIENT_MAX_ATTEMPTS + 1):
            try:
                chunks = self._stream_collect(
                    system=system,
                    user=user,
                    write_path=write_path if stream else None,
                    cancel_check=cancel_check,
                    started=started,
                )
                break
            except BaseException as exc:
                if cancel_check:
                    try:
                        cancel_check()
                    except BaseException:
                        raise
                if not _is_transient_llm_error(exc) or attempt >= _TRANSIENT_MAX_ATTEMPTS:
                    raise
                wait = min(2 ** (attempt - 1), 8)
                log.warning(
                    "LLM 连接中断，%s 秒后重试 (%s/%s): %s",
                    wait,
                    attempt,
                    _TRANSIENT_MAX_ATTEMPTS,
                    exc,
                )
                self._reset_adapter()
                time.sleep(wait)

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

    def _stream_collect(
        self,
        *,
        system: str,
        user: str,
        write_path: Path | None,
        cancel_check: Callable[[], None] | None,
        started: float,
    ) -> list[str]:
        adapter = self._ensure_adapter()
        chunks: list[str] = []
        last_emit = started
        poll_stop = threading.Event()
        cancel_error: list[BaseException] = []

        def _poll_cancel() -> None:
            if not cancel_check:
                return
            while not poll_stop.wait(0.25):
                try:
                    cancel_check()
                except BaseException as exc:
                    cancel_error.append(exc)
                    return

        poll_thread = None
        if cancel_check:
            cancel_check()
            poll_thread = threading.Thread(target=_poll_cancel, daemon=True)
            poll_thread.start()

        try:
            for chunk in adapter.stream_text(system=system, messages=[{"role": "user", "content": user}]):
                if cancel_error:
                    raise cancel_error[0]
                if cancel_check:
                    cancel_check()
                chunks.append(chunk)
                if write_path:
                    write_path.parent.mkdir(parents=True, exist_ok=True)
                    write_path.write_text("".join(chunks), encoding="utf-8")
                now = time.monotonic()
                total = sum(len(c) for c in chunks)
                if now - last_emit >= 8:
                    log.info("LLM 流式输出中… %s 字（%.0f 秒）", total, now - started)
                    last_emit = now
        finally:
            poll_stop.set()
            if poll_thread is not None:
                poll_thread.join(timeout=1)

        if cancel_error:
            raise cancel_error[0]
        return chunks


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

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[2]
MUSEFRAME_ROOT = PROJECT_ROOT.parent / "museframe4video"


@dataclass(frozen=True)
class SupportAPIConfig:
    enabled: bool
    base_url: str
    service_id: str
    token: str
    env: str
    timeout: int

    def as_settings_dict(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "base_url": self.base_url,
            "service_id": self.service_id,
            "token": self.token,
            "env": self.env or None,
            "timeout": self.timeout,
        }


@dataclass(frozen=True)
class LLMRuntimeConfig:
    provider: str
    model: str
    temperature: float | None = None
    max_tokens: int | None = None
    timeout: int = 600
    max_retries: int = 3
    stream: bool = True

    def as_llm_config_dict(self) -> dict[str, Any]:
        payload = {
            "provider": self.provider,
            "model": self.model,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            "timeout": self.timeout,
            "max_retries": self.max_retries,
            "stream": self.stream,
        }
        return {k: v for k, v in payload.items() if v is not None}


@dataclass(frozen=True)
class PipelineConfig:
    max_workers: int = 4
    max_attempts: int = 3
    s5_quality_tier: str = "production"


@dataclass(frozen=True)
class AppSettings:
    project_root: Path
    base_workspace_dir: Path
    llm_core_path: Path
    schemas_dir: Path
    support_api: SupportAPIConfig
    llm: LLMRuntimeConfig
    conversion_llm: LLMRuntimeConfig
    pipeline: PipelineConfig = field(default_factory=PipelineConfig)


def _resolve_dotenv_path(dotenv_path: str | Path | None) -> Path:
    if dotenv_path:
        return Path(dotenv_path)
    for candidate in (
        os.getenv("NOVELSCRIPT_DOTENV"),
        str(PROJECT_ROOT / ".env"),
        str(MUSEFRAME_ROOT / ".env"),
    ):
        if candidate and Path(candidate).exists():
            return Path(candidate)
    return PROJECT_ROOT / ".env"


def load_settings(
    config_path: str | Path | None = None,
    dotenv_path: str | Path | None = None,
) -> AppSettings:
    load_dotenv(_resolve_dotenv_path(dotenv_path))
    config = _load_json_config(config_path or os.getenv("NOVELSCRIPT_CONFIG") or PROJECT_ROOT / "configs" / "app.json")

    workspace = dict(config.get("workspace") or {})
    llm_core = dict(config.get("llm_core") or {})
    support_api = dict(config.get("support_api") or {})
    llm = dict(config.get("llm") or {})
    conversion_llm = dict(config.get("conversion_llm") or llm)
    pipeline_cfg = dict(config.get("pipeline") or {})

    base_workspace_dir = Path(
        _env_first("NOVELSCRIPT_BASE_WORKSPACE_DIR", "SMART_SERVICE_BASE_WORKSPACE_DIR", default=workspace.get("base_dir", ".runs"))
    )
    if not base_workspace_dir.is_absolute():
        base_workspace_dir = PROJECT_ROOT / base_workspace_dir

    llm_core_default = llm_core.get("path", "../museframe4video/vendor/llm_core")
    llm_core_raw = _env_first("NOVELSCRIPT_LLM_CORE_PATH", "SMART_SERVICE_LLM_CORE_PATH", default=llm_core_default)
    llm_core_path = Path(llm_core_raw)
    if not llm_core_path.is_absolute():
        base = MUSEFRAME_ROOT if os.getenv("SMART_SERVICE_LLM_CORE_PATH") else PROJECT_ROOT
        llm_core_path = (base / llm_core_path).resolve()

    support_env = _env_first("NOVELSCRIPT_SUPPORT_API_ENV", "SMART_SERVICE_SUPPORT_API_ENV", default=support_api.get("env", ""))

    return AppSettings(
        project_root=PROJECT_ROOT,
        base_workspace_dir=base_workspace_dir,
        llm_core_path=llm_core_path,
        schemas_dir=PROJECT_ROOT / "schemas",
        support_api=SupportAPIConfig(
            enabled=_env_bool_first(
                ("NOVELSCRIPT_SUPPORT_API_ENABLED", "SMART_SERVICE_SUPPORT_API_ENABLED"),
                bool(support_api.get("enabled", True)),
            ),
            base_url=_env_first(
                "NOVELSCRIPT_SUPPORT_API_BASE_URL",
                "SMART_SERVICE_SUPPORT_API_BASE_URL",
                default=_resolve_env_value(support_api.get("base_url", ""), support_env),
            ),
            service_id=_env_first(
                "NOVELSCRIPT_SUPPORT_API_SERVICE_ID",
                "SMART_SERVICE_SUPPORT_API_SERVICE_ID",
                default=support_api.get("service_id", "gencomic_auto_video_pre_api"),
            ),
            token=_env_first(
                "NOVELSCRIPT_SUPPORT_API_TOKEN",
                "SMART_SERVICE_SUPPORT_API_TOKEN",
                "GENCOMIC_SUPPORT_API_TOKEN",
                "SUPPORT_AUTH_TOKEN",
                default=str(support_api.get("token", "")),
            ),
            env=support_env,
            timeout=_env_int_first(
                ("NOVELSCRIPT_SUPPORT_API_TIMEOUT", "SMART_SERVICE_SUPPORT_API_TIMEOUT"),
                int(support_api.get("timeout", 10)),
            ),
        ),
        llm=_llm_config_from_env(("NOVELSCRIPT_LLM", "SMART_SERVICE_LLM"), llm),
        conversion_llm=_llm_config_from_env(("NOVELSCRIPT_CONVERSION_LLM", "SMART_SERVICE_CONVERSION_LLM"), conversion_llm),
        pipeline=PipelineConfig(
            max_workers=_env_int("NOVELSCRIPT_MAX_WORKERS", int(pipeline_cfg.get("max_workers", 4))),
            max_attempts=_env_int("NOVELSCRIPT_MAX_ATTEMPTS", int(pipeline_cfg.get("max_attempts", 3))),
            s5_quality_tier=str(pipeline_cfg.get("s5_quality_tier", "production")),
        ),
    )


def load_dotenv(path: str | Path) -> None:
    target = Path(path)
    if not target.exists():
        return
    for raw_line in target.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if not key or key in os.environ:
            continue
        os.environ[key] = _strip_env_quotes(value.strip())


def _load_json_config(path: str | Path) -> dict[str, Any]:
    target = Path(path)
    if not target.is_absolute():
        target = PROJECT_ROOT / target
    if not target.exists():
        return {}
    payload = json.loads(target.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"config root must be an object: {target}")
    return payload


def _resolve_env_value(value: Any, env: str) -> Any:
    if isinstance(value, dict):
        return value.get(env) or value.get(str(env).lower()) or value.get("default") or ""
    return value


def _llm_config_from_env(prefixes: str | tuple[str, ...], defaults: dict[str, Any]) -> LLMRuntimeConfig:
    if isinstance(prefixes, str):
        prefixes = (prefixes,)
    suffixes = ("PROVIDER", "MODEL", "TEMPERATURE", "MAX_TOKENS", "TIMEOUT", "MAX_RETRIES", "STREAM")
    vals = {s: _env_first(*(f"{p}_{s}" for p in prefixes), default=defaults.get(s.lower())) for s in suffixes}
    return LLMRuntimeConfig(
        provider=str(vals["PROVIDER"] or defaults.get("provider", "gemini")),
        model=str(vals["MODEL"] or defaults.get("model", "gemini_35_flash")),
        temperature=_parse_float(vals["TEMPERATURE"], defaults.get("temperature")),
        max_tokens=_parse_int_optional(vals["MAX_TOKENS"], defaults.get("max_tokens")),
        timeout=int(vals["TIMEOUT"] or defaults.get("timeout", 600)),
        max_retries=int(vals["MAX_RETRIES"] or defaults.get("max_retries", 3)),
        stream=_parse_bool(vals["STREAM"], bool(defaults.get("stream", True))),
    )


def _env_first(*keys: str, default: Any = "") -> str:
    for key in keys:
        value = os.getenv(key)
        if value not in (None, ""):
            return value
    return "" if default is None else str(default)


def _env_bool_first(keys: tuple[str, ...], default: bool) -> bool:
    for key in keys:
        value = os.getenv(key)
        if value is not None:
            return value.strip().lower() in {"1", "true", "yes", "y", "on"}
    return default


def _env_int_first(keys: tuple[str, ...], default: int) -> int:
    for key in keys:
        value = os.getenv(key)
        if value not in (None, ""):
            return int(value)
    return default


def _parse_float(value: Any, default: Any) -> float | None:
    if value in (None, ""):
        value = default
    if value in (None, ""):
        return None
    return float(value)


def _parse_int_optional(value: Any, default: Any) -> int | None:
    if value in (None, ""):
        value = default
    if value in (None, ""):
        return None
    return int(value)


def _parse_bool(value: Any, default: bool) -> bool:
    if value in (None, ""):
        return default
    return str(value).strip().lower() in {"1", "true", "yes", "y", "on"}


def _env(key: str, default: Any = "") -> str:
    value = os.getenv(key)
    if value is None:
        return "" if default is None else str(default)
    return value


def _env_bool(key: str, default: bool = False) -> bool:
    value = os.getenv(key)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}


def _env_int(key: str, default: int) -> int:
    value = os.getenv(key)
    return int(value) if value not in (None, "") else default


def _env_int_optional(key: str, default: Any = None) -> int | None:
    value = os.getenv(key)
    if value in (None, ""):
        value = default
    if value in (None, ""):
        return None
    return int(value)


def _env_float_optional(key: str, default: Any = None) -> float | None:
    value = os.getenv(key)
    if value in (None, ""):
        value = default
    if value in (None, ""):
        return None
    return float(value)


def _strip_env_quotes(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]
    return value

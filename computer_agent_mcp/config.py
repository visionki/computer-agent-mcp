from __future__ import annotations

import os
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Mapping


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    normalized = raw.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    return default


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _default_debug_dir() -> str:
    return str((Path(__file__).resolve().parents[1] / ".computer_agent_mcp_debug").resolve())


@dataclass(slots=True)
class ServerConfig:
    name: str = "computer-agent-mcp"
    openai_api_key: str | None = None
    openai_base_url: str = "https://api.openai.com/v1"
    openai_model: str = "gpt-5.4"
    openai_timeout_seconds: int = 120
    openai_user_agent: str | None = None
    max_steps_default: int = 30
    max_duration_s_default: int = 120
    max_type_chars: int = 200
    default_pause_between_ms: int = 80
    post_action_wait_ms: int = 500
    control_cursor_enabled: bool = True
    debug_include_cursor_overlay: bool = True
    human_override_enabled: bool = True
    mouse_interrupt_threshold_px: int = 15
    kill_switch_file: str | None = None
    debug_enabled: bool = True
    debug_save_images: bool = True
    debug_dir: str = field(default_factory=_default_debug_dir)
    log_level: str = "INFO"

    @classmethod
    def from_env(cls, overrides: Mapping[str, Any] | None = None) -> "ServerConfig":
        config = cls(
            openai_api_key=os.getenv("COMPUTER_AGENT_OPENAI_API_KEY") or os.getenv("OPENAI_API_KEY"),
            openai_base_url=(
                os.getenv("COMPUTER_AGENT_OPENAI_BASE_URL")
                or os.getenv("OPENAI_BASE_URL")
                or "https://api.openai.com/v1"
            ),
            openai_model=os.getenv("COMPUTER_AGENT_OPENAI_MODEL", "gpt-5.4"),
            openai_timeout_seconds=max(10, _env_int("COMPUTER_AGENT_OPENAI_TIMEOUT_SECONDS", 120)),
            openai_user_agent=os.getenv("COMPUTER_AGENT_OPENAI_USER_AGENT"),
            max_steps_default=max(1, _env_int("COMPUTER_AGENT_MAX_STEPS_DEFAULT", 30)),
            max_duration_s_default=max(1, _env_int("COMPUTER_AGENT_MAX_DURATION_S_DEFAULT", 120)),
            max_type_chars=max(1, _env_int("COMPUTER_AGENT_MAX_TYPE_CHARS", 200)),
            default_pause_between_ms=max(0, _env_int("COMPUTER_AGENT_DEFAULT_PAUSE_MS", 80)),
            post_action_wait_ms=max(0, _env_int("COMPUTER_AGENT_POST_ACTION_WAIT_MS", 500)),
            control_cursor_enabled=_env_bool("COMPUTER_AGENT_CONTROL_CURSOR", True),
            debug_include_cursor_overlay=_env_bool("COMPUTER_AGENT_DEBUG_INCLUDE_CURSOR", True),
            human_override_enabled=_env_bool("COMPUTER_AGENT_HUMAN_OVERRIDE", True),
            mouse_interrupt_threshold_px=max(
                1, _env_int("COMPUTER_AGENT_MOUSE_INTERRUPT_THRESHOLD_PX", 15)
            ),
            kill_switch_file=os.getenv("COMPUTER_AGENT_KILL_SWITCH_FILE"),
            debug_enabled=_env_bool("COMPUTER_AGENT_DEBUG", True),
            debug_save_images=_env_bool("COMPUTER_AGENT_DEBUG_SAVE_IMAGES", True),
            debug_dir=os.getenv("COMPUTER_AGENT_DEBUG_DIR", _default_debug_dir()),
            log_level=os.getenv("COMPUTER_AGENT_LOG_LEVEL", "INFO").upper(),
        )
        clean_overrides = {key: value for key, value in (overrides or {}).items() if value is not None}
        return replace(config, **clean_overrides)

    def kill_switch_active(self) -> bool:
        return bool(self.kill_switch_file) and Path(self.kill_switch_file).exists()

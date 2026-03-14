from __future__ import annotations

import sys

from computer_agent_mcp.platform_base import DesktopAdapter, UnsupportedPlatformError
from computer_agent_mcp.platform_windows import WindowsAdapter


class UnsupportedPlatformAdapter(DesktopAdapter):
    @property
    def platform_name(self) -> str:
        return sys.platform

    def _discover_displays(self):
        raise UnsupportedPlatformError(
            f"Platform {sys.platform!r} is not supported. computer-agent-mcp v1 targets Windows only."
        )

    def get_active_window_info(self):
        return None, None


def create_adapter(event_filter) -> DesktopAdapter:
    if sys.platform.startswith("win"):
        return WindowsAdapter(event_filter)
    return UnsupportedPlatformAdapter(event_filter)


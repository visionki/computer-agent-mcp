from __future__ import annotations

import ctypes
from ctypes import wintypes

from computer_agent_mcp.platform_base import DesktopAdapter, DisplayDescriptor


class RECT(ctypes.Structure):
    _fields_ = [
        ("left", wintypes.LONG),
        ("top", wintypes.LONG),
        ("right", wintypes.LONG),
        ("bottom", wintypes.LONG),
    ]


class MONITORINFOEXW(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("rcMonitor", RECT),
        ("rcWork", RECT),
        ("dwFlags", wintypes.DWORD),
        ("szDevice", wintypes.WCHAR * 32),
    ]


MONITORINFOF_PRIMARY = 1


class WindowsAdapter(DesktopAdapter):
    platform_name = "windows"

    def __init__(self, event_filter):
        super().__init__(event_filter)
        self._set_dpi_awareness()

    def _discover_displays(self) -> dict[str, DisplayDescriptor]:
        user32 = ctypes.windll.user32
        shcore = getattr(ctypes.windll, "shcore", None)
        displays: dict[str, DisplayDescriptor] = {}
        monitor_handles: list[ctypes.c_void_p] = []

        def callback(hmonitor, hdc, rect_ptr, data):
            monitor_handles.append(hmonitor)
            return 1

        monitor_enum_proc = ctypes.WINFUNCTYPE(
            ctypes.c_int,
            wintypes.HMONITOR,
            wintypes.HDC,
            ctypes.POINTER(RECT),
            wintypes.LPARAM,
        )(callback)
        user32.EnumDisplayMonitors(0, 0, monitor_enum_proc, 0)

        fallback_index = 1
        for handle in monitor_handles:
            info = MONITORINFOEXW()
            info.cbSize = ctypes.sizeof(MONITORINFOEXW)
            user32.GetMonitorInfoW(handle, ctypes.byref(info))
            width_px = info.rcMonitor.right - info.rcMonitor.left
            height_px = info.rcMonitor.bottom - info.rcMonitor.top
            scale_factor = 1.0
            if shcore is not None:
                try:
                    factor = ctypes.c_int()
                    shcore.GetScaleFactorForMonitor(handle, ctypes.byref(factor))
                    if factor.value:
                        scale_factor = factor.value / 100.0
                except Exception:
                    scale_factor = 1.0
            is_primary = bool(info.dwFlags & MONITORINFOF_PRIMARY)
            display_id = "primary" if is_primary else f"display-{fallback_index}"
            if not is_primary:
                fallback_index += 1
            displays[display_id] = DisplayDescriptor(
                id=display_id,
                name=info.szDevice or display_id,
                is_primary=is_primary,
                width_px=width_px,
                height_px=height_px,
                logical_width=round(width_px / scale_factor, 2),
                logical_height=round(height_px / scale_factor, 2),
                scale_factor=scale_factor,
                origin_x_px=info.rcMonitor.left,
                origin_y_px=info.rcMonitor.top,
                logical_origin_x=round(info.rcMonitor.left / scale_factor, 2),
                logical_origin_y=round(info.rcMonitor.top / scale_factor, 2),
                input_coord_space="pixels",
            )
        return displays

    def get_active_window_info(self) -> tuple[str | None, str | None]:
        user32 = ctypes.windll.user32
        hwnd = user32.GetForegroundWindow()
        if not hwnd:
            return None, None
        length = user32.GetWindowTextLengthW(hwnd)
        buffer = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, buffer, length + 1)
        title = buffer.value or None
        return None, title

    @staticmethod
    def _set_dpi_awareness() -> None:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass


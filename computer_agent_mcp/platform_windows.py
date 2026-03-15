from __future__ import annotations

import ctypes
from ctypes import wintypes
from pathlib import Path

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
SPI_SETCURSORS = 0x0057
IMAGE_CURSOR = 2
OCR_NORMAL = 32512
OCR_IBEAM = 32513
OCR_WAIT = 32514
OCR_CROSS = 32515
OCR_UP = 32516
OCR_SIZENWSE = 32642
OCR_SIZENESW = 32643
OCR_SIZEWE = 32644
OCR_SIZENS = 32645
OCR_SIZEALL = 32646
OCR_NO = 32648
OCR_HAND = 32649
OCR_APPSTARTING = 32650
OCR_HELP = 32651


class _WindowsControlCursorIndicator:
    CURSOR_FILE_BY_SYSTEM_ID = {
        OCR_NORMAL: "normal_select.ani",
        OCR_IBEAM: "text_select.ani",
        OCR_WAIT: "wait.ani",
        OCR_CROSS: "precision_select.ani",
        OCR_UP: "normal_select.ani",
        OCR_SIZENWSE: "diagonal_resize_nwse.ani",
        OCR_SIZENESW: "diagonal_resize_nesw.ani",
        OCR_SIZEWE: "horizontal_resize.ani",
        OCR_SIZENS: "vertical_resize.ani",
        OCR_SIZEALL: "move.ani",
        OCR_NO: "unavailable.ani",
        OCR_HAND: "hand_select.ani",
        OCR_APPSTARTING: "working_in_background.ani",
        OCR_HELP: "help_select.ani",
    }

    def __init__(self, asset_dir: Path) -> None:
        self._asset_dir = asset_dir
        self._user32 = ctypes.WinDLL("user32", use_last_error=True)
        self._user32.LoadCursorFromFileW.argtypes = [wintypes.LPCWSTR]
        self._user32.LoadCursorFromFileW.restype = wintypes.HANDLE
        self._user32.CopyImage.argtypes = [
            wintypes.HANDLE,
            wintypes.UINT,
            ctypes.c_int,
            ctypes.c_int,
            wintypes.UINT,
        ]
        self._user32.CopyImage.restype = wintypes.HANDLE
        self._user32.SetSystemCursor.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        self._user32.SetSystemCursor.restype = wintypes.BOOL
        self._user32.SystemParametersInfoW.argtypes = [
            wintypes.UINT,
            wintypes.UINT,
            wintypes.LPVOID,
            wintypes.UINT,
        ]
        self._user32.SystemParametersInfoW.restype = wintypes.BOOL
        self._active = False

    def activate(self) -> str | None:
        if self._active:
            return None
        try:
            for cursor_id, filename in self.CURSOR_FILE_BY_SYSTEM_ID.items():
                cursor_copy = self._copy_cursor(self._load_cursor_from_file(self._asset_dir / filename))
                if not cursor_copy:
                    raise ctypes.WinError(ctypes.get_last_error())
                if not self._user32.SetSystemCursor(cursor_copy, cursor_id):
                    raise ctypes.WinError(ctypes.get_last_error())
        except Exception as exc:
            self._restore_best_effort()
            return f"Failed to activate the Windows AI-control cursor indicator: {exc}"
        self._active = True
        return None

    def deactivate(self) -> str | None:
        if not self._active:
            return None
        try:
            if not self._user32.SystemParametersInfoW(SPI_SETCURSORS, 0, None, 0):
                raise ctypes.WinError(ctypes.get_last_error())
        except Exception as exc:
            return f"Failed to restore the Windows cursor scheme: {exc}"
        finally:
            self._active = False
        return None

    def _load_cursor_from_file(self, cursor_path: Path):
        if not cursor_path.is_file():
            raise FileNotFoundError(f"Cursor asset not found: {cursor_path}")
        cursor = self._user32.LoadCursorFromFileW(str(cursor_path))
        if not cursor:
            raise ctypes.WinError(ctypes.get_last_error())
        return cursor

    def _copy_cursor(self, cursor_handle):
        return self._user32.CopyImage(cursor_handle, IMAGE_CURSOR, 0, 0, 0)

    def _restore_best_effort(self) -> None:
        try:
            self._user32.SystemParametersInfoW(SPI_SETCURSORS, 0, None, 0)
        except Exception:
            pass


class WindowsAdapter(DesktopAdapter):
    platform_name = "windows"

    def __init__(self, event_filter):
        super().__init__(event_filter)
        self._control_cursor_indicator: _WindowsControlCursorIndicator | None = None
        self._set_dpi_awareness()

    @staticmethod
    def control_cursor_asset_dir() -> Path:
        return Path(__file__).resolve().parent / "assets" / "cursor"

    def activate_control_cursor(self) -> str | None:
        try:
            if self._control_cursor_indicator is None:
                self._control_cursor_indicator = _WindowsControlCursorIndicator(self.control_cursor_asset_dir())
            return self._control_cursor_indicator.activate()
        except Exception as exc:
            return f"Failed to initialize the Windows AI-control cursor indicator: {exc}"

    def deactivate_control_cursor(self) -> str | None:
        if self._control_cursor_indicator is None:
            return None
        return self._control_cursor_indicator.deactivate()

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

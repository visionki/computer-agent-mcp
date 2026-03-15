from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from io import BytesIO
import time
from typing import Callable

from computer_agent_mcp.keys import resolve_pynput_key
from computer_agent_mcp.models import CursorInfo, DisplayInfo
from computer_agent_mcp.monitor import SyntheticEventFilter


class UnsupportedPlatformError(RuntimeError):
    pass


@dataclass(slots=True)
class DisplayDescriptor:
    id: str
    name: str
    is_primary: bool
    width_px: int
    height_px: int
    logical_width: float
    logical_height: float
    scale_factor: float
    origin_x_px: int
    origin_y_px: int
    logical_origin_x: float
    logical_origin_y: float
    input_coord_space: str = "pixels"

    def to_public(self) -> DisplayInfo:
        return DisplayInfo(
            id=self.id,
            name=self.name,
            is_primary=self.is_primary,
            width_px=self.width_px,
            height_px=self.height_px,
            logical_width=self.logical_width,
            logical_height=self.logical_height,
            scale_factor=self.scale_factor,
            origin_x_px=self.origin_x_px,
            origin_y_px=self.origin_y_px,
            logical_origin_x=self.logical_origin_x,
            logical_origin_y=self.logical_origin_y,
        )

    def contains_local_px(self, x: int, y: int) -> bool:
        return 0 <= x < self.width_px and 0 <= y < self.height_px

    def local_px_to_global_input(self, x: int, y: int) -> tuple[float, float]:
        if self.input_coord_space == "logical_points":
            return (
                self.logical_origin_x + (x / self.scale_factor),
                self.logical_origin_y + (y / self.scale_factor),
            )
        return self.origin_x_px + x, self.origin_y_px + y

    def global_input_to_local_px(self, x: float, y: float) -> tuple[int, int]:
        if self.input_coord_space == "logical_points":
            return (
                int(round((x - self.logical_origin_x) * self.scale_factor)),
                int(round((y - self.logical_origin_y) * self.scale_factor)),
            )
        return int(round(x - self.origin_x_px)), int(round(y - self.origin_y_px))


@dataclass(slots=True)
class CapturedDisplayState:
    display: DisplayInfo
    cursor: CursorInfo | None
    active_app: str | None
    active_window_title: str | None
    png_bytes: bytes


class DesktopAdapter(ABC):
    MIN_VISIBLE_MOUSE_MOVE_MS = 120
    POINTER_APPROACH_DURATIONS_MS = {
        "click": 220,
        "drag": 180,
        "scroll": 180,
    }

    def __init__(self, event_filter: SyntheticEventFilter):
        self.event_filter = event_filter
        self._descriptors: dict[str, DisplayDescriptor] = {}
        self._mouse = None
        self._keyboard = None

    @property
    @abstractmethod
    def platform_name(self) -> str: ...

    def startup_warnings(self) -> list[str]:
        return []

    def activate_control_cursor(self) -> str | None:
        return None

    def deactivate_control_cursor(self) -> str | None:
        return None

    def list_displays(self) -> list[DisplayInfo]:
        return [descriptor.to_public() for descriptor in self._load_descriptors().values()]

    def capture_display(self, display_id: str, include_cursor: bool) -> CapturedDisplayState:
        descriptor = self.require_display(display_id)
        monitor = {
            "left": descriptor.origin_x_px,
            "top": descriptor.origin_y_px,
            "width": descriptor.width_px,
            "height": descriptor.height_px,
        }
        from PIL import Image, ImageDraw
        try:
            import mss
        except Exception as exc:
            raise RuntimeError("mss is required for screen capture") from exc

        with mss.mss() as sct:
            shot = sct.grab(monitor)
        image = Image.frombytes("RGB", shot.size, shot.rgb)
        actual_width, actual_height = shot.size

        capture_scale_x = (
            actual_width / descriptor.logical_width if descriptor.logical_width else descriptor.scale_factor
        )
        capture_scale_y = (
            actual_height / descriptor.logical_height if descriptor.logical_height else descriptor.scale_factor
        )
        capture_scale = round((capture_scale_x + capture_scale_y) / 2, 4)

        public_display = DisplayInfo(
            id=descriptor.id,
            name=descriptor.name,
            is_primary=descriptor.is_primary,
            width_px=actual_width,
            height_px=actual_height,
            logical_width=descriptor.logical_width,
            logical_height=descriptor.logical_height,
            scale_factor=capture_scale,
            origin_x_px=descriptor.origin_x_px,
            origin_y_px=descriptor.origin_y_px,
            logical_origin_x=descriptor.logical_origin_x,
            logical_origin_y=descriptor.logical_origin_y,
        )

        cursor = self.current_cursor_for_display(display_id)
        if cursor is not None and (
            descriptor.width_px != actual_width or descriptor.height_px != actual_height
        ):
            cursor = CursorInfo(
                x=int(round(cursor.x * actual_width / max(descriptor.width_px, 1))),
                y=int(round(cursor.y * actual_height / max(descriptor.height_px, 1))),
                visible=cursor.visible,
            )

        if include_cursor and cursor is not None and cursor.visible:
            draw = ImageDraw.Draw(image)
            radius = 10
            draw.ellipse(
                (cursor.x - radius, cursor.y - radius, cursor.x + radius, cursor.y + radius),
                outline="red",
                width=3,
            )
            draw.line((cursor.x - 14, cursor.y, cursor.x + 14, cursor.y), fill="red", width=2)
            draw.line((cursor.x, cursor.y - 14, cursor.x, cursor.y + 14), fill="red", width=2)

        output = BytesIO()
        image.save(output, format="PNG")
        active_app, active_window_title = self.get_active_window_info()
        return CapturedDisplayState(
            display=public_display,
            cursor=cursor,
            active_app=active_app,
            active_window_title=active_window_title,
            png_bytes=output.getvalue(),
        )

    def current_cursor_for_display(self, display_id: str) -> CursorInfo | None:
        descriptor = self.require_display(display_id)
        x, y = self._ensure_mouse().position
        local_x, local_y = descriptor.global_input_to_local_px(x, y)
        if not descriptor.contains_local_px(local_x, local_y):
            return None
        return CursorInfo(x=local_x, y=local_y, visible=True)

    def move_mouse(
        self,
        display_id: str,
        x: int,
        y: int,
        duration_ms: int = 120,
        check_interrupts: Callable[[], None] | None = None,
    ) -> None:
        descriptor = self.require_display(display_id)
        target_x, target_y = descriptor.local_px_to_global_input(x, y)
        mouse = self._ensure_mouse()
        start_x, start_y = mouse.position
        effective_duration_ms = self._effective_mouse_move_duration_ms(
            start_x=start_x,
            start_y=start_y,
            target_x=target_x,
            target_y=target_y,
            requested_duration_ms=duration_ms,
        )
        duration_s = max(0.0, effective_duration_ms / 1000)
        self.event_filter.suppress_mouse_moves(duration_s + 0.25)
        steps = max(1, int(duration_s / 0.01)) if duration_s else 1
        for step in range(1, steps + 1):
            if check_interrupts is not None:
                check_interrupts()
            ratio = step / steps
            next_x = start_x + (target_x - start_x) * ratio
            next_y = start_y + (target_y - start_y) * ratio
            mouse.position = (next_x, next_y)
            if steps > 1:
                time.sleep(duration_s / steps)

    def click_mouse(
        self,
        display_id: str,
        x: int,
        y: int,
        button: str,
        count: int = 1,
        check_interrupts: Callable[[], None] | None = None,
    ) -> None:
        self._approach_pointer(display_id, x, y, action="click", check_interrupts=check_interrupts)
        if check_interrupts is not None:
            check_interrupts()
        time.sleep(0.08)
        descriptor = self.require_display(display_id)
        global_x, global_y = descriptor.local_px_to_global_input(x, y)
        self.event_filter.expect_click(global_x, global_y, button, count=count)
        self._ensure_mouse().click(self._resolve_button(button), count)

    def drag_mouse(
        self,
        display_id: str,
        from_x: int,
        from_y: int,
        to_x: int,
        to_y: int,
        duration_ms: int = 250,
        check_interrupts: Callable[[], None] | None = None,
    ) -> None:
        mouse = self._ensure_mouse()
        descriptor = self.require_display(display_id)
        start_x, start_y = descriptor.local_px_to_global_input(from_x, from_y)
        end_x, end_y = descriptor.local_px_to_global_input(to_x, to_y)
        self._approach_pointer(display_id, from_x, from_y, action="drag", check_interrupts=check_interrupts)
        self.event_filter.expect_click(start_x, start_y, "left")
        self.event_filter.suppress_mouse_moves((duration_ms / 1000) + 0.3)
        mouse.press(self._resolve_button("left"))
        try:
            steps = max(1, int(max(duration_ms, 1) / 16))
            for step in range(1, steps + 1):
                if check_interrupts is not None:
                    check_interrupts()
                ratio = step / steps
                next_x = start_x + (end_x - start_x) * ratio
                next_y = start_y + (end_y - start_y) * ratio
                mouse.position = (next_x, next_y)
                time.sleep(max(duration_ms / 1000, 0.001) / steps)
        finally:
            mouse.release(self._resolve_button("left"))

    def scroll_at(
        self,
        display_id: str,
        x: int,
        y: int,
        page_dx: int,
        page_dy: int,
        check_interrupts: Callable[[], None] | None = None,
    ) -> None:
        self._approach_pointer(display_id, x, y, action="scroll", check_interrupts=check_interrupts)
        self.event_filter.suppress_scroll(0.25)
        wheel_x, wheel_y = self._translate_semantic_scroll(page_dx, page_dy)
        self._ensure_mouse().scroll(wheel_x, wheel_y)

    def type_text(self, text: str) -> None:
        keyboard = self._ensure_keyboard()
        if not text:
            return
        # Let the backend deliver the whole string as one typing operation.
        estimated_seconds = max(0.12, min(2.5, (len(text) * 0.05) + 0.2))
        self.event_filter.suppress_keyboard(estimated_seconds)
        keyboard.type(text)
        time.sleep(0.02)

    def press_keys(self, keys: list[str]) -> None:
        keyboard = self._ensure_keyboard()
        resolved_keys = [resolve_pynput_key(key) for key in keys]
        self.event_filter.suppress_keyboard(0.35)
        for key in resolved_keys:
            keyboard.press(key)
        for key in reversed(resolved_keys):
            keyboard.release(key)

    def require_display(self, display_id: str) -> DisplayDescriptor:
        descriptors = self._load_descriptors()
        if display_id in descriptors:
            return descriptors[display_id]
        if display_id == "primary":
            for descriptor in descriptors.values():
                if descriptor.is_primary:
                    return descriptor
        raise ValueError(f"Unknown display_id: {display_id}")

    def _ensure_mouse(self):
        if self._mouse is None:
            try:
                from pynput import mouse
            except Exception as exc:
                raise RuntimeError("pynput is required for mouse control") from exc
            self._mouse = mouse.Controller()
        return self._mouse

    def _ensure_keyboard(self):
        if self._keyboard is None:
            try:
                from pynput import keyboard
            except Exception as exc:
                raise RuntimeError("pynput is required for keyboard control") from exc
            self._keyboard = keyboard.Controller()
        return self._keyboard

    def _resolve_button(self, button: str):
        try:
            from pynput import mouse
        except Exception as exc:
            raise RuntimeError("pynput is required for mouse control") from exc

        normalized = button.lower()
        mapping = {
            "left": mouse.Button.left,
            "middle": mouse.Button.middle,
            "right": mouse.Button.right,
        }
        try:
            return mapping[normalized]
        except KeyError as exc:
            raise ValueError(f"Unsupported mouse button: {button}") from exc

    def _translate_semantic_scroll(self, page_dx: int, page_dy: int) -> tuple[int, int]:
        # Semantic scroll deltas describe page movement: positive y means scroll down
        # toward later content. Pynput on Windows expects the opposite wheel sign.
        return page_dx, -page_dy

    def _approach_pointer(
        self,
        display_id: str,
        x: int,
        y: int,
        *,
        action: str,
        check_interrupts: Callable[[], None] | None = None,
    ) -> None:
        duration_ms = self.POINTER_APPROACH_DURATIONS_MS[action]
        self.move_mouse(
            display_id,
            x,
            y,
            duration_ms=duration_ms,
            check_interrupts=check_interrupts,
        )

    def _effective_mouse_move_duration_ms(
        self,
        *,
        start_x: float,
        start_y: float,
        target_x: float,
        target_y: float,
        requested_duration_ms: int,
    ) -> int:
        if start_x == target_x and start_y == target_y:
            return 0
        return max(requested_duration_ms, self.MIN_VISIBLE_MOUSE_MOVE_MS)

    def _load_descriptors(self) -> dict[str, DisplayDescriptor]:
        if not self._descriptors:
            self._descriptors = self._discover_displays()
        return self._descriptors

    @abstractmethod
    def _discover_displays(self) -> dict[str, DisplayDescriptor]: ...

    @abstractmethod
    def get_active_window_info(self) -> tuple[str | None, str | None]: ...

from __future__ import annotations

from dataclasses import dataclass
from threading import Event
import time
from typing import Callable

from computer_agent_mcp.config import ServerConfig
from computer_agent_mcp.models import (
    ActionExecutionResult,
    ClickAction,
    ComputerAction,
    DesktopState,
    DoubleClickAction,
    DragAction,
    KeypressAction,
    MoveAction,
    RightClickAction,
    ScrollAction,
    TypeAction,
    WaitAction,
)
from computer_agent_mcp.monitor import HumanOverrideMonitor
from computer_agent_mcp.platform_base import DesktopAdapter


@dataclass(slots=True)
class ActionExecutor:
    adapter: DesktopAdapter
    monitor: HumanOverrideMonitor
    config: ServerConfig

    def mapping_preview(
        self,
        state: DesktopState,
        action: ComputerAction,
        *,
        source_width: int,
        source_height: int,
    ) -> dict | None:
        descriptor = self.adapter.require_display(state.display_id)
        payload = {
            "model_image_px": [source_width, source_height],
            "captured_display_px": [state.display.width_px, state.display.height_px],
            "target_display_px": [descriptor.width_px, descriptor.height_px],
            "target_scale_factor": descriptor.scale_factor,
            "captured_scale_factor": state.display.scale_factor,
        }
        if isinstance(action, (MoveAction, ClickAction, DoubleClickAction, RightClickAction, ScrollAction)):
            mapped = self._map_point(state, action.x, action.y, source_width=source_width, source_height=source_height)
            payload.update({"from": [action.x, action.y], "to": list(mapped)})
            return payload
        if isinstance(action, DragAction):
            mapped_from = self._map_point(
                state,
                action.from_point.x,
                action.from_point.y,
                source_width=source_width,
                source_height=source_height,
            )
            mapped_to = self._map_point(
                state,
                action.to.x,
                action.to.y,
                source_width=source_width,
                source_height=source_height,
            )
            payload.update(
                {
                    "from": [action.from_point.x, action.from_point.y],
                    "to": [action.to.x, action.to.y],
                    "mapped_from": list(mapped_from),
                    "mapped_to": list(mapped_to),
                }
            )
            return payload
        return None

    def execute(
        self,
        state: DesktopState,
        action: ComputerAction,
        *,
        source_width: int,
        source_height: int,
        deadline_monotonic: float | None = None,
        cancel_event: Event | None = None,
        progress_callback: Callable[[str], None] | None = None,
    ) -> ActionExecutionResult:
        self.monitor.arm()
        try:
            self._check_interrupts(deadline_monotonic=deadline_monotonic, cancel_event=cancel_event)
            self._validate_action(state, action, source_width=source_width, source_height=source_height)
            mapping = self.mapping_preview(
                state,
                action,
                source_width=source_width,
                source_height=source_height,
            )
            self._run_action(
                state,
                action,
                source_width=source_width,
                source_height=source_height,
                deadline_monotonic=deadline_monotonic,
                cancel_event=cancel_event,
                progress_callback=progress_callback,
            )
            if self.config.post_action_wait_ms > 0:
                self._sleep_with_override_check(
                    self.config.post_action_wait_ms,
                    deadline_monotonic=deadline_monotonic,
                    cancel_event=cancel_event,
                    progress_callback=progress_callback,
                    progress_label=f"settling {self.config.post_action_wait_ms}ms after action",
                )
            return ActionExecutionResult(status="ok", message="Action executed.", mapping=mapping)
        except HumanOverrideInterrupted:
            return ActionExecutionResult(
                status="blocked",
                message="Automation paused because local input interrupted the run.",
                block_reason="human_override",
                intervention=self.monitor.consume_signal(),
            )
        except SupersededInterrupted:
            return ActionExecutionResult(
                status="blocked",
                message="Automation stopped because a newer task superseded this run.",
                block_reason="superseded",
            )
        except ExecutionDeadlineExceeded:
            return ActionExecutionResult(
                status="blocked",
                message="Automation stopped because the task exceeded its configured time budget.",
                block_reason="timeout",
            )
        except KillSwitchInterrupted:
            return ActionExecutionResult(
                status="blocked",
                message="Execution stopped by the configured kill switch.",
                block_reason="environment_error",
            )
        except Exception as exc:
            return ActionExecutionResult(status="failed", message=str(exc))
        finally:
            self.monitor.disarm()

    def _validate_action(
        self,
        state: DesktopState,
        action: ComputerAction,
        *,
        source_width: int,
        source_height: int,
    ) -> None:
        if isinstance(action, (MoveAction, ClickAction, DoubleClickAction, RightClickAction, ScrollAction)):
            self._validate_source_point(action.x, action.y, source_width=source_width, source_height=source_height)
            return
        if isinstance(action, DragAction):
            self._validate_source_point(
                action.from_point.x,
                action.from_point.y,
                source_width=source_width,
                source_height=source_height,
            )
            self._validate_source_point(
                action.to.x,
                action.to.y,
                source_width=source_width,
                source_height=source_height,
            )
            return
        if isinstance(action, TypeAction):
            if len(action.text) > self.config.max_type_chars:
                raise ValueError(
                    f"type action text length exceeds limit {self.config.max_type_chars}"
                )
            return
        if isinstance(action, KeypressAction):
            return
        if isinstance(action, WaitAction):
            if action.ms < 0:
                raise ValueError("wait.ms must be non-negative")
            return
        raise ValueError(f"Unsupported action type: {action.type}")

    def _validate_source_point(self, x: int, y: int, *, source_width: int, source_height: int) -> None:
        if not (0 <= x < source_width and 0 <= y < source_height):
            raise ValueError(
                f"Point ({x}, {y}) is outside model image bounds {source_width}x{source_height}"
            )

    def _map_point(
        self,
        state: DesktopState,
        x: int,
        y: int,
        *,
        source_width: int,
        source_height: int,
    ) -> tuple[int, int]:
        descriptor = self.adapter.require_display(state.display_id)
        mapped_x = int(round(x * descriptor.width_px / max(source_width, 1)))
        mapped_y = int(round(y * descriptor.height_px / max(source_height, 1)))
        mapped_x = max(0, min(descriptor.width_px - 1, mapped_x))
        mapped_y = max(0, min(descriptor.height_px - 1, mapped_y))
        return mapped_x, mapped_y

    def _run_action(
        self,
        state: DesktopState,
        action: ComputerAction,
        *,
        source_width: int,
        source_height: int,
        deadline_monotonic: float | None,
        cancel_event: Event | None,
        progress_callback: Callable[[str], None] | None,
    ) -> None:
        display_id = state.display_id
        check_interrupts = lambda: self._check_interrupts(  # noqa: E731
            deadline_monotonic=deadline_monotonic,
            cancel_event=cancel_event,
        )
        if isinstance(action, MoveAction):
            x, y = self._map_point(
                state,
                action.x,
                action.y,
                source_width=source_width,
                source_height=source_height,
            )
            self.adapter.move_mouse(
                display_id,
                x,
                y,
                action.duration_ms,
                check_interrupts=self._progress_interrupt_checker(
                    check_interrupts,
                    progress_callback=progress_callback,
                    message=f"moving mouse toward ({action.x}, {action.y})",
                ),
            )
            return
        if isinstance(action, ClickAction):
            x, y = self._map_point(
                state,
                action.x,
                action.y,
                source_width=source_width,
                source_height=source_height,
            )
            self.adapter.click_mouse(display_id, x, y, action.button, count=1, check_interrupts=check_interrupts)
            return
        if isinstance(action, DoubleClickAction):
            x, y = self._map_point(
                state,
                action.x,
                action.y,
                source_width=source_width,
                source_height=source_height,
            )
            self.adapter.click_mouse(display_id, x, y, "left", count=2, check_interrupts=check_interrupts)
            return
        if isinstance(action, RightClickAction):
            x, y = self._map_point(
                state,
                action.x,
                action.y,
                source_width=source_width,
                source_height=source_height,
            )
            self.adapter.click_mouse(display_id, x, y, "right", count=1, check_interrupts=check_interrupts)
            return
        if isinstance(action, DragAction):
            from_x, from_y = self._map_point(
                state,
                action.from_point.x,
                action.from_point.y,
                source_width=source_width,
                source_height=source_height,
            )
            to_x, to_y = self._map_point(
                state,
                action.to.x,
                action.to.y,
                source_width=source_width,
                source_height=source_height,
            )
            self.adapter.drag_mouse(
                display_id,
                from_x,
                from_y,
                to_x,
                to_y,
                action.duration_ms,
                check_interrupts=self._progress_interrupt_checker(
                    check_interrupts,
                    progress_callback=progress_callback,
                    message=(
                        "dragging pointer "
                        f"from ({action.from_point.x}, {action.from_point.y}) "
                        f"to ({action.to.x}, {action.to.y})"
                    ),
                ),
            )
            return
        if isinstance(action, ScrollAction):
            x, y = self._map_point(
                state,
                action.x,
                action.y,
                source_width=source_width,
                source_height=source_height,
            )
            semantic_delta_x, semantic_delta_y = self._semantic_scroll_delta(action)
            self.adapter.scroll_at(
                display_id,
                x,
                y,
                semantic_delta_x,
                semantic_delta_y,
                check_interrupts=check_interrupts,
            )
            return
        if isinstance(action, TypeAction):
            self._type_with_override(
                action.text,
                deadline_monotonic=deadline_monotonic,
                cancel_event=cancel_event,
                progress_callback=progress_callback,
            )
            return
        if isinstance(action, KeypressAction):
            self.adapter.press_keys(action.keys)
            return
        if isinstance(action, WaitAction):
            self._sleep_with_override_check(
                action.ms,
                deadline_monotonic=deadline_monotonic,
                cancel_event=cancel_event,
                progress_callback=progress_callback,
                progress_label=f"waiting {action.ms}ms",
            )
            return
        raise ValueError(f"Unsupported action type: {action.type}")

    def _type_with_override(
        self,
        text: str,
        *,
        deadline_monotonic: float | None,
        cancel_event: Event | None,
        progress_callback: Callable[[str], None] | None = None,
    ) -> None:
        self._check_interrupts(deadline_monotonic=deadline_monotonic, cancel_event=cancel_event)
        self.adapter.type_text(text)
        self._check_interrupts(deadline_monotonic=deadline_monotonic, cancel_event=cancel_event)
        if progress_callback is not None and text:
            progress_callback(f"typing text ({len(text)}/{len(text)} chars)")

    def _sleep_with_override_check(
        self,
        ms: int,
        *,
        deadline_monotonic: float | None = None,
        cancel_event: Event | None = None,
        progress_callback: Callable[[str], None] | None = None,
        progress_label: str | None = None,
    ) -> None:
        if ms <= 0:
            return
        total_seconds = ms / 1000
        remaining = total_seconds
        interval = 0.5
        next_report_at = interval
        while remaining > 0:
            self._check_interrupts(deadline_monotonic=deadline_monotonic, cancel_event=cancel_event)
            slice_seconds = min(remaining, 0.03)
            time.sleep(slice_seconds)
            remaining -= slice_seconds
            if progress_callback is not None and progress_label is not None:
                elapsed = max(0.0, total_seconds - remaining)
                if elapsed >= next_report_at and remaining > 0:
                    progress_callback(
                        f"{progress_label} ({int(round(elapsed * 1000))}/{ms}ms)"
                    )
                    next_report_at += interval

    def _progress_interrupt_checker(
        self,
        base_check_interrupts: Callable[[], None],
        *,
        progress_callback: Callable[[str], None] | None,
        message: str,
    ) -> Callable[[], None]:
        if progress_callback is None:
            return base_check_interrupts

        last_report = 0.0

        def wrapped() -> None:
            nonlocal last_report
            base_check_interrupts()
            now = time.monotonic()
            if now - last_report >= 0.5:
                progress_callback(message)
                last_report = now

        return wrapped

    def _semantic_scroll_delta(self, action: ScrollAction) -> tuple[int, int]:
        if action.direction == "down":
            return 0, action.amount
        if action.direction == "up":
            return 0, -action.amount
        if action.direction == "right":
            return action.amount, 0
        return -action.amount, 0

    def _check_interrupts(
        self,
        *,
        deadline_monotonic: float | None = None,
        cancel_event: Event | None = None,
    ) -> None:
        if self.monitor.interrupted():
            raise HumanOverrideInterrupted
        if cancel_event is not None and cancel_event.is_set():
            raise SupersededInterrupted
        if self.config.kill_switch_active():
            raise KillSwitchInterrupted
        if deadline_monotonic is not None and time.monotonic() > deadline_monotonic:
            raise ExecutionDeadlineExceeded


class HumanOverrideInterrupted(Exception):
    pass


class KillSwitchInterrupted(Exception):
    pass


class SupersededInterrupted(Exception):
    pass


class ExecutionDeadlineExceeded(Exception):
    pass

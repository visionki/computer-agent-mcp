from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from datetime import UTC, datetime
from math import hypot
from threading import Event, Lock
import time

from computer_agent_mcp.keys import normalize_key_token
from computer_agent_mcp.models import InterventionInfo


@dataclass(slots=True)
class _ExpectedClick:
    x: float
    y: float
    button: str
    expires_at: float


@dataclass(slots=True)
class HumanOverrideSignal:
    event_type: str
    key: str | None = None
    x: int | None = None
    y: int | None = None
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))

    def to_model(self) -> InterventionInfo:
        return InterventionInfo(
            event_type=self.event_type,
            key=self.key,
            x=self.x,
            y=self.y,
            timestamp=self.timestamp.astimezone(UTC).isoformat(),
        )


class SyntheticEventFilter:
    def __init__(self) -> None:
        self._lock = Lock()
        self._keyboard_suppressed_until = 0.0
        self._mouse_move_suppressed_until = 0.0
        self._scroll_suppressed_until = 0.0
        self._expected_clicks: deque[_ExpectedClick] = deque()

    def suppress_keyboard(self, seconds: float) -> None:
        with self._lock:
            self._keyboard_suppressed_until = max(
                self._keyboard_suppressed_until, time.monotonic() + seconds
            )

    def suppress_mouse_moves(self, seconds: float) -> None:
        with self._lock:
            self._mouse_move_suppressed_until = max(
                self._mouse_move_suppressed_until, time.monotonic() + seconds
            )

    def suppress_scroll(self, seconds: float) -> None:
        with self._lock:
            self._scroll_suppressed_until = max(
                self._scroll_suppressed_until, time.monotonic() + seconds
            )

    def expect_click(self, x: float, y: float, button: str, ttl: float = 0.45, count: int = 1) -> None:
        with self._lock:
            expires_at = time.monotonic() + ttl
            for _ in range(max(1, count)):
                self._expected_clicks.append(
                    _ExpectedClick(x=x, y=y, button=button, expires_at=expires_at)
                )

    def ignore_keyboard(self) -> bool:
        with self._lock:
            return time.monotonic() <= self._keyboard_suppressed_until

    def ignore_mouse_move(self) -> bool:
        with self._lock:
            return time.monotonic() <= self._mouse_move_suppressed_until

    def ignore_scroll(self) -> bool:
        with self._lock:
            return time.monotonic() <= self._scroll_suppressed_until

    def ignore_click(self, x: float, y: float, button: str) -> bool:
        now = time.monotonic()
        with self._lock:
            while self._expected_clicks and self._expected_clicks[0].expires_at < now:
                self._expected_clicks.popleft()
            for click in list(self._expected_clicks):
                if click.button != button:
                    continue
                if hypot(click.x - x, click.y - y) <= 8:
                    self._expected_clicks.remove(click)
                    return True
            return False


class HumanOverrideMonitor:
    def __init__(self, threshold_px: int = 15, enabled: bool = True) -> None:
        self.threshold_px = threshold_px
        self.enabled = enabled
        self.filter = SyntheticEventFilter()
        self._listeners_started = False
        self._start_warning: str | None = None
        self._lock = Lock()
        self._armed = False
        self._signal: HumanOverrideSignal | None = None
        self._interrupt = Event()
        self._movement_anchor: tuple[float, float] | None = None
        self._mouse_listener = None
        self._keyboard_listener = None

    @property
    def startup_warning(self) -> str | None:
        return self._start_warning

    def start(self) -> None:
        if not self.enabled or self._listeners_started:
            return
        try:
            from pynput import keyboard, mouse
        except Exception as exc:
            self._start_warning = f"Human override monitor unavailable: {exc}"
            self.enabled = False
            return

        self._mouse_listener = mouse.Listener(
            on_move=self._on_move,
            on_click=self._on_click,
            on_scroll=self._on_scroll,
        )
        self._keyboard_listener = keyboard.Listener(on_press=self._on_press)
        self._mouse_listener.start()
        self._keyboard_listener.start()
        self._listeners_started = True

    def stop(self) -> None:
        if self._mouse_listener is not None:
            self._mouse_listener.stop()
        if self._keyboard_listener is not None:
            self._keyboard_listener.stop()

    def arm(self) -> None:
        if not self.enabled:
            return
        with self._lock:
            self._armed = True
            self._signal = None
            self._interrupt.clear()
            self._movement_anchor = None

    def disarm(self) -> None:
        with self._lock:
            self._armed = False
            self._movement_anchor = None

    def interrupted(self) -> bool:
        return self._interrupt.is_set()

    def consume_signal(self) -> InterventionInfo | None:
        with self._lock:
            signal = self._signal
            self._signal = None
            return signal.to_model() if signal else None

    def _trigger(self, signal: HumanOverrideSignal) -> None:
        with self._lock:
            if not self._armed or self._signal is not None:
                return
            self._signal = signal
            self._interrupt.set()

    def _on_move(self, x: float, y: float) -> None:
        if not self.enabled or self.filter.ignore_mouse_move():
            return
        with self._lock:
            if not self._armed:
                return
            if self._movement_anchor is None:
                self._movement_anchor = (x, y)
                return
            anchor_x, anchor_y = self._movement_anchor
            if hypot(anchor_x - x, anchor_y - y) >= self.threshold_px:
                self._signal = HumanOverrideSignal(
                    event_type="mouse_move",
                    x=int(round(x)),
                    y=int(round(y)),
                    timestamp=datetime.now(UTC),
                )
                self._interrupt.set()

    def _on_click(self, x: float, y: float, button, pressed: bool) -> None:
        if not self.enabled or not pressed:
            return
        button_name = getattr(button, "name", str(button)).lower()
        if self.filter.ignore_click(x, y, button_name):
            return
        self._trigger(
            HumanOverrideSignal(
                event_type="mouse_click",
                x=int(round(x)),
                y=int(round(y)),
                timestamp=datetime.now(UTC),
            )
        )

    def _on_scroll(self, x: float, y: float, dx: float, dy: float) -> None:
        if not self.enabled or self.filter.ignore_scroll():
            return
        self._trigger(
            HumanOverrideSignal(
                event_type="scroll",
                x=int(round(x)),
                y=int(round(y)),
                timestamp=datetime.now(UTC),
            )
        )

    def _on_press(self, key) -> None:
        if not self.enabled or self.filter.ignore_keyboard():
            return
        normalized = normalize_key_token(key)
        self._trigger(
            HumanOverrideSignal(
                event_type="keyboard",
                key=normalized,
                timestamp=datetime.now(UTC),
            )
        )

from __future__ import annotations

from computer_agent_mcp.platform_base import DesktopAdapter, DisplayDescriptor


class FakeEventFilter:
    def __init__(self) -> None:
        self.suppressed_mouse_moves: list[float] = []
        self.suppressed_scroll: list[float] = []
        self.expected_clicks: list[tuple[float, float, str, int]] = []

    def suppress_mouse_moves(self, seconds: float) -> None:
        self.suppressed_mouse_moves.append(seconds)

    def suppress_scroll(self, seconds: float) -> None:
        self.suppressed_scroll.append(seconds)

    def expect_click(self, x: float, y: float, button: str, count: int = 1) -> None:
        self.expected_clicks.append((x, y, button, count))


class FakeMouse:
    def __init__(self, start_position: tuple[float, float] = (0.0, 0.0)) -> None:
        self._position = start_position
        self.positions: list[tuple[float, float]] = []
        self.clicks: list[tuple[str, int]] = []
        self.presses: list[str] = []
        self.releases: list[str] = []
        self.scrolls: list[tuple[int, int]] = []

    @property
    def position(self) -> tuple[float, float]:
        return self._position

    @position.setter
    def position(self, value: tuple[float, float]) -> None:
        self._position = value
        self.positions.append(value)

    def click(self, button: str, count: int) -> None:
        self.clicks.append((button, count))

    def press(self, button: str) -> None:
        self.presses.append(button)

    def release(self, button: str) -> None:
        self.releases.append(button)

    def scroll(self, dx: int, dy: int) -> None:
        self.scrolls.append((dx, dy))


class TestDesktopAdapter(DesktopAdapter):
    platform_name = "test"

    def __init__(self, event_filter: FakeEventFilter, mouse: FakeMouse) -> None:
        super().__init__(event_filter)
        self._mouse = mouse
        self._descriptors = {"primary": self._make_descriptor()}

    def _discover_displays(self) -> dict[str, DisplayDescriptor]:
        return self._descriptors

    def get_active_window_info(self) -> tuple[str | None, str | None]:
        return None, None

    def _resolve_button(self, button: str) -> str:
        return button

    @staticmethod
    def _make_descriptor() -> DisplayDescriptor:
        return DisplayDescriptor(
            id="primary",
            name="Primary",
            is_primary=True,
            width_px=1920,
            height_px=1080,
            logical_width=1920,
            logical_height=1080,
            scale_factor=1.0,
            origin_x_px=0,
            origin_y_px=0,
            logical_origin_x=0,
            logical_origin_y=0,
        )


def test_move_mouse_enforces_minimum_visible_duration(monkeypatch):
    monkeypatch.setattr("computer_agent_mcp.platform_base.time.sleep", lambda _: None)
    event_filter = FakeEventFilter()
    mouse = FakeMouse()
    adapter = TestDesktopAdapter(event_filter, mouse)

    adapter.move_mouse("primary", 120, 0, duration_ms=40)

    assert len(mouse.positions) == 12
    assert mouse.position == (120.0, 0.0)
    assert len(event_filter.suppressed_mouse_moves) == 1
    assert abs(event_filter.suppressed_mouse_moves[0] - 0.37) < 1e-9


def test_scroll_at_uses_visible_pointer_approach(monkeypatch):
    monkeypatch.setattr("computer_agent_mcp.platform_base.time.sleep", lambda _: None)
    event_filter = FakeEventFilter()
    mouse = FakeMouse()
    adapter = TestDesktopAdapter(event_filter, mouse)

    adapter.scroll_at("primary", 300, 400, 0, 900)

    assert len(mouse.positions) == 18
    assert mouse.position == (300.0, 400.0)
    assert len(event_filter.suppressed_mouse_moves) == 1
    assert abs(event_filter.suppressed_mouse_moves[0] - 0.43) < 1e-9
    assert event_filter.suppressed_scroll == [0.25]
    assert mouse.scrolls == [(0, -900)]


def test_click_and_drag_use_unified_pointer_approach(monkeypatch):
    monkeypatch.setattr("computer_agent_mcp.platform_base.time.sleep", lambda _: None)

    click_filter = FakeEventFilter()
    click_mouse = FakeMouse()
    click_adapter = TestDesktopAdapter(click_filter, click_mouse)
    click_adapter.click_mouse("primary", 200, 50, "left")

    assert len(click_mouse.positions) == 22
    assert len(click_filter.suppressed_mouse_moves) == 1
    assert abs(click_filter.suppressed_mouse_moves[0] - 0.47) < 1e-9
    assert click_filter.expected_clicks == [(200, 50, "left", 1)]
    assert click_mouse.clicks == [("left", 1)]

    drag_filter = FakeEventFilter()
    drag_mouse = FakeMouse()
    drag_adapter = TestDesktopAdapter(drag_filter, drag_mouse)
    drag_adapter.drag_mouse("primary", 100, 100, 500, 300, duration_ms=250)

    assert len(drag_mouse.positions) == 33
    assert len(drag_filter.suppressed_mouse_moves) == 2
    assert abs(drag_filter.suppressed_mouse_moves[0] - 0.43) < 1e-9
    assert abs(drag_filter.suppressed_mouse_moves[1] - 0.55) < 1e-9
    assert drag_filter.expected_clicks == [(100, 100, "left", 1)]
    assert drag_mouse.presses == ["left"]
    assert drag_mouse.releases == ["left"]

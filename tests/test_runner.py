from __future__ import annotations

import asyncio
from io import BytesIO
from pathlib import Path

from PIL import Image

from computer_agent_mcp.config import ServerConfig
from computer_agent_mcp.debug import DebugRecorder
from computer_agent_mcp.executor import ActionExecutor
from computer_agent_mcp.models import (
    ClickAction,
    ComputerTaskArgs,
    CursorInfo,
    DisplayInfo,
    InterventionInfo,
    RunResult,
    WaitAction,
    WorkerDecision,
)
from computer_agent_mcp.openai_adapter import ModelAdapter, ModelResponseError
from computer_agent_mcp.runner import ComputerAgentRunner


def make_png(color: str, width: int = 1000, height: int = 500) -> bytes:
    image = Image.new("RGB", (width, height), color=color)
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


class PassiveMonitor:
    def __init__(self) -> None:
        self.filter = object()

    def arm(self) -> None:
        pass

    def disarm(self) -> None:
        pass

    def interrupted(self) -> bool:
        return False

    def consume_signal(self):
        return None


class InterruptingMonitor(PassiveMonitor):
    def __init__(self) -> None:
        super().__init__()
        self._armed = False
        self._tripped = False

    def arm(self) -> None:
        self._armed = True
        self._tripped = False

    def disarm(self) -> None:
        self._armed = False

    def interrupted(self) -> bool:
        if self._armed and not self._tripped:
            self._tripped = True
            return True
        return False

    def consume_signal(self):
        return InterventionInfo(
            event_type="mouse_move",
            x=10,
            y=10,
            timestamp="2026-03-14T00:00:00Z",
        )


class FakeAdapter:
    platform_name = "windows"

    def __init__(
        self,
        capture_pngs: list[bytes],
        *,
        activate_control_cursor_warning: str | None = None,
        deactivate_control_cursor_warning: str | None = None,
    ) -> None:
        self.capture_pngs = list(capture_pngs)
        self.capture_index = 0
        self.capture_include_cursor_args: list[bool] = []
        self.actions: list[tuple] = []
        self.activate_control_cursor_warning = activate_control_cursor_warning
        self.deactivate_control_cursor_warning = deactivate_control_cursor_warning
        self.control_cursor_activations = 0
        self.control_cursor_deactivations = 0
        self.descriptor = type(
            "Descriptor",
            (),
            {
                "id": "primary",
                "name": "Primary",
                "is_primary": True,
                "width_px": 1000,
                "height_px": 500,
                "logical_width": 1000.0,
                "logical_height": 500.0,
                "scale_factor": 1.0,
                "origin_x_px": 0,
                "origin_y_px": 0,
                "logical_origin_x": 0.0,
                "logical_origin_y": 0.0,
                "to_public": lambda self: DisplayInfo(
                    id="primary",
                    name="Primary",
                    is_primary=True,
                    width_px=1000,
                    height_px=500,
                    logical_width=1000.0,
                    logical_height=500.0,
                    scale_factor=1.0,
                    origin_x_px=0,
                    origin_y_px=0,
                    logical_origin_x=0.0,
                    logical_origin_y=0.0,
                ),
            },
        )()

    def startup_warnings(self) -> list[str]:
        return []

    def list_displays(self):
        return [self.descriptor.to_public()]

    def require_display(self, display_id: str):
        return self.descriptor

    def capture_display(self, display_id: str, include_cursor: bool):
        self.capture_include_cursor_args.append(include_cursor)
        index = min(self.capture_index, len(self.capture_pngs) - 1)
        png_bytes = self.capture_pngs[index]
        self.capture_index += 1
        return type(
            "Capture",
            (),
            {
                "display": self.descriptor.to_public(),
                "cursor": CursorInfo(x=10, y=10, visible=True),
                "active_app": "Browser",
                "active_window_title": f"Window {self.capture_index}",
                "png_bytes": png_bytes,
            },
        )()

    def activate_control_cursor(self) -> str | None:
        self.control_cursor_activations += 1
        return self.activate_control_cursor_warning

    def deactivate_control_cursor(self) -> str | None:
        self.control_cursor_deactivations += 1
        return self.deactivate_control_cursor_warning

    def move_mouse(
        self,
        display_id: str,
        x: int,
        y: int,
        duration_ms: int = 120,
        check_interrupts=None,
    ) -> None:
        if check_interrupts is not None:
            check_interrupts()
        self.actions.append(("move", x, y, duration_ms))

    def click_mouse(
        self,
        display_id: str,
        x: int,
        y: int,
        button: str,
        count: int = 1,
        check_interrupts=None,
    ) -> None:
        if check_interrupts is not None:
            check_interrupts()
        self.actions.append(("click", x, y, button, count))

    def drag_mouse(
        self,
        display_id: str,
        from_x: int,
        from_y: int,
        to_x: int,
        to_y: int,
        duration_ms: int = 250,
        check_interrupts=None,
    ) -> None:
        if check_interrupts is not None:
            check_interrupts()
        self.actions.append(("drag", from_x, from_y, to_x, to_y, duration_ms))

    def scroll_at(self, display_id: str, x: int, y: int, page_dx: int, page_dy: int, check_interrupts=None) -> None:
        if check_interrupts is not None:
            check_interrupts()
        self.actions.append(("scroll", x, y, page_dx, page_dy))

    def type_text(self, text: str) -> None:
        self.actions.append(("type", text))

    def press_keys(self, keys: list[str]) -> None:
        self.actions.append(("keypress", tuple(keys)))


class SequenceModel(ModelAdapter):
    def __init__(self, items):
        self.items = list(items)
        self.calls = 0

    async def plan_step(self, context, state, debug_recorder):
        item = self.items[self.calls]
        self.calls += 1
        if isinstance(item, Exception):
            raise item
        return item


class BlockingModel(ModelAdapter):
    def __init__(self) -> None:
        self.started = asyncio.Event()
        self.release = asyncio.Event()

    async def plan_step(self, context, state, debug_recorder):
        self.started.set()
        await self.release.wait()
        return make_decision("completed", "done")


def make_decision(
    status: str,
    summary: str,
    *,
    observation: str | None = None,
    memory_update: str | None = None,
    expected_outcome: str | None = None,
    result: str | None = None,
    actions=None,
    image_width: int = 1000,
    image_height: int = 500,
    block_reason: str | None = None,
    next_user_action: str | None = None,
) -> WorkerDecision:
    return WorkerDecision(
        status=status,
        summary=summary,
        observation=observation,
        memory_update=memory_update,
        expected_outcome=expected_outcome,
        result=result,
        image_width=image_width,
        image_height=image_height,
        actions=actions or [],
        block_reason=block_reason,
        next_user_action=next_user_action,
    )


def make_runner(
    model: ModelAdapter,
    adapter: FakeAdapter,
    monitor,
    *,
    max_steps_default: int = 30,
    max_duration_s_default: int = 120,
    monotonic_fn=None,
) -> ComputerAgentRunner:
    config = ServerConfig(
        max_steps_default=max_steps_default,
        max_duration_s_default=max_duration_s_default,
        debug_enabled=False,
        post_action_wait_ms=0,
    )
    executor = ActionExecutor(adapter=adapter, monitor=monitor, config=config)
    return ComputerAgentRunner(
        config=config,
        adapter=adapter,
        executor=executor,
        model_adapter=model,
        debug_recorder=DebugRecorder(enabled=False, base_dir=Path("unused")),
        startup_warnings=[],
        monotonic_fn=monotonic_fn or (lambda: 0.0),
    )


def test_runner_completes_after_single_action():
    async def scenario() -> RunResult:
        adapter = FakeAdapter([make_png("blue"), make_png("green")])
        model = SequenceModel(
            [
                make_decision(
                    "act",
                    "Click the search box.",
                    observation="The page shows a search box.",
                    memory_update="The target page shows a visible search box.",
                    expected_outcome="The search box should become focused.",
                    actions=[ClickAction(x=100, y=80)],
                ),
                make_decision(
                    "completed",
                    "The task is done.",
                    observation="The task is visibly complete.",
                    memory_update="The success state is now visible on screen.",
                    result="Visible success state is shown.",
                ),
            ]
        )
        runner = make_runner(model, adapter, PassiveMonitor(), monotonic_fn=lambda: 0.0)
        return await runner.run(ComputerTaskArgs(task="Open the site"))

    result = asyncio.run(scenario())
    assert result.status == "completed"
    assert result.steps_executed == 1
    assert [step.summary for step in result.trace] == [
        "Click the search box.",
        "The task is done.",
    ]
    assert result.trace[0].execution_status == "ok"
    assert result.trace[1].execution_status == "completed"
    assert result.trace[0].observation == "The page shows a search box."
    assert result.trace[0].memory_update == "The target page shows a visible search box."
    assert result.trace[0].expected_outcome == "The search box should become focused."
    assert result.trace[1].memory_update == "The success state is now visible on screen."
    assert result.result == "Visible success state is shown."
    assert result.memory == [
        "The target page shows a visible search box.",
        "The success state is now visible on screen.",
    ]
    assert result.trace[0].resulting_window_title == "Window 2"


def test_runner_sends_raw_screenshot_to_model_capture():
    async def scenario():
        adapter = FakeAdapter([make_png("blue")])
        model = SequenceModel([make_decision("completed", "done")])
        runner = make_runner(model, adapter, PassiveMonitor(), monotonic_fn=lambda: 0.0)
        result = await runner.run(ComputerTaskArgs(task="Observe current screen"))
        return result, adapter

    result, adapter = asyncio.run(scenario())
    assert result.status == "completed"
    assert adapter.capture_include_cursor_args == [False]


def test_runner_wraps_run_with_control_cursor_lifecycle():
    async def scenario():
        adapter = FakeAdapter([make_png("blue")])
        model = SequenceModel([make_decision("completed", "done")])
        runner = make_runner(model, adapter, PassiveMonitor(), monotonic_fn=lambda: 0.0)
        result = await runner.run(ComputerTaskArgs(task="Observe current screen"))
        return result, adapter

    result, adapter = asyncio.run(scenario())
    assert result.status == "completed"
    assert adapter.control_cursor_activations == 1
    assert adapter.control_cursor_deactivations == 1


def test_runner_includes_control_cursor_activation_warning():
    async def scenario():
        adapter = FakeAdapter(
            [make_png("blue")],
            activate_control_cursor_warning="control cursor unavailable",
        )
        model = SequenceModel([make_decision("completed", "done")])
        runner = make_runner(model, adapter, PassiveMonitor(), monotonic_fn=lambda: 0.0)
        result = await runner.run(ComputerTaskArgs(task="Observe current screen"))
        return result, adapter

    result, adapter = asyncio.run(scenario())
    assert result.status == "completed"
    assert "control cursor unavailable" in result.warnings
    assert adapter.control_cursor_activations == 1
    assert adapter.control_cursor_deactivations == 1


def test_runner_includes_control_cursor_restore_warning():
    async def scenario():
        adapter = FakeAdapter(
            [make_png("blue")],
            deactivate_control_cursor_warning="control cursor restore failed",
        )
        model = SequenceModel([make_decision("completed", "done")])
        runner = make_runner(model, adapter, PassiveMonitor(), monotonic_fn=lambda: 0.0)
        result = await runner.run(ComputerTaskArgs(task="Observe current screen"))
        return result, adapter

    result, adapter = asyncio.run(scenario())
    assert result.status == "completed"
    assert "control cursor restore failed" in result.warnings
    assert adapter.control_cursor_activations == 1
    assert adapter.control_cursor_deactivations == 1


def test_runner_blocks_when_model_requests_login():
    async def scenario() -> RunResult:
        adapter = FakeAdapter([make_png("blue")])
        model = SequenceModel(
            [
                make_decision(
                    "blocked",
                    "The site needs a login.",
                    block_reason="requires_login",
                    next_user_action="Log in, then rerun the task.",
                )
            ]
        )
        runner = make_runner(model, adapter, PassiveMonitor(), monotonic_fn=lambda: 0.0)
        return await runner.run(ComputerTaskArgs(task="Continue the flow"))

    result = asyncio.run(scenario())
    assert result.status == "blocked"
    assert result.block_reason == "requires_login"
    assert result.next_user_action == "Log in, then rerun the task."


def test_runner_blocks_on_human_override():
    async def scenario() -> RunResult:
        adapter = FakeAdapter([make_png("blue")])
        model = SequenceModel(
            [
                make_decision(
                    "act",
                    "Click the button.",
                    actions=[ClickAction(x=100, y=80)],
                )
            ]
        )
        runner = make_runner(model, adapter, InterruptingMonitor(), monotonic_fn=lambda: 0.0)
        return await runner.run(ComputerTaskArgs(task="Click the thing"))

    result = asyncio.run(scenario())
    assert result.status == "blocked"
    assert result.block_reason == "human_override"


def test_runner_fails_on_invalid_model_output():
    async def scenario() -> RunResult:
        adapter = FakeAdapter([make_png("blue")])
        model = SequenceModel([ModelResponseError("bad json")])
        runner = make_runner(model, adapter, PassiveMonitor(), monotonic_fn=lambda: 0.0)
        return await runner.run(ComputerTaskArgs(task="Do something"))

    result = asyncio.run(scenario())
    assert result.status == "failed"
    assert "invalid decision" in result.summary.lower()


def test_runner_blocks_on_max_steps():
    async def scenario() -> RunResult:
        adapter = FakeAdapter([make_png("blue"), make_png("green")])
        model = SequenceModel(
            [
                make_decision(
                    "act",
                    "Click once.",
                    actions=[ClickAction(x=100, y=80)],
                )
            ]
        )
        runner = make_runner(
            model,
            adapter,
            PassiveMonitor(),
            max_steps_default=1,
            monotonic_fn=lambda: 0.0,
        )
        return await runner.run(ComputerTaskArgs(task="Continue", max_steps=1))

    result = asyncio.run(scenario())
    assert result.status == "blocked"
    assert result.block_reason == "max_steps"


def test_runner_blocks_on_timeout():
    async def scenario() -> RunResult:
        adapter = FakeAdapter([make_png("blue")])
        model = SequenceModel(
            [
                make_decision("completed", "done")
            ]
        )
        times = iter([0.0, 2.0])
        runner = make_runner(
            model,
            adapter,
            PassiveMonitor(),
            max_duration_s_default=1,
            monotonic_fn=lambda: next(times),
        )
        return await runner.run(ComputerTaskArgs(task="Continue"))

    result = asyncio.run(scenario())
    assert result.status == "blocked"
    assert result.block_reason == "timeout"


def test_runner_rejects_busy_second_task():
    async def scenario():
        adapter = FakeAdapter([make_png("blue"), make_png("green")])
        model = BlockingModel()
        runner = make_runner(model, adapter, PassiveMonitor(), monotonic_fn=lambda: 0.0)

        first = asyncio.create_task(runner.run(ComputerTaskArgs(task="First task")))
        await model.started.wait()
        second = asyncio.create_task(runner.run(ComputerTaskArgs(task="Second task")))
        await asyncio.sleep(0)
        model.release.set()
        first_result = await first
        second_result = await second
        return first_result, second_result

    first_result, second_result = asyncio.run(scenario())
    assert first_result.status == "failed"
    assert first_result.block_reason == "superseded"
    assert second_result.status == "completed"


def test_runner_accepts_multi_action_batch():
    async def scenario() -> RunResult:
        adapter = FakeAdapter([make_png("blue"), make_png("green")])
        model = SequenceModel(
            [
                make_decision(
                    "act",
                    "Focus then click.",
                    actions=[
                        ClickAction(x=100, y=80),
                        ClickAction(x=120, y=90),
                    ],
                ),
                make_decision("completed", "done"),
            ]
        )
        runner = make_runner(model, adapter, PassiveMonitor(), monotonic_fn=lambda: 0.0)
        return await runner.run(ComputerTaskArgs(task="Batch"))

    result = asyncio.run(scenario())
    assert result.status == "completed"
    assert result.steps_executed == 2


def test_runner_rejects_non_positive_max_steps():
    try:
        ComputerTaskArgs(task="Test", max_steps=0)
    except ValueError:
        return
    raise AssertionError("Expected ComputerTaskArgs to reject non-positive max_steps")


def test_worker_decision_rejects_result_for_act_status():
    try:
        make_decision(
            "act",
            "Do something",
            result="This should only appear at the end.",
            actions=[ClickAction(x=100, y=80)],
        )
    except ValueError:
        return
    raise AssertionError("Expected WorkerDecision to reject result for status=act")


def test_runner_reports_progress_and_wait_heartbeat():
    async def scenario():
        adapter = FakeAdapter([make_png("blue"), make_png("green")])
        model = SequenceModel(
            [
                make_decision(
                    "act",
                    "Wait for the page to load.",
                    actions=[WaitAction(ms=1200)],
                ),
                make_decision("completed", "done"),
            ]
        )
        runner = make_runner(model, adapter, PassiveMonitor(), monotonic_fn=lambda: 0.0)
        messages: list[str] = []

        async def progress_callback(progress: float, total: float | None, message: str) -> None:
            messages.append(message)

        result = await runner.run(
            ComputerTaskArgs(task="Wait for the page"),
            progress_callback=progress_callback,
        )
        return result, messages

    result, messages = asyncio.run(scenario())
    assert result.status == "completed"
    assert "Requesting vision worker for step 1" in messages
    assert "Received model decision for step 1" in messages
    assert any("Step 1 action 1/1: wait 1200ms" in message for message in messages)
    assert any("waiting 1200ms (" in message and "/1200ms)" in message for message in messages)
    assert "Capturing updated screen after step 1" in messages
    assert messages[-1] == "Finished"

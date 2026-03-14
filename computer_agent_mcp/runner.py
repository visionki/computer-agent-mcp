from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from hashlib import sha256
from io import BytesIO
import json
from threading import Event
import time
from typing import Awaitable, Callable
from uuid import uuid4

from PIL import Image, ImageDraw

from computer_agent_mcp.config import ServerConfig
from computer_agent_mcp.debug import DebugRecorder, RunDebugRecorder
from computer_agent_mcp.executor import ActionExecutor
from computer_agent_mcp.models import (
    ComputerAction,
    ComputerTaskArgs,
    CursorInfo,
    DesktopState,
    DisplayInfo,
    ModelPlanContext,
    RunResult,
)
from computer_agent_mcp.openai_adapter import ModelAdapter, ModelResponseError
from computer_agent_mcp.platform_base import DesktopAdapter


@dataclass(slots=True)
class _RunState:
    run_id: str
    task: str
    display_id: str
    max_steps: int
    warnings: list[str]
    history: list[str] = field(default_factory=list)
    stalled_action_signature: str | None = None
    stalled_count: int = 0


class ComputerAgentRunner:
    def __init__(
        self,
        config: ServerConfig,
        adapter: DesktopAdapter,
        executor: ActionExecutor,
        model_adapter: ModelAdapter,
        debug_recorder: DebugRecorder,
        startup_warnings: list[str] | None = None,
        monotonic_fn: Callable[[], float] = time.monotonic,
    ) -> None:
        self.config = config
        self.adapter = adapter
        self.executor = executor
        self.model_adapter = model_adapter
        self.debug_recorder = debug_recorder
        self.startup_warnings = list(startup_warnings or [])
        self._monotonic_fn = monotonic_fn
        self._run_lock = asyncio.Lock()
        self._state_lock = asyncio.Lock()
        self._latest_submission_id = 0
        self._active_cancel_event: Event | None = None

    async def run(
        self,
        request: ComputerTaskArgs,
        progress_callback: Callable[[float, float | None, str], Awaitable[None]] | None = None,
    ) -> RunResult:
        run_id = uuid4().hex[:12]
        run_debug = self.debug_recorder.create_run(run_id)
        async with self._state_lock:
            self._latest_submission_id += 1
            submission_id = self._latest_submission_id
            active_cancel_event = self._active_cancel_event
        if active_cancel_event is not None:
            active_cancel_event.set()

        async with self._run_lock:
            async with self._state_lock:
                if submission_id != self._latest_submission_id:
                    result = RunResult(
                        status="failed",
                        summary="This task was superseded by a newer request before it started.",
                        run_id=run_id,
                        steps_executed=0,
                        block_reason="superseded",
                        warnings=list(self.startup_warnings),
                    )
                    run_debug.record("run.superseded_before_start", result.model_dump(mode="json"))
                    return result
                cancel_event = Event()
                self._active_cancel_event = cancel_event
            try:
                return await self._run_locked(
                    request,
                    run_id,
                    run_debug,
                    progress_callback,
                    cancel_event=cancel_event,
                )
            finally:
                async with self._state_lock:
                    if self._active_cancel_event is cancel_event:
                        self._active_cancel_event = None

    async def _run_locked(
        self,
        request: ComputerTaskArgs,
        run_id: str,
        run_debug: RunDebugRecorder,
        progress_callback: Callable[[float, float | None, str], Awaitable[None]] | None,
        cancel_event: Event,
    ) -> RunResult:
        max_steps = request.max_steps if request.max_steps is not None else self.config.max_steps_default
        total_progress = float(max_steps * 4 + 4)
        progress_value = 0.0
        start_time = self._monotonic_fn()
        deadline_monotonic = start_time + self.config.max_duration_s_default
        state = _RunState(
            run_id=run_id,
            task=request.task,
            display_id=request.display_id,
            max_steps=max_steps,
            warnings=list(self.startup_warnings),
        )
        run_debug.record(
            "run.start",
            {
                "run_id": run_id,
                "task": request.task,
                "display_id": request.display_id,
                "max_steps": max_steps,
                "max_duration_s": self.config.max_duration_s_default,
            },
        )
        run_debug.write_text("task.txt", request.task)
        run_debug.write_json(
            "run_config.json",
            {
                "run_id": run_id,
                "display_id": request.display_id,
                "max_steps": max_steps,
                "max_duration_s": self.config.max_duration_s_default,
                "model": self.config.openai_model,
                "openai_base_url": self.config.openai_base_url,
                "startup_warnings": self.startup_warnings,
            },
        )

        async def emit_progress(message: str) -> None:
            nonlocal progress_value
            progress_value += 1.0
            if progress_callback is not None:
                await progress_callback(progress_value, total_progress, message)

        def was_superseded() -> bool:
            return cancel_event.is_set()

        try:
            await emit_progress("Capturing current screen")
            current_state = await self._capture_state(request.display_id, run_debug)
        except Exception as exc:
            return self._finish(
                run_debug,
                RunResult(
                    status="failed",
                    summary=f"Failed to capture the current screen: {exc}",
                    run_id=run_id,
                    warnings=list(self.startup_warnings),
                ),
            )

        steps_executed = 0
        for step_index in range(1, max_steps + 1):
            if was_superseded():
                return self._finish(
                    run_debug,
                    RunResult(
                        status="failed",
                        summary="Execution stopped because a newer task superseded this run.",
                        run_id=run_id,
                        steps_executed=steps_executed,
                        block_reason="superseded",
                        warnings=list(dict.fromkeys(self.startup_warnings + current_state.warnings)),
                    ),
                )
            if self.config.kill_switch_active():
                return self._finish(
                    run_debug,
                    RunResult(
                        status="blocked",
                        summary="Execution stopped by the configured kill switch.",
                        run_id=run_id,
                        steps_executed=steps_executed,
                        block_reason="environment_error",
                        next_user_action="Remove the kill switch and rerun the task from the current screen.",
                        warnings=list(dict.fromkeys(self.startup_warnings + current_state.warnings)),
                    ),
                )
            if self._monotonic_fn() > deadline_monotonic:
                return self._finish(
                    run_debug,
                    RunResult(
                        status="blocked",
                        summary="The task hit the configured time limit before completion.",
                        run_id=run_id,
                        steps_executed=steps_executed,
                        block_reason="timeout",
                        next_user_action="Submit a new task from the current screen if more work is needed.",
                        warnings=list(dict.fromkeys(self.startup_warnings + current_state.warnings)),
                    ),
                )

            context = ModelPlanContext(
                run_id=run_id,
                task=request.task,
                step_index=step_index,
                max_steps=max_steps,
                recent_history=list(state.history[-4:]),
                warnings=list(dict.fromkeys(self.startup_warnings + current_state.warnings)),
            )
            await emit_progress(f"Planning step {step_index}")
            try:
                decision = await self.model_adapter.plan_step(context, current_state, run_debug)
            except ModelResponseError as exc:
                return self._finish(
                    run_debug,
                    RunResult(
                        status="failed",
                        summary=f"Vision worker returned an invalid decision: {exc}",
                        run_id=run_id,
                        steps_executed=steps_executed,
                        warnings=list(dict.fromkeys(self.startup_warnings + current_state.warnings)),
                    ),
                )
            except Exception as exc:
                return self._finish(
                    run_debug,
                    RunResult(
                        status="failed",
                        summary=f"Vision worker request failed: {exc}",
                        run_id=run_id,
                        steps_executed=steps_executed,
                        warnings=list(dict.fromkeys(self.startup_warnings + current_state.warnings)),
                    ),
                )
            if was_superseded():
                return self._finish(
                    run_debug,
                    RunResult(
                        status="failed",
                        summary="Execution stopped because a newer task superseded this run.",
                        run_id=run_id,
                        steps_executed=steps_executed,
                        block_reason="superseded",
                        warnings=list(dict.fromkeys(self.startup_warnings + current_state.warnings)),
                    ),
                )

            run_debug.record(
                "runner.decision",
                {
                    "step_index": step_index,
                    "decision": decision.model_dump(mode="json", by_alias=True),
                },
            )
            state.history.append(
                "Step "
                f"{step_index}: {decision.summary} "
                f"[image={decision.image_width}x{decision.image_height}]"
            )

            if decision.status == "completed":
                return self._finish(
                    run_debug,
                    RunResult(
                        status="completed",
                        summary=decision.summary,
                        run_id=run_id,
                        steps_executed=steps_executed,
                        warnings=list(dict.fromkeys(self.startup_warnings + current_state.warnings)),
                    ),
                )
            if decision.status == "blocked":
                return self._finish(
                    run_debug,
                    RunResult(
                        status="blocked",
                        summary=decision.summary,
                        run_id=run_id,
                        steps_executed=steps_executed,
                        block_reason=decision.block_reason or "needs_human_input",
                        next_user_action=decision.next_user_action,
                        warnings=list(dict.fromkeys(self.startup_warnings + current_state.warnings)),
                    ),
                )
            if decision.status == "failed":
                return self._finish(
                    run_debug,
                    RunResult(
                        status="failed",
                        summary=decision.summary,
                        run_id=run_id,
                        steps_executed=steps_executed,
                        warnings=list(dict.fromkeys(self.startup_warnings + current_state.warnings)),
                    ),
                )

            run_debug.record(
                "runner.action_selected",
                {
                    "step_index": step_index,
                    "actions": [action.model_dump(mode="json", by_alias=True) for action in decision.actions],
                    "model_image_size": [decision.image_width, decision.image_height],
                    "mapping": [
                        self.executor.mapping_preview(
                            current_state,
                            action,
                            source_width=decision.image_width,
                            source_height=decision.image_height,
                        )
                        for action in decision.actions
                    ],
                },
                image_bytes=self._actions_overlay(
                    current_state,
                    decision.actions,
                    source_width=decision.image_width,
                    source_height=decision.image_height,
                ),
            )

            await emit_progress(f"Executing step {step_index} ({len(decision.actions)} action(s))")
            for action_index, action in enumerate(decision.actions, start=1):
                execution = await asyncio.to_thread(
                    self.executor.execute,
                    current_state,
                    action,
                    source_width=decision.image_width,
                    source_height=decision.image_height,
                    deadline_monotonic=deadline_monotonic,
                    cancel_event=cancel_event,
                )
                run_debug.record(
                    "runner.action_result",
                    {
                        "step_index": step_index,
                        "action_index": action_index,
                        "action_count": len(decision.actions),
                        "result": {
                            "status": execution.status,
                            "message": execution.message,
                            "block_reason": execution.block_reason,
                            "intervention": execution.intervention.model_dump(mode="json")
                            if execution.intervention
                            else None,
                            "mapping": execution.mapping,
                        },
                    },
                )
                if execution.status == "blocked":
                    status = "blocked"
                    if execution.block_reason == "superseded":
                        status = "failed"
                    return self._finish(
                        run_debug,
                        RunResult(
                            status=status,
                            summary=execution.message or "The run was interrupted.",
                            run_id=run_id,
                            steps_executed=steps_executed,
                            block_reason=execution.block_reason or "environment_error",
                            next_user_action=(
                                None
                                if execution.block_reason == "superseded"
                                else "Inspect the desktop and submit a new task from the current screen."
                            ),
                            warnings=list(dict.fromkeys(self.startup_warnings + current_state.warnings)),
                        ),
                    )
                if execution.status == "failed":
                    return self._finish(
                        run_debug,
                        RunResult(
                            status="failed",
                            summary=execution.message or "Failed to execute the planned action.",
                            run_id=run_id,
                            steps_executed=steps_executed,
                            warnings=list(dict.fromkeys(self.startup_warnings + current_state.warnings)),
                        ),
                    )
                steps_executed += 1

            previous_hash = current_state.image_sha256
            action_signature = self._actions_signature(decision.actions)
            if was_superseded():
                return self._finish(
                    run_debug,
                    RunResult(
                        status="failed",
                        summary="Execution stopped because a newer task superseded this run.",
                        run_id=run_id,
                        steps_executed=steps_executed,
                        block_reason="superseded",
                        warnings=list(dict.fromkeys(self.startup_warnings + current_state.warnings)),
                    ),
                )
            await emit_progress(f"Capturing screen after step {step_index}")
            try:
                current_state = await self._capture_state(request.display_id, run_debug)
            except Exception as exc:
                return self._finish(
                    run_debug,
                    RunResult(
                        status="failed",
                        summary=f"Failed to capture the screen after executing an action: {exc}",
                        run_id=run_id,
                        steps_executed=steps_executed,
                        warnings=list(dict.fromkeys(self.startup_warnings + current_state.warnings)),
                    ),
                )

            if current_state.image_sha256 == previous_hash:
                if state.stalled_action_signature == action_signature:
                    state.stalled_count += 1
                else:
                    state.stalled_action_signature = action_signature
                    state.stalled_count = 1
                unchanged_note = (
                    f"Step {step_index}: screen unchanged after batch "
                    f"(repeat_count={state.stalled_count})."
                )
                state.history.append(unchanged_note)
                run_debug.record(
                    "runner.screen_unchanged",
                    {
                        "step_index": step_index,
                        "repeat_count": state.stalled_count,
                        "actions_signature": action_signature,
                    },
                )
            else:
                state.stalled_action_signature = None
                state.stalled_count = 0

        return self._finish(
            run_debug,
            RunResult(
                status="blocked",
                summary=f"Paused after reaching the configured step limit ({max_steps}).",
                run_id=run_id,
                steps_executed=steps_executed,
                block_reason="max_steps",
                next_user_action="Rerun the task from the current screen if more work is needed.",
                warnings=list(dict.fromkeys(self.startup_warnings + current_state.warnings)),
            ),
        )

    async def _capture_state(self, display_id: str, run_debug: RunDebugRecorder) -> DesktopState:
        captured = await asyncio.to_thread(
            self.adapter.capture_display,
            display_id,
            self.config.include_cursor_by_default,
        )
        state = DesktopState(
            display_id=display_id,
            display=captured.display,
            cursor=captured.cursor,
            active_app=captured.active_app,
            active_window_title=captured.active_window_title,
            screenshot_png=captured.png_bytes,
            image_sha256=sha256(captured.png_bytes).hexdigest(),
            warnings=list(self.startup_warnings),
        )
        run_debug.record(
            "runner.capture",
            {
                "display_id": display_id,
                "display": state.display.model_dump(mode="json"),
                "cursor": state.cursor.model_dump(mode="json") if state.cursor else None,
                "active_window_title": state.active_window_title,
                "active_app": state.active_app,
                "warnings": state.warnings,
            },
            image_bytes=state.screenshot_png,
        )
        return state

    def _actions_signature(self, actions: list[ComputerAction]) -> str:
        payload = [action.model_dump(mode="json", by_alias=True) for action in actions]
        return json.dumps(payload, ensure_ascii=False, sort_keys=True)

    def _actions_overlay(
        self,
        state: DesktopState,
        actions: list[ComputerAction],
        *,
        source_width: int,
        source_height: int,
    ) -> bytes:
        image = Image.open(BytesIO(state.screenshot_png)).convert("RGB")
        draw = ImageDraw.Draw(image)
        colors = ["lime", "yellow", "cyan", "magenta", "orange", "white"]

        def to_capture_coords(x: int, y: int) -> tuple[int, int]:
            mapped_x = int(round(x * state.display.width_px / max(source_width, 1)))
            mapped_y = int(round(y * state.display.height_px / max(source_height, 1)))
            return mapped_x, mapped_y

        for index, action in enumerate(actions):
            color = colors[index % len(colors)]
            if hasattr(action, "x") and hasattr(action, "y"):
                x, y = to_capture_coords(int(getattr(action, "x")), int(getattr(action, "y")))
                draw.ellipse((x - 12, y - 12, x + 12, y + 12), outline=color, width=3)
                draw.line((x - 18, y, x + 18, y), fill=color, width=2)
                draw.line((x, y - 18, x, y + 18), fill=color, width=2)
            elif action.type == "drag":
                start = to_capture_coords(action.from_point.x, action.from_point.y)
                end = to_capture_coords(action.to.x, action.to.y)
                draw.line((start[0], start[1], end[0], end[1]), fill=color, width=3)
                draw.ellipse((start[0] - 8, start[1] - 8, start[0] + 8, start[1] + 8), outline=color, width=3)
                draw.ellipse((end[0] - 8, end[1] - 8, end[0] + 8, end[1] + 8), outline=color, width=3)
        buffer = BytesIO()
        image.save(buffer, format="PNG")
        return buffer.getvalue()

    def _finish(self, run_debug: RunDebugRecorder, result: RunResult) -> RunResult:
        run_debug.record("run.finish", result.model_dump(mode="json"))
        run_debug.write_json("result.json", result.model_dump(mode="json"))
        return result

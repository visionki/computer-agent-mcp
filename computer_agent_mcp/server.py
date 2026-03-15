from __future__ import annotations

from argparse import ArgumentParser
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
import logging
import os

from mcp.server.fastmcp import Context, FastMCP
from mcp.types import CallToolResult, TextContent

from computer_agent_mcp.config import ServerConfig
from computer_agent_mcp.debug import DebugRecorder
from computer_agent_mcp.executor import ActionExecutor
from computer_agent_mcp.models import ComputerTaskArgs, DisplayListResult, RunResult
from computer_agent_mcp.monitor import HumanOverrideMonitor
from computer_agent_mcp.openai_adapter import OpenAIResponsesModelAdapter
from computer_agent_mcp.platform import create_adapter
from computer_agent_mcp.runner import ComputerAgentRunner


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

_CONFIG_OVERRIDES: dict[str, object] = {}


@dataclass(slots=True)
class AppContext:
    config: ServerConfig
    adapter: object
    monitor: HumanOverrideMonitor
    executor: ActionExecutor
    debug_recorder: DebugRecorder
    runner: ComputerAgentRunner
    startup_warnings: list[str]


def _text_result(structured_model, text_summary: str, *, is_error: bool = False) -> CallToolResult:
    return CallToolResult(
        content=[TextContent(type="text", text=text_summary)],
        structuredContent=structured_model.model_dump(mode="json"),
        isError=is_error,
    )


def _format_run_result_text(result: RunResult) -> str:
    lines = [
        result.summary,
    ]
    if result.result:
        lines.extend(["", result.result])
    lines.extend(
        [
            "",
            f"status: {result.status}",
            f"run_id: {result.run_id}",
            f"steps_executed: {result.steps_executed}",
        ]
    )
    if result.memory:
        lines.extend(["", "memory:"])
        lines.extend(f"- {item}" for item in result.memory)
    if result.trace:
        lines.append("trace:")
        for index, trace_step in enumerate(result.trace, start=1):
            if index > 1:
                lines.append("")
            lines.append(f"Step {trace_step.step_index}")
            if trace_step.observation:
                lines.append(f"observation: {trace_step.observation}")
            if trace_step.memory_update:
                lines.append(f"memory_update: {trace_step.memory_update}")
            lines.append(f"summary: {trace_step.summary}")
            if trace_step.actions:
                action_text = "; ".join(
                    ComputerAgentRunner._describe_action(action) for action in trace_step.actions
                )
            else:
                action_text = "none"
            lines.append(f"actions: {action_text}")
            if trace_step.expected_outcome:
                lines.append(f"expected_outcome: {trace_step.expected_outcome}")
            lines.append(f"execution_status: {trace_step.execution_status or 'unknown'}")
            if trace_step.execution_message:
                lines.append(f"execution_message: {trace_step.execution_message}")
            lines.append(
                f"resulting_window_title: {trace_step.resulting_window_title or 'unknown'}"
            )
    if result.next_user_action:
        lines.extend(["", f"next_user_action: {result.next_user_action}"])
    if result.warnings:
        lines.extend(["", "warnings:"])
        lines.extend(f"- {warning}" for warning in result.warnings)
    return "\n".join(lines)


def build_arg_parser() -> ArgumentParser:
    parser = ArgumentParser(description="computer-agent-mcp server")
    parser.add_argument("--api-key", dest="openai_api_key", default=None)
    parser.add_argument("--base-url", dest="openai_base_url", default=None)
    parser.add_argument("--model", dest="openai_model", default=None)
    parser.add_argument("--user-agent", dest="openai_user_agent", default=None)
    parser.add_argument("--openai-timeout-seconds", type=int, default=None)
    parser.add_argument("--max-steps-default", type=int, default=None)
    parser.add_argument("--max-duration-s-default", type=int, default=None)
    parser.add_argument("--debug-dir", default=None)
    parser.add_argument("--log-level", default=None)
    parser.add_argument("--kill-switch-file", default=None)
    return parser


@asynccontextmanager
async def app_lifespan(_server: FastMCP):
    config = ServerConfig.from_env(_CONFIG_OVERRIDES)
    monitor = HumanOverrideMonitor(
        threshold_px=config.mouse_interrupt_threshold_px,
        enabled=config.human_override_enabled,
    )
    monitor.start()
    adapter = create_adapter(monitor.filter)
    startup_warnings: list[str] = []
    if monitor.startup_warning:
        startup_warnings.append(monitor.startup_warning)
    startup_warnings.extend(adapter.startup_warnings())
    debug_recorder = DebugRecorder(
        enabled=config.debug_enabled,
        base_dir=Path(config.debug_dir),
        save_images=config.debug_save_images,
    )
    executor = ActionExecutor(
        adapter=adapter,
        monitor=monitor,
        config=config,
    )
    model_adapter = OpenAIResponsesModelAdapter(config=config)
    runner = ComputerAgentRunner(
        config=config,
        adapter=adapter,
        executor=executor,
        model_adapter=model_adapter,
        debug_recorder=debug_recorder,
        startup_warnings=startup_warnings,
    )
    yield AppContext(
        config=config,
        adapter=adapter,
        monitor=monitor,
        executor=executor,
        debug_recorder=debug_recorder,
        runner=runner,
        startup_warnings=startup_warnings,
    )
    monitor.stop()


mcp = FastMCP(
    name="computer-agent-mcp",
    instructions=(
        "This server exposes a stateless black-box computer-use task tool. "
        "Use computer_use_task for desktop work. Each call starts fresh from the current screen and must fully describe the task. "
        "The server does not keep resumable task state across calls, and a newer task may supersede an older in-flight task. "
        "If a run stops with block_reason=human_override, do not automatically retry. Ask the user what changed and whether to continue from the current screen."
    ),
    lifespan=app_lifespan,
)


@mcp.tool(
    description=(
        "List available displays. Use this only when you need to target a non-primary monitor. "
        "Most callers can rely on computer_use_task(display_id='primary')."
    )
)
async def computer_list_displays(ctx: Context) -> CallToolResult:
    app: AppContext = ctx.request_context.lifespan_context
    displays = app.adapter.list_displays()
    result = DisplayListResult(
        platform=app.adapter.platform_name,
        displays=displays,
        warnings=list(app.startup_warnings),
    )
    return _text_result(
        result,
        text_summary=f"{len(displays)} display(s) available on {app.adapter.platform_name}.",
    )


@mcp.tool(
    description=(
        "Run a stateless black-box computer-use task on the local desktop. "
        "The server captures the current screen, plans actions with an internal vision model, executes locally, "
        "and returns only the task-level result. Each call must describe the full task from the current screen. "
        "If the result is blocked with block_reason=human_override, the caller should stop and ask the user why they intervened before deciding whether to call the tool again."
    )
)
async def computer_use_task(
    task: str,
    display_id: str = "primary",
    max_steps: int | None = None,
    ctx: Context | None = None,
) -> CallToolResult:
    assert ctx is not None
    app: AppContext = ctx.request_context.lifespan_context
    request = ComputerTaskArgs.model_validate(
        {
            "task": task,
            "display_id": display_id,
            "max_steps": max_steps,
        }
    )

    async def progress_callback(progress: float, total: float | None, message: str) -> None:
        await ctx.report_progress(progress, total, message=message)

    result: RunResult = await app.runner.run(request, progress_callback=progress_callback)
    return _text_result(
        result,
        text_summary=_format_run_result_text(result),
        is_error=result.status == "failed",
    )


def main() -> None:
    global _CONFIG_OVERRIDES

    parser = build_arg_parser()
    args = parser.parse_args()
    if args.max_steps_default is not None and args.max_steps_default <= 0:
        parser.error("--max-steps-default must be positive")
    if args.max_duration_s_default is not None and args.max_duration_s_default <= 0:
        parser.error("--max-duration-s-default must be positive")

    api_key = (
        args.openai_api_key
        or os.getenv("COMPUTER_AGENT_OPENAI_API_KEY")
        or os.getenv("OPENAI_API_KEY")
    )
    if not api_key:
        parser.error(
            "missing OpenAI API key. Provide --api-key or set COMPUTER_AGENT_OPENAI_API_KEY / OPENAI_API_KEY. "
            "base-url defaults to https://api.openai.com/v1 and model defaults to gpt-5.4."
        )

    _CONFIG_OVERRIDES = {
        "openai_api_key": api_key,
        "openai_base_url": args.openai_base_url,
        "openai_model": args.openai_model,
        "openai_user_agent": args.openai_user_agent,
        "openai_timeout_seconds": args.openai_timeout_seconds,
        "max_steps_default": args.max_steps_default,
        "max_duration_s_default": args.max_duration_s_default,
        "debug_dir": args.debug_dir,
        "log_level": args.log_level,
        "kill_switch_file": args.kill_switch_file,
    }

    mcp.run(transport="stdio")

from __future__ import annotations

from computer_agent_mcp.config import ServerConfig
from computer_agent_mcp.models import DesktopState, ModelPlanContext


def build_worker_instructions(config: ServerConfig) -> str:
    return f"""You are the internal desktop worker for a black-box MCP server.
Return exactly one JSON object and nothing else.

Schema:
{{
  "status": "act" | "completed" | "blocked" | "failed",
  "summary": "short string",
  "image_width": 1234,
  "image_height": 567,
  "actions": [],
  "block_reason": "requires_login" | "requires_captcha" | "requires_confirmation" | "needs_human_input" | "human_override" | "environment_error" | "ambiguous" | null,
  "next_user_action": "string or null"
}}

Rules:
- When status is "act", actions must contain one or more actions.
- When status is not "act", actions must be an empty array.
- Always include image_width and image_height as the width and height of the image space you are actually using for coordinates in this response.
- Use only coordinates from that reported image space.
- Prefer keyboard shortcuts when reliable.
- Do not refer to hidden UI, old screenshots, or tools that do not exist.
- Do not ask the external host to inspect the screenshot; it cannot see the image.
- Use "blocked" only when you cannot continue reliably without human information, human intervention, or a stable environment change.
- Use "completed" only when the task goal is done.
- Use "failed" only for unrecoverable execution problems.
- Keep summary concise and factual.
- If you use a type action, keep each text payload at or below {config.max_type_chars} characters.

Allowed actions:
- {{"type":"move","x":123,"y":456,"duration_ms":120}}
- {{"type":"click","x":123,"y":456,"button":"left"}}
- {{"type":"double_click","x":123,"y":456}}
- {{"type":"right_click","x":123,"y":456}}
- {{"type":"drag","from":{{"x":100,"y":200}},"to":{{"x":300,"y":400}},"duration_ms":250}}
- {{"type":"scroll","x":123,"y":456,"delta_x":0,"delta_y":-600}}
- {{"type":"type","text":"hello"}}
- {{"type":"keypress","keys":["CTRL","L"]}}
- {{"type":"wait","ms":1000}}
"""


def build_worker_user_message(context: ModelPlanContext, state: DesktopState) -> str:
    history = context.recent_history[-6:]
    history_text = "\n".join(f"- {item}" for item in history) if history else "- none"
    return f"""Task:
{context.task}

Current step:
- step_index: {context.step_index}
- max_steps: {context.max_steps}

Current screen:
- display_id: {state.display_id}
- screenshot_width: {state.display.width_px}
- screenshot_height: {state.display.height_px}
- active_window_title: {state.active_window_title or "unknown"}
- active_app: {state.active_app or "unknown"}

Recent history:
{history_text}

Decide the best next actions from the current screenshot only.
If the task is already done, return status="completed".
If you genuinely need human help or missing information, return status="blocked".
"""

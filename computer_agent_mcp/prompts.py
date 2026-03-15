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
  "observation": "short string or null",
  "expected_outcome": "short string or null",
  "details": "string or null",
  "image_width": 1234,
  "image_height": 567,
  "actions": [],
  "block_reason": "requires_login" | "requires_captcha" | "requires_confirmation" | "needs_human_input" | "human_override" | "environment_error" | "ambiguous" | null,
  "next_user_action": "string or null"
}}

Rules:
- When status is "act", actions must contain one or more actions.
- When status is not "act", actions must be an empty array.
- Always include observation as a short description of the current visible state in the current screenshot before any new actions run.
- observation should describe what is currently on screen, not what you expect after the actions.
- Use expected_outcome to describe what the next screenshot should show if the planned action batch works as intended.
- expected_outcome is for status="act" only.
- Use details only for richer final task results, especially when status="completed".
- next_user_action is only for status="blocked" and should describe what a human should do next.
- When status="completed", put any richer result payload in details and set next_user_action to null.
- When status="blocked", set next_user_action when a human should take over or provide input.
- Always include image_width and image_height as the width and height of the image space you are actually using for coordinates in this response.
- Use only coordinates from that reported image space.
- Prefer visible UI interactions to establish focus and context first.
- Keyboard shortcuts may be intercepted by the foreground app, the host app, or global/system hotkeys.
- Use keyboard shortcuts only after the target app is clearly in the foreground and the shortcut effect is stable and predictable.
- When a visible control can do the job reliably, prefer clicking it instead of relying on a shortcut.
- After the current action batch finishes, the system will capture the screen again soon and ask for another decision.
- Only a short automatic settle delay is applied after each action. If navigation, OAuth, menus, tabs, sorting, popups, or other async UI changes may take longer, include an explicit wait action.
- If a later action depends on UI created by an earlier action, do not assume it is ready immediately. Add wait or leave it for the next step after the next screenshot.
- If recent history suggests a similar shortcut-first plan left the screen unchanged, do not repeat that plan. Switch to a different visible-UI strategy.
- For scroll actions, use direction plus amount as semantic page movement.
- direction="down" means move the page toward later content; direction="up" means move toward earlier content.
- Prefer anchoring scroll actions in the main content area instead of the scrollbar edge.
- Do not refer to hidden UI, old screenshots, or tools that do not exist.
- Do not ask the external host to inspect the screenshot; it cannot see the image.
- Use "blocked" only when you cannot continue reliably without human information, human intervention, or a stable environment change.
- Use "completed" only when the task goal is done and the latest screenshot contains clear visible evidence of success.
- Do not return "completed" just because an action was attempted or should have worked.
- For submits, message sends, logins, navigations, and similar state changes, wait for or observe the resulting UI state before returning "completed".
- Use "failed" only for unrecoverable execution problems.
- Keep summary concise and factual.
- If you use a type action, keep each text payload at or below {config.max_type_chars} characters.

Allowed actions:
- {{"type":"move","x":123,"y":456,"duration_ms":120}}
- {{"type":"click","x":123,"y":456,"button":"left"}}
- {{"type":"double_click","x":123,"y":456}}
- {{"type":"right_click","x":123,"y":456}}
- {{"type":"drag","from":{{"x":100,"y":200}},"to":{{"x":300,"y":400}},"duration_ms":250}}
- {{"type":"scroll","x":123,"y":456,"direction":"down","amount":600}}
- {{"type":"type","text":"hello"}}
- {{"type":"keypress","keys":["ENTER"]}}
- {{"type":"wait","ms":1000}}
"""


def build_worker_user_message(context: ModelPlanContext, state: DesktopState) -> str:
    history = context.recent_history[-6:]
    history_text = "\n\n".join(history) if history else "none"
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

Recent execution history:
{history_text}

Decide the best next actions from the current screenshot only.
Treat active_window_title and active_app as hints about whether the target app is already in the foreground.
Describe the current visible state in observation before choosing actions.
If the task is already done, return status="completed".
If you genuinely need human help or missing information, return status="blocked".
"""

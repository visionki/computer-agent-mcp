from __future__ import annotations

from abc import ABC, abstractmethod
from base64 import b64encode
from dataclasses import dataclass
from typing import Any

from computer_agent_mcp.config import ServerConfig
from computer_agent_mcp.debug import RunDebugRecorder
from computer_agent_mcp.models import DesktopState, ModelPlanContext, WorkerDecision
from computer_agent_mcp.prompts import build_worker_instructions, build_worker_user_message
from computer_agent_mcp.response_parsing import extract_json_object, extract_output_text


class ModelResponseError(RuntimeError):
    pass


class ModelAdapter(ABC):
    @abstractmethod
    async def plan_step(
        self,
        context: ModelPlanContext,
        state: DesktopState,
        debug_recorder: RunDebugRecorder,
    ) -> WorkerDecision: ...


@dataclass(slots=True)
class OpenAIResponsesModelAdapter(ModelAdapter):
    config: ServerConfig
    _client: Any | None = None

    async def plan_step(
        self,
        context: ModelPlanContext,
        state: DesktopState,
        debug_recorder: RunDebugRecorder,
    ) -> WorkerDecision:
        user_message = build_worker_user_message(context, state)
        debug_recorder.write_text(f"step_{context.step_index:02d}_prompt.txt", user_message)

        client = self._get_client()
        image_url = f"data:image/png;base64,{b64encode(state.screenshot_png).decode('ascii')}"
        response = await client.responses.create(
            model=self.config.openai_model,
            instructions=build_worker_instructions(self.config),
            input=[
                {
                    "role": "user",
                    "content": [
                        {"type": "input_text", "text": user_message},
                        {"type": "input_image", "image_url": image_url, "detail": "original"},
                    ],
                }
            ],
        )
        response_dict = self._response_to_dict(response)
        response_text = extract_output_text(response_dict)
        payload = extract_json_object(response_text)
        debug_recorder.write_json(
            f"step_{context.step_index:02d}_response.json",
            {
                "response_id": response_dict.get("id"),
                "text": response_text,
                "output_types": [item.get("type") for item in response_dict.get("output", [])],
                "usage": response_dict.get("usage"),
            },
        )
        if payload is None:
            raise ModelResponseError("Model did not return a parseable JSON decision.")
        try:
            return WorkerDecision.model_validate(payload)
        except Exception as exc:
            raise ModelResponseError(f"Model returned an invalid decision payload: {exc}") from exc

    def _get_client(self):
        if self._client is not None:
            return self._client
        if not self.config.openai_api_key:
            raise RuntimeError("OPENAI_API_KEY or COMPUTER_AGENT_OPENAI_API_KEY is required.")
        try:
            from openai import AsyncOpenAI
        except Exception as exc:
            raise RuntimeError("The openai package is required.") from exc
        default_headers = None
        if self.config.openai_user_agent:
            default_headers = {"User-Agent": self.config.openai_user_agent}
        self._client = AsyncOpenAI(
            api_key=self.config.openai_api_key,
            base_url=self.config.openai_base_url,
            timeout=self.config.openai_timeout_seconds,
            default_headers=default_headers,
        )
        return self._client

    @staticmethod
    def _response_to_dict(response: Any) -> dict[str, Any]:
        if isinstance(response, dict):
            return response
        if hasattr(response, "model_dump"):
            return response.model_dump(mode="json")
        if hasattr(response, "to_dict"):
            return response.to_dict()
        raise TypeError(f"Unsupported response object: {type(response)!r}")

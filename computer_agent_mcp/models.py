from __future__ import annotations

from dataclasses import dataclass, field
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


TaskStatus = Literal["completed", "blocked", "failed"]
WorkerStatus = Literal["act", "completed", "blocked", "failed"]


class Point(BaseModel):
    x: int
    y: int


class DisplayInfo(BaseModel):
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
    coordinate_space: Literal["screenshot_pixels"] = "screenshot_pixels"


class CursorInfo(BaseModel):
    x: int
    y: int
    visible: bool = True


class DisplayListResult(BaseModel):
    platform: str
    displays: list[DisplayInfo]
    warnings: list[str] = Field(default_factory=list)


class ComputerTaskArgs(BaseModel):
    task: str
    display_id: str = "primary"
    max_steps: int | None = None

    @model_validator(mode="after")
    def _validate_task(self) -> "ComputerTaskArgs":
        self.task = self.task.strip()
        if not self.task:
            raise ValueError("task must not be empty")
        if self.max_steps is not None and self.max_steps <= 0:
            raise ValueError("max_steps must be positive when provided")
        return self


class RunResult(BaseModel):
    status: TaskStatus
    summary: str
    run_id: str
    steps_executed: int = 0
    block_reason: str | None = None
    next_user_action: str | None = None
    warnings: list[str] = Field(default_factory=list)


class MoveAction(BaseModel):
    type: Literal["move"] = "move"
    x: int
    y: int
    duration_ms: int = 120


class ClickAction(BaseModel):
    type: Literal["click"] = "click"
    x: int
    y: int
    button: Literal["left", "middle", "right"] = "left"


class DoubleClickAction(BaseModel):
    type: Literal["double_click"] = "double_click"
    x: int
    y: int


class RightClickAction(BaseModel):
    type: Literal["right_click"] = "right_click"
    x: int
    y: int


class DragAction(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    type: Literal["drag"] = "drag"
    from_point: Point = Field(alias="from")
    to: Point
    duration_ms: int = 250


class ScrollAction(BaseModel):
    type: Literal["scroll"] = "scroll"
    x: int
    y: int
    delta_x: int = 0
    delta_y: int = 0


class TypeAction(BaseModel):
    type: Literal["type"] = "type"
    text: str


class KeypressAction(BaseModel):
    type: Literal["keypress"] = "keypress"
    keys: list[str]


class WaitAction(BaseModel):
    type: Literal["wait"] = "wait"
    ms: int


ComputerAction = Annotated[
    MoveAction
    | ClickAction
    | DoubleClickAction
    | RightClickAction
    | DragAction
    | ScrollAction
    | TypeAction
    | KeypressAction
    | WaitAction,
    Field(discriminator="type"),
]


class WorkerDecision(BaseModel):
    status: WorkerStatus
    summary: str
    image_width: int = Field(ge=1)
    image_height: int = Field(ge=1)
    actions: list[ComputerAction] = Field(default_factory=list)
    block_reason: str | None = None
    next_user_action: str | None = None

    @model_validator(mode="after")
    def _validate_status(self) -> "WorkerDecision":
        if self.status == "act":
            if not self.actions:
                raise ValueError("status=act requires one or more actions")
        elif self.actions:
            raise ValueError("Only status=act may include actions")
        return self


class InterventionInfo(BaseModel):
    event_type: Literal["keyboard", "mouse_click", "mouse_move", "scroll"]
    key: str | None = None
    x: int | None = None
    y: int | None = None
    timestamp: str


@dataclass(slots=True)
class DesktopState:
    display_id: str
    display: DisplayInfo
    cursor: CursorInfo | None
    active_app: str | None
    active_window_title: str | None
    screenshot_png: bytes
    image_sha256: str
    warnings: list[str] = field(default_factory=list)


@dataclass(slots=True)
class ModelPlanContext:
    run_id: str
    task: str
    step_index: int
    max_steps: int
    recent_history: list[str]
    warnings: list[str]


@dataclass(slots=True)
class ActionExecutionResult:
    status: Literal["ok", "blocked", "failed"]
    message: str | None = None
    block_reason: str | None = None
    intervention: InterventionInfo | None = None
    mapping: dict | None = None

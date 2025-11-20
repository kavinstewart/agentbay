from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from app.enums import FlowStatus, FlowType, TaskStatus, WorkerStatus


class WorkerCreate(BaseModel):
    label: str | None = None


class WorkerRead(BaseModel):
    model_config = {"from_attributes": True}

    id: str
    label: str | None
    status: WorkerStatus
    tmux_session: str
    workspace_path: str
    ttyd_url: str | None
    created_at: datetime
    last_seen_at: datetime


class TaskCreate(BaseModel):
    tool: str
    spec: dict[str, Any] = Field(default_factory=dict)
    flow_id: str | None = None


class TaskRead(BaseModel):
    model_config = {"from_attributes": True}

    id: str
    worker_id: str
    tool: str
    status: TaskStatus
    spec_json: dict[str, Any]
    result_json: dict[str, Any] | None
    error_message: str | None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None


class FlowCreate(BaseModel):
    worker_id: str
    initial_prompt: str
    max_iterations: int = 6
    min_score: int = 9


class FlowRead(BaseModel):
    model_config = {"from_attributes": True}

    id: str
    type: FlowType
    status: FlowStatus
    worker_id: str
    config: dict[str, Any]
    state: dict[str, Any]
    result: dict[str, Any] | None
    created_at: datetime
    updated_at: datetime | None

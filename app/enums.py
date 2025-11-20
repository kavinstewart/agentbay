from __future__ import annotations

from enum import Enum


class WorkerStatus(str, Enum):
    idle = "idle"
    busy = "busy"
    error = "error"
    terminated = "terminated"


class TaskStatus(str, Enum):
    queued = "queued"
    running = "running"
    completed = "completed"
    failed = "failed"


class TaskEventType(str, Enum):
    stdout_chunk = "stdout_chunk"
    stderr_chunk = "stderr_chunk"
    state_change = "state_change"
    result_parsed = "result_parsed"


class FlowStatus(str, Enum):
    running = "running"
    completed = "completed"
    failed = "failed"


class FlowType(str, Enum):
    design_refinement = "design_refinement"

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from shlex import quote
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.enums import TaskEventType, TaskStatus, WorkerStatus
from app.models import Task, TaskEvent, Worker
from app.schemas import TaskCreate
from app.services import runtime_registry
from app.utils.paths import SHIMS_DIR

TOOL_SHIMS: dict[str, str] = {
    "codex": "run_codex_task.sh",
    "claude": "run_claude_task.sh",
    "gemini": "run_gemini_task.sh",
    "critic_llm": "run_critic_task.sh",
}


def _build_command(tool: str, spec_path: Path) -> str:
    shim = TOOL_SHIMS.get(tool)
    if not shim:
        raise ValueError(f"Unsupported tool '{tool}'")
    script_path = SHIMS_DIR / shim
    return f"bash {quote(str(script_path))} {quote(str(spec_path))}"


async def create_task(session: AsyncSession, worker_id: str, payload: TaskCreate) -> Task:
    worker = await session.get(Worker, worker_id)
    if not worker:
        raise ValueError("Worker not found")
    spec_json = payload.spec
    task = Task(worker_id=worker_id, tool=payload.tool, spec_json=spec_json, flow_id=payload.flow_id)
    session.add(task)
    await session.flush()

    workspace = Path(worker.workspace_path)
    specs_dir = workspace / "specs"
    specs_dir.mkdir(parents=True, exist_ok=True)
    spec_path = specs_dir / f"{task.id}.json"
    spec_path.write_text(json.dumps(spec_json, indent=2))

    command = _build_command(payload.tool, Path("specs") / f"{task.id}.json")
    task.status = TaskStatus.running
    task.started_at = datetime.now(timezone.utc)
    worker.status = WorkerStatus.busy
    session.add(
        TaskEvent(
            task_id=task.id,
            type=TaskEventType.state_change,
            payload={"state": "running", "command": command},
        )
    )
    await session.commit()

    runtime = runtime_registry.get(worker_id)
    if runtime is None:
        runtime = await runtime_registry.ensure_runtime(worker_id, worker.tmux_session, worker.workspace_path)
    runtime.enqueue_task(task.id, command)
    return task


async def get_task(session: AsyncSession, task_id: str) -> Task | None:
    return await session.get(Task, task_id)


async def list_worker_tasks(session: AsyncSession, worker_id: str) -> list[Task]:
    result = await session.execute(
        select(Task).where(Task.worker_id == worker_id).order_by(Task.created_at.desc())
    )
    return list(result.scalars().all())

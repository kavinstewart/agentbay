from __future__ import annotations

import asyncio
import json
from collections import deque
from datetime import datetime, timezone
from typing import Deque

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.config import settings
from app.enums import FlowStatus, TaskEventType, TaskStatus, WorkerStatus
from app.models import Flow, Task, TaskEvent, Worker
from app.services.tmux import TmuxController


class WorkerRuntime:
    def __init__(
        self,
        worker_id: str,
        tmux_session: str,
        workspace_path: str,
        sessionmaker: async_sessionmaker,
    ) -> None:
        self.worker_id = worker_id
        self.workspace_path = workspace_path
        self.controller = TmuxController(tmux_session)
        self.sessionmaker = sessionmaker
        self.running_tasks: Deque[str] = deque()
        self._monitor_task: asyncio.Task | None = None
        self._lock = asyncio.Lock()
        self._collecting_task_id: str | None = None
        self._result_lines: list[str] = []

    async def start(self) -> None:
        if self._monitor_task is None:
            self._monitor_task = asyncio.create_task(self._monitor_loop())

    def enqueue_task(self, task_id: str, command: str) -> None:
        self.running_tasks.append(task_id)
        self.controller.send_line(command)

    def mark_task_failed(self, task_id: str, message: str) -> None:
        if task_id in self.running_tasks:
            self.running_tasks.remove(task_id)

    async def _monitor_loop(self) -> None:
        while True:
            snapshot = self.controller.capture_pane()
            new_text = snapshot.new_text
            if new_text:
                lines = new_text.splitlines()
                await self._process_lines(lines)
            await asyncio.sleep(settings.monitor_interval)

    async def _process_lines(self, lines: list[str]) -> None:
        if not lines:
            return
        async with self.sessionmaker() as session:
            for raw_line in lines:
                stripped = raw_line.strip()
                if settings.sentinel_start in stripped:
                    self._collecting_task_id = self.running_tasks[0] if self.running_tasks else None
                    self._result_lines = []
                    print(f"[runtime] detected sentinel start for {self._collecting_task_id}")
                    continue
                if settings.sentinel_end in stripped:
                    print(f"[runtime] detected sentinel end for {self._collecting_task_id}")
                    await self._finalize_result(session)
                    continue
                if self._collecting_task_id:
                    self._result_lines.append(raw_line)
                elif self.running_tasks:
                    event = TaskEvent(
                        task_id=self.running_tasks[0],
                        type=TaskEventType.stdout_chunk,
                        payload={"line": raw_line},
                    )
                    session.add(event)
            await session.commit()

    async def _finalize_result(self, session) -> None:
        task_id = self._collecting_task_id
        payload_text = "\n".join(self._result_lines)
        self._collecting_task_id = None
        self._result_lines = []
        if not task_id:
            return
        result: dict | None = None
        error_message: str | None = None
        status = TaskStatus.completed
        try:
            result = json.loads(payload_text)
            result_status = (result or {}).get("status")
            if result_status in {"failed", "error"}:
                status = TaskStatus.failed
                error_message = (result or {}).get("error")
        except json.JSONDecodeError:
            status = TaskStatus.failed
            error_message = "Invalid JSON result from tool"
        stmt = select(Task).where(Task.id == task_id)
        task = (await session.execute(stmt)).scalar_one_or_none()
        if not task:
            return
        task.result_json = result
        task.error_message = error_message
        task.status = status
        now = datetime.now(timezone.utc)
        task.finished_at = now
        if task.started_at is None:
            task.started_at = now
        session.add(
            TaskEvent(
                task_id=task_id,
                type=TaskEventType.result_parsed,
                payload={"result": result, "error": error_message},
            )
        )
        if task_id in self.running_tasks:
            self.running_tasks.remove(task_id)
        worker = await session.get(Worker, task.worker_id)
        if worker:
            worker.status = WorkerStatus.idle if not self.running_tasks else WorkerStatus.busy
            worker.last_seen_at = now
        if status == TaskStatus.failed and task.flow_id:
            flow = await session.get(Flow, task.flow_id)
            if flow:
                flow.status = FlowStatus.failed
                flow.result = {
                    "reason": task.error_message or "task_failed",
                    "task_id": task_id,
                }
        await session.commit()


class RuntimeRegistry:
    """Tracks active worker runtimes and their monitor loops."""

    def __init__(self, sessionmaker: async_sessionmaker) -> None:
        self.sessionmaker = sessionmaker
        self._runtimes: dict[str, WorkerRuntime] = {}
        self._lock = asyncio.Lock()

    async def bootstrap(self) -> None:
        async with self.sessionmaker() as session:
            result = await session.execute(select(Worker))
            for worker in result.scalars():
                await self.ensure_runtime(worker.id, worker.tmux_session, worker.workspace_path)

    async def ensure_runtime(self, worker_id: str, tmux_session: str, workspace_path: str) -> WorkerRuntime:
        async with self._lock:
            runtime = self._runtimes.get(worker_id)
            if runtime is None:
                runtime = WorkerRuntime(
                    worker_id=worker_id,
                    tmux_session=tmux_session,
                    workspace_path=workspace_path,
                    sessionmaker=self.sessionmaker,
                )
                self._runtimes[worker_id] = runtime
                await runtime.start()
            return runtime

    def get(self, worker_id: str) -> WorkerRuntime | None:
        return self._runtimes.get(worker_id)

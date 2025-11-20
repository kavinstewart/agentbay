from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy.ext.asyncio import async_sessionmaker

from app.enums import FlowStatus, TaskStatus
from app.models import Flow, FlowIteration, Task, Worker
from app.schemas import TaskCreate
from app.services.task_runner import create_task


class DesignRefinementCoordinator:
    def __init__(self, sessionmaker: async_sessionmaker) -> None:
        self.sessionmaker = sessionmaker

    def kickoff(self, flow_id: str) -> None:
        asyncio.create_task(self._run(flow_id))

    async def _run(self, flow_id: str) -> None:
        async with self.sessionmaker() as session:
            flow = await session.get(Flow, flow_id)
            if not flow:
                return
            worker = await session.get(Worker, flow.worker_id)
            if not worker:
                flow.status = FlowStatus.failed
                flow.result = {"reason": "worker_missing"}
                await session.commit()
                return
            config = flow.config
        workspace = Path(worker.workspace_path)
        design_path = workspace / "design.md"
        self._write_initial_design(design_path, config["initial_prompt"])
        for iteration in range(1, config["max_iterations"] + 1):
            coder_spec = self._build_coder_spec(config, iteration)
            payload = TaskCreate(tool="codex", spec=coder_spec, flow_id=flow_id)
            async with self.sessionmaker() as session:
                task = await create_task(session, worker.id, payload)
                task_id = task.id
            finished_task = await wait_for_task_completion(self.sessionmaker, task_id)
            if finished_task.status == TaskStatus.failed:
                await self._mark_failed(flow_id, "coder_task_failed", {"task_id": task_id})
                return
            critic_result = self._run_carmack_critic(design_path, iteration)
            await self._record_iteration(flow_id, iteration, task_id, critic_result)
            if critic_result["score"] >= config["min_score"]:
                await self._mark_completed(flow_id, iteration, critic_result)
                return
        await self._mark_failed(flow_id, "max_iterations_reached", None)

    def _write_initial_design(self, path: Path, prompt: str) -> None:
        path.write_text(f"# Design Draft\n\n{prompt}\n")

    def _build_coder_spec(self, config: dict[str, Any], iteration: int) -> dict[str, Any]:
        return {
            "description": "Refine design document",
            "files": ["design.md"],
            "instructions": (
                "Update design.md to reflect feedback and improve clarity, performance, and feasibility. "
                f"This is iteration {iteration} of the refinement loop."
            ),
            "context": {
                "iteration": iteration,
                "initial_prompt": config["initial_prompt"],
            },
        }

    def _run_carmack_critic(self, design_path: Path, iteration: int) -> dict[str, Any]:
        content = design_path.read_text() if design_path.exists() else ""
        heading_count = content.count("#")
        length = len(content.split())
        score = min(10, 4 + heading_count + (length // 200))
        issues = []
        if heading_count < 3:
            issues.append("Add more structured sections to the design.")
        if "performance" not in content.lower():
            issues.append("Explicitly discuss performance considerations.")
        suggestions = "Iterate on the architecture and quantify trade-offs."
        return {
            "persona": "john_carmack",
            "score": score,
            "issues": issues,
            "suggestions": suggestions,
            "iteration": iteration,
        }

    async def _record_iteration(
        self,
        flow_id: str,
        iteration: int,
        task_id: str,
        critic_result: dict[str, Any],
    ) -> None:
        async with self.sessionmaker() as session:
            flow = await session.get(Flow, flow_id)
            if not flow:
                return
            flow.state = {
                "last_iteration": iteration,
                "last_score": critic_result["score"],
                "last_critic": critic_result,
            }
            session.add(
                FlowIteration(
                    flow_id=flow_id,
                    iteration_index=iteration,
                    coder_task_id=task_id,
                    critic_task_payload=critic_result,
                )
            )
            await session.commit()

    async def _mark_completed(self, flow_id: str, iteration: int, critic_result: dict[str, Any]) -> None:
        async with self.sessionmaker() as session:
            flow = await session.get(Flow, flow_id)
            if not flow:
                return
            flow.status = FlowStatus.completed
            flow.result = {
                "final_iteration": iteration,
                "critic": critic_result,
            }
            await session.commit()

    async def _mark_failed(self, flow_id: str, reason: str, details: dict[str, Any] | None) -> None:
        async with self.sessionmaker() as session:
            flow = await session.get(Flow, flow_id)
            if not flow:
                return
            flow.status = FlowStatus.failed
            flow.result = {"reason": reason, "details": details}
            await session.commit()


def _now() -> datetime:
    return datetime.now(timezone.utc)


async def wait_for_task_completion(sessionmaker: async_sessionmaker, task_id: str) -> Task:
    while True:
        async with sessionmaker() as session:
            task = await session.get(Task, task_id)
            if task and task.status in {TaskStatus.completed, TaskStatus.failed}:
                return task
        await asyncio.sleep(1)


design_flow_coordinator: DesignRefinementCoordinator | None = None


def init_design_coordinator(sessionmaker: async_sessionmaker) -> None:
    global design_flow_coordinator
    design_flow_coordinator = DesignRefinementCoordinator(sessionmaker)

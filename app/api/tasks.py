from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.schemas import TaskCreate, TaskRead
from app.services.task_runner import create_task, get_task
from app.services.worker_manager import worker_manager

router = APIRouter(tags=["tasks"])


@router.post("/workers/{worker_id}/tasks", response_model=TaskRead)
async def create_worker_task(
    worker_id: str,
    payload: TaskCreate,
    session: AsyncSession = Depends(get_session),
) -> TaskRead:
    worker = await worker_manager.get_worker(session, worker_id)
    if not worker:
        raise HTTPException(status_code=404, detail="Worker not found")
    task = await create_task(session, worker_id, payload)
    return TaskRead.model_validate(task)


@router.get("/tasks/{task_id}", response_model=TaskRead)
async def get_task_status(task_id: str, session: AsyncSession = Depends(get_session)) -> TaskRead:
    task = await get_task(session, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    return TaskRead.model_validate(task)

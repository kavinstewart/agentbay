from __future__ import annotations

from typing import List

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.schemas import TaskRead, WorkerCreate, WorkerRead
from app.services.task_runner import list_worker_tasks
from app.services.worker_manager import worker_manager

router = APIRouter(prefix="/workers", tags=["workers"])


@router.post("", response_model=WorkerRead)
async def create_worker(payload: WorkerCreate, session: AsyncSession = Depends(get_session)) -> WorkerRead:
    worker = await worker_manager.create_worker(session, payload.label)
    return WorkerRead.model_validate(worker)


@router.get("", response_model=List[WorkerRead])
async def list_workers(session: AsyncSession = Depends(get_session)) -> list[WorkerRead]:
    workers = await worker_manager.list_workers(session)
    return [WorkerRead.model_validate(worker) for worker in workers]


@router.get("/{worker_id}", response_model=WorkerRead)
async def get_worker(worker_id: str, session: AsyncSession = Depends(get_session)) -> WorkerRead:
    worker = await worker_manager.get_worker(session, worker_id)
    if not worker:
        raise HTTPException(status_code=404, detail="Worker not found")
    return WorkerRead.model_validate(worker)


@router.get("/{worker_id}/tasks", response_model=List[TaskRead])
async def get_worker_tasks(worker_id: str, session: AsyncSession = Depends(get_session)) -> list[TaskRead]:
    worker = await worker_manager.get_worker(session, worker_id)
    if not worker:
        raise HTTPException(status_code=404, detail="Worker not found")
    tasks = await list_worker_tasks(session, worker_id)
    return [TaskRead.model_validate(task) for task in tasks]

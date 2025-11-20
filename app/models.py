from __future__ import annotations

from datetime import datetime
from uuid import uuid4

from sqlalchemy import JSON, Column, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import Enum as SQLEnum

from app.db import Base
from app.enums import FlowStatus, FlowType, TaskEventType, TaskStatus, WorkerStatus


class Worker(Base):
    __tablename__ = "workers"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    label: Mapped[str | None]
    status: Mapped[WorkerStatus] = mapped_column(
        SQLEnum(WorkerStatus), default=WorkerStatus.idle, nullable=False
    )
    tmux_session: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    workspace_path: Mapped[str] = mapped_column(String(255), nullable=False)
    ttyd_url: Mapped[str | None]
    ttyd_pid: Mapped[int | None]
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), onupdate=func.now())
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    tasks: Mapped[list["Task"]] = relationship(back_populates="worker")


class Task(Base):
    __tablename__ = "tasks"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    worker_id: Mapped[str] = mapped_column(ForeignKey("workers.id"), nullable=False, index=True)
    tool: Mapped[str] = mapped_column(String(32), nullable=False)
    spec_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    status: Mapped[TaskStatus] = mapped_column(
        SQLEnum(TaskStatus), default=TaskStatus.queued, nullable=False
    )
    result_json: Mapped[dict | None] = mapped_column(JSON)
    error_message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    flow_id: Mapped[str | None] = mapped_column(ForeignKey("flows.id"), nullable=True)

    worker: Mapped[Worker] = relationship(back_populates="tasks")
    events: Mapped[list["TaskEvent"]] = relationship(back_populates="task", cascade="all, delete-orphan")


class TaskEvent(Base):
    __tablename__ = "task_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    task_id: Mapped[str] = mapped_column(ForeignKey("tasks.id"), nullable=False, index=True)
    type: Mapped[TaskEventType] = mapped_column(SQLEnum(TaskEventType), nullable=False)
    payload: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    task: Mapped[Task] = relationship(back_populates="events")


class Flow(Base):
    __tablename__ = "flows"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    type: Mapped[FlowType] = mapped_column(SQLEnum(FlowType), nullable=False)
    status: Mapped[FlowStatus] = mapped_column(
        SQLEnum(FlowStatus), default=FlowStatus.running, nullable=False
    )
    worker_id: Mapped[str] = mapped_column(ForeignKey("workers.id"), nullable=False)
    config: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    state: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    result: Mapped[dict | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), onupdate=func.now())

    worker: Mapped[Worker] = relationship()
    tasks: Mapped[list[Task]] = relationship()
    iterations: Mapped[list["FlowIteration"]] = relationship(
        back_populates="flow", cascade="all, delete-orphan"
    )


class FlowIteration(Base):
    __tablename__ = "flow_iterations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    flow_id: Mapped[str] = mapped_column(ForeignKey("flows.id"), nullable=False, index=True)
    iteration_index: Mapped[int] = mapped_column(Integer, nullable=False)
    coder_task_id: Mapped[str | None] = mapped_column(String(36))
    critic_task_payload: Mapped[dict | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    flow: Mapped[Flow] = relationship(back_populates="iterations")

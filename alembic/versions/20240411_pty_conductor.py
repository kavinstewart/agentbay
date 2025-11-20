"""Initial schema for PTY conductor"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "20240411_conductor"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    worker_status = sa.Enum("idle", "busy", "error", "terminated", name="workerstatus")
    task_status = sa.Enum("queued", "running", "completed", "failed", name="taskstatus")
    task_event_type = sa.Enum(
        "stdout_chunk", "stderr_chunk", "state_change", "result_parsed", name="taskeventtype"
    )
    flow_status = sa.Enum("running", "completed", "failed", name="flowstatus")
    flow_type = sa.Enum("design_refinement", name="flowtype")

    op.create_table(
        "workers",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("label", sa.String(length=255)),
        sa.Column("status", worker_status, nullable=False, server_default="idle"),
        sa.Column("tmux_session", sa.String(length=64), nullable=False, unique=True),
        sa.Column("workspace_path", sa.String(length=255), nullable=False),
        sa.Column("ttyd_url", sa.String(length=255)),
        sa.Column("ttyd_pid", sa.Integer()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True)),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    op.create_table(
        "flows",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("type", flow_type, nullable=False),
        sa.Column("status", flow_status, nullable=False, server_default="running"),
        sa.Column("worker_id", sa.String(length=36), sa.ForeignKey("workers.id"), nullable=False),
        sa.Column("config", sa.JSON(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("state", sa.JSON(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("result", sa.JSON()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True)),
    )

    op.create_table(
        "tasks",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("worker_id", sa.String(length=36), sa.ForeignKey("workers.id"), nullable=False),
        sa.Column("tool", sa.String(length=32), nullable=False),
        sa.Column("spec_json", sa.JSON(), nullable=False),
        sa.Column("status", task_status, nullable=False, server_default="queued"),
        sa.Column("result_json", sa.JSON()),
        sa.Column("error_message", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.Column("flow_id", sa.String(length=36), sa.ForeignKey("flows.id")),
    )
    op.create_index("ix_tasks_worker_id", "tasks", ["worker_id"])

    op.create_table(
        "task_events",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("task_id", sa.String(length=36), sa.ForeignKey("tasks.id"), nullable=False),
        sa.Column("type", task_event_type, nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_task_events_task_id", "task_events", ["task_id"])

    op.create_table(
        "flow_iterations",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("flow_id", sa.String(length=36), sa.ForeignKey("flows.id"), nullable=False),
        sa.Column("iteration_index", sa.Integer(), nullable=False),
        sa.Column("coder_task_id", sa.String(length=36)),
        sa.Column("critic_task_payload", sa.JSON()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_flow_iterations_flow_id", "flow_iterations", ["flow_id"])


def downgrade() -> None:
    op.drop_index("ix_flow_iterations_flow_id", table_name="flow_iterations")
    op.drop_table("flow_iterations")
    op.drop_index("ix_task_events_task_id", table_name="task_events")
    op.drop_table("task_events")
    op.drop_index("ix_tasks_worker_id", table_name="tasks")
    op.drop_table("tasks")
    op.drop_table("flows")
    op.drop_table("workers")
    sa.Enum(name="flowtype").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="flowstatus").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="taskeventtype").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="taskstatus").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="workerstatus").drop(op.get_bind(), checkfirst=True)

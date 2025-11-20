from __future__ import annotations

import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.enums import WorkerStatus
from app.models import Worker
from app.services import runtime_registry


class WorkerManager:
    def __init__(self) -> None:
        self.workspace_root = settings.workspace_root.resolve()
        self.workspace_root.mkdir(parents=True, exist_ok=True)
        self._next_ttyd_port = settings.ttyd_port_start

    async def list_workers(self, session: AsyncSession) -> list[Worker]:
        result = await session.execute(select(Worker))
        return list(result.scalars().all())

    async def get_worker(self, session: AsyncSession, worker_id: str) -> Worker | None:
        return await session.get(Worker, worker_id)

    async def create_worker(self, session: AsyncSession, label: str | None = None) -> Worker:
        worker_id = str(uuid4())
        workspace = self.workspace_root / worker_id
        specs_dir = workspace / "specs"
        logs_dir = workspace / "logs"
        for path in (workspace, specs_dir, logs_dir):
            path.mkdir(parents=True, exist_ok=True)
        tmux_session = f"worker_{worker_id[:8]}"
        self._start_tmux_session(tmux_session, workspace)
        ttyd_url, ttyd_pid = self._start_ttyd(tmux_session)
        created_at = datetime.now(timezone.utc).isoformat()
        metadata_path = workspace / "worker.json"
        metadata_path.write_text(
            json.dumps(
                {
                    "id": worker_id,
                    "label": label,
                    "tmux_session": tmux_session,
                    "workspace": str(workspace),
                    "cli_type": settings.default_cli_type,
                    "created_at": created_at,
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        worker = Worker(
            id=worker_id,
            label=label,
            status=WorkerStatus.idle,
            tmux_session=tmux_session,
            workspace_path=str(workspace),
            ttyd_url=ttyd_url,
            ttyd_pid=ttyd_pid,
        )
        session.add(worker)
        await session.commit()
        await runtime_registry.ensure_runtime(worker.id, worker.tmux_session, worker.workspace_path)
        return worker

    def _start_tmux_session(self, session_name: str, workspace: Path) -> None:
        subprocess.run(
            [settings.tmux_bin, "new-session", "-d", "-s", session_name, "-c", str(workspace)],
            check=True,
        )

    def _start_ttyd(self, tmux_session: str) -> tuple[str | None, Optional[int]]:
        port = self._next_ttyd_port
        self._next_ttyd_port += 1
        cmd = [
            settings.ttyd_bin,
            "-p",
            str(port),
            settings.tmux_bin,
            "attach",
            "-t",
            tmux_session,
        ]
        try:
            proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except FileNotFoundError:
            return None, None
        url = f"{settings.ttyd_host}:{port}"
        return url, proc.pid


worker_manager = WorkerManager()

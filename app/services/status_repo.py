from __future__ import annotations

import sqlite3
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from app.config import settings


class StatusRepository:
    """Read-only helper for the watcher sqlite cache."""

    def __init__(self, db_path: Path | None = None) -> None:
        self.db_path = Path(db_path or settings.status_db_path)

    def list_status(self, min_polled_ts: float | None = None) -> list[dict[str, Any]]:
        if not self.db_path.exists():
            return []
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            query = """
                SELECT s.*, p.worker_id, p.tmux_session, p.tmux_window, p.tmux_pane, p.cwd, p.cli_type
                FROM status s
                LEFT JOIN ptys p ON s.id = p.id
            """
            params: list[Any] = []
            if min_polled_ts is not None:
                query += " WHERE s.last_polled_ts >= ?"
                params.append(min_polled_ts)
            query += " ORDER BY s.last_polled_ts DESC"
            result = conn.execute(query, params)
            rows = []
            for row in result.fetchall():
                rows.append(self._row_to_dict(row))
            return rows
        finally:
            conn.close()

    def tail_history(self, pane_id: str, limit: int = 50) -> list[dict[str, Any]]:
        if not self.db_path.exists():
            return []
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            result = conn.execute(
                """
                SELECT h.id, h.ts, h.state, h.summary,
                       p.worker_id, p.tmux_session, p.tmux_window, p.tmux_pane, p.cwd, p.cli_type
                FROM status_history h
                LEFT JOIN ptys p ON h.id = p.id
                WHERE h.id = ?
                ORDER BY h.ts DESC
                LIMIT ?
                """,
                (pane_id, limit),
            )
            rows = [self._history_row_to_dict(row) for row in result.fetchall()]
            return list(reversed(rows))
        finally:
            conn.close()

    def _row_to_dict(self, row: sqlite3.Row) -> dict[str, Any]:
        target = None
        if row["tmux_session"] and row["tmux_window"] is not None and row["tmux_pane"] is not None:
            target = f"{row['tmux_session']}:{row['tmux_window']}.{row['tmux_pane']}"
        return {
            "pane_id": row["id"],
            "worker_id": row["worker_id"],
            "cli_type": row["cli_type"],
            "cwd": row["cwd"],
            "tmux_session": row["tmux_session"],
            "tmux_window": row["tmux_window"],
            "tmux_pane": row["tmux_pane"],
            "tmux_target": target,
            "state": row["state"],
            "summary": row["summary"],
            "actions_needed": row["actions_needed"],
            "last_snapshot_hash": row["last_snapshot_hash"],
            "last_change_ts": row["last_change_ts"],
            "last_polled_ts": row["last_polled_ts"],
            "stable_count": row["stable_count"],
        }

    def _history_row_to_dict(self, row: sqlite3.Row) -> dict[str, Any]:
        target = None
        if row["tmux_session"] and row["tmux_window"] is not None and row["tmux_pane"] is not None:
            target = f"{row['tmux_session']}:{row['tmux_window']}.{row['tmux_pane']}"
        return {
            "pane_id": row["id"],
            "tmux_target": target,
            "worker_id": row["worker_id"],
            "cli_type": row["cli_type"],
            "cwd": row["cwd"],
            "ts": row["ts"],
            "state": row["state"],
            "summary": row["summary"],
        }


def format_timestamp(ts: float | None) -> str:
    if not ts:
        return "-"
    return datetime.fromtimestamp(ts).isoformat(timespec="seconds")


def min_timestamp_for_window(window_seconds: float | None) -> float | None:
    if window_seconds is None:
        return None
    return time.time() - window_seconds

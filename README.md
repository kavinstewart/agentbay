# PTY-Based Multi-CLI Coding Conductor

This service implements the tmux/ttyd/PTY-based conductor described in the design doc. It manages workers, submits CLI-driven tasks via tmux panes, captures sentinel-wrapped results, and exposes an HTTP API for worker, task, and design-refinement flow orchestration.

## Getting Started

1. **Install dependencies**
   ```bash
   poetry install
   ```
2. **Apply the initial database migration**
   ```bash
   alembic upgrade head
   ```
3. **Launch the API + watcher**
   ```bash
   poetry install --with dev  # ensures honcho is available
   poetry run honcho start
   ```

Use a `.env` file to override any of the defaults from `app/config.py`. For example:

```
CONDUCTOR_DATABASE_URL=postgresql+asyncpg:///conductor
CONDUCTOR_WORKSPACE_ROOT=/srv/workers
```

Ensure Postgres, `tmux`, and (optionally) `ttyd` are installed and on `PATH`.

To surface worker readiness inside tmux, point the status bar at the new CLI:

```bash
tmux set -g status-right '#(cd /path/to/repo && python scripts/conductor.py pty status --short --since 30)'
```

## HTTP API Overview

- `POST /workers` – create a worker with its own tmux session and (optional) ttyd URL.
- `GET /workers`, `GET /workers/{id}` – inspect workers.
- `POST /workers/{id}/tasks` – write a JSON spec, invoke the appropriate CLI shim, and stream its output until the sentinel result is parsed.
- `GET /tasks/{task_id}` – fetch task state/result.
- `POST /flows/design-refinement` – kick off the Carmack-style iterative refinement loop.
- `GET /flows/{flow_id}` – inspect flow progress/result.

Each worker receives a workspace directory with `specs/` plus whatever files a flow creates (e.g., `design.md`). Humans can attach via the ttyd URL to observe or intervene directly in the tmux session.

## CLI Shims

Shim scripts live under `scripts/shims` and all share the same JSON → sentinel protocol via `tool_runner.py`. Add new tools by creating another wrapper that calls the runner with a unique tool name and updating `TOOL_SHIMS` in `app/services/task_runner.py`.

## Smoke Test

With the API running locally on port 8100, execute:

```bash
poetry run python scripts/e2e_smoketest.py
```

The script provisions a worker, runs a standalone CLI task, kicks off the Carmack-inspired flow, and exits non-zero if anything fails.

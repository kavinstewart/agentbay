"""Quick end-to-end smoke test against a running conductor instance."""
from __future__ import annotations

import json
import time
from pathlib import Path
from urllib import request

BASE_URL = "http://127.0.0.1:8100"
LOG_PATH = Path(__file__).with_suffix(".log")
TIMEOUTS = {
    "task_poll": 40,
    "flow_poll": 90,
    "sleep": 1.0,
}


def log(message: str) -> None:
    print(message)
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with LOG_PATH.open("a", encoding="utf-8") as handle:
        handle.write(message + "\n")


def _http(method: str, path: str, payload: dict | None = None) -> dict:
    data = None
    if payload is not None:
        data = json.dumps(payload).encode()
    req = request.Request(
        f"{BASE_URL}{path}",
        data=data,
        method=method,
        headers={"Content-Type": "application/json"},
    )
    with request.urlopen(req) as resp:  # type: ignore[arg-type]
        body = resp.read().decode()
        return json.loads(body)


def main() -> None:
    LOG_PATH.write_text("", encoding="utf-8")

    worker = _http("POST", "/workers", {"label": "smoke"})
    worker_id = worker["id"]
    log(f"Worker created: {worker_id}")
    log(f"Workspace: {worker['workspace_path']}")
    workspace = Path(worker["workspace_path"])
    workspace.mkdir(parents=True, exist_ok=True)
    design_path = workspace / "design.md"
    if not design_path.exists():
        design_path.write_text("# Design Draft\n\nDocument the conductor architecture\n", encoding="utf-8")
        log(f"Seeded {design_path} with baseline content")

    task = _http(
        "POST",
        f"/workers/{worker_id}/tasks",
        {
            "tool": "codex",
            "spec": {
                "description": "Validate conductor",
                "instructions": "add smoke-test heading",
                "context": {"iteration": 1},
            },
        },
    )
    task_id = task["id"]
    log(f"Task started: {task_id}")
    log(f"Task spec: {json.dumps(task['spec_json']) if 'spec_json' in task else task}")

    for _ in range(TIMEOUTS["task_poll"]):
        status = _http("GET", f"/tasks/{task_id}")
        if status["status"] in {"completed", "failed"}:
            log(f"Task finished: {status['status']}")
            log(f"Task result: {status['result_json']}")
            if status["status"] == "failed":
                raise SystemExit("Task failed during smoke test")
            break
        time.sleep(TIMEOUTS["sleep"])
    else:
        raise SystemExit("Task timed out")

    flow = _http(
        "POST",
        "/flows/design-refinement",
        {
            "worker_id": worker_id,
            "initial_prompt": "Document the conductor architecture",
            "max_iterations": 3,
            "min_score": 6,
        },
    )
    flow_id = flow["id"]
    log(f"Flow started: {flow_id}")

    for _ in range(TIMEOUTS["flow_poll"]):
        status = _http("GET", f"/flows/{flow_id}")
        if status["status"] != "running":
            log(f"Flow finished: {status['status']}")
            log(f"Flow result: {status['result']}")
            if status["status"] != "completed":
                raise SystemExit("Flow did not complete successfully")
            break
        time.sleep(TIMEOUTS["sleep"])
    else:
        raise SystemExit("Flow timed out")

    design_path = Path(worker["workspace_path"]) / "design.md"
    if design_path.exists():
        log("Final design.md contents:\n" + design_path.read_text())

if __name__ == "__main__":
    main()

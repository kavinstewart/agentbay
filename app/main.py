from __future__ import annotations

from fastapi import FastAPI

from app.api import flows, tasks, workers
from app.db import AsyncSessionLocal
from app.flows.design_refinement import init_design_coordinator
from app.services import runtime_registry

app = FastAPI(title="PTY Coding Conductor", version="0.1.0")

app.include_router(workers.router)
app.include_router(tasks.router)
app.include_router(flows.router)


@app.on_event("startup")
async def setup_runtime() -> None:
    await runtime_registry.bootstrap()
    init_design_coordinator(AsyncSessionLocal)

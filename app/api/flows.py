from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.enums import FlowStatus, FlowType
from app.flows import design_refinement
from app.models import Flow
from app.schemas import FlowCreate, FlowRead
from app.services.worker_manager import worker_manager

router = APIRouter(prefix="/flows", tags=["flows"])


@router.post("/design-refinement", response_model=FlowRead)
async def start_design_flow(
    payload: FlowCreate, session: AsyncSession = Depends(get_session)
) -> FlowRead:
    coordinator = design_refinement.design_flow_coordinator
    if coordinator is None:
        raise HTTPException(status_code=500, detail="Flow coordinator not initialized")
    worker = await worker_manager.get_worker(session, payload.worker_id)
    if not worker:
        raise HTTPException(status_code=404, detail="Worker not found")
    flow = Flow(
        type=FlowType.design_refinement,
        worker_id=payload.worker_id,
        status=FlowStatus.running,
        config={
            "initial_prompt": payload.initial_prompt,
            "max_iterations": payload.max_iterations,
            "min_score": payload.min_score,
        },
        state={},
    )
    session.add(flow)
    await session.commit()
    await session.refresh(flow)
    coordinator.kickoff(flow.id)
    return FlowRead.model_validate(flow)


@router.get("/{flow_id}", response_model=FlowRead)
async def get_flow(flow_id: str, session: AsyncSession = Depends(get_session)) -> FlowRead:
    flow = await session.get(Flow, flow_id)
    if not flow:
        raise HTTPException(status_code=404, detail="Flow not found")
    return FlowRead.model_validate(flow)

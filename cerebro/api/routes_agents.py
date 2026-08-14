"""REST API routes for agents."""

from fastapi import APIRouter, HTTPException
from cerebro import store

router = APIRouter(prefix="/api/agents", tags=["agents"])


@router.get("")
async def get_agents():
    """List all agents."""
    agents = await store.list_agents()
    return {"agents": agents}


@router.get("/{agent_id}")
async def get_agent_by_id(agent_id: str):
    """Retrieve an agent by its identifier."""
    agent = await store.get_agent(agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail=f"Agent '{agent_id}' not found")
    return agent

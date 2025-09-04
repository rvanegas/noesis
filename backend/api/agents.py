from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from typing import Dict, Any

from services.agent_coordinator import coordinator


from core.utils import logger
# import time

router = APIRouter()

@router.get("/results")
async def get_conversation_results(
    conversation_id: str = Query(..., description="Conversation ID (format: session_id:conversation_id)"),
    snapshot_id: str = Query(..., description="Snapshot ID for filtering results")
) -> Dict[str, Any]:
    """Get latest agent results for a conversation/snapshot, grouped by agent type"""
    return coordinator.result_manager.get_formatted_results(conversation_id, snapshot_id, coordinator)

@router.get("/active")
async def get_active_tasks(conversation_id: str = Query(..., description="Conversation ID (format: session_id:conversation_id)")) -> Dict[str, Any]:
    """Get all currently active tasks for a specific conversation"""
    return coordinator.result_manager.get_active_tasks_formatted(conversation_id, coordinator) 

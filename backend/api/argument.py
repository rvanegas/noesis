from fastapi import APIRouter, File, UploadFile, HTTPException, Query, Depends

from core.utils import logger
from schemas.arguments import (
    Arguments,
    ArgumentsWithStep,
    ArgumentsWithProposition,
    ArgumentsWithStepAndProposition)
from services.argument_service import (
    ArgumentService,
    ArgumentStepService,
    ArgumentPropositionService,
    ArgumentStepAndPropositionService)
from services.file import FileData, create_file
from services.agent_coordinator import coordinator

router = APIRouter()

def get_conversation_handler(operation_name: str):
    """Dependency that returns a conversation handler function"""
    def handler(conversation_id: str = Query(..., description="Conversation ID (format: session_id:conversation_id)"),
                snapshot_id: str = Query(..., description="Snapshot ID for agent coordination")):
        def conversation_handler(args):
            try:
                args.conversation_id = conversation_id
                # logger.info(f"{operation_name} operation for conversation: {conversation_id}")
                return args, snapshot_id
            except Exception as e:
                logger.error(f"{operation_name} error: {e}")
                raise HTTPException(status_code=422, detail=str(e))
        return conversation_handler
    return handler

@router.post('/argue')
async def argue(args: ArgumentsWithProposition,
        handler = Depends(get_conversation_handler("Argue"))):
    args, snapshot_id = handler(args)
    
    # Clean up expired agent results
    removed_count = coordinator.result_manager.cleanup_expired_conversations()
    if removed_count > 0:
        logger.info(f"Cleaned up {removed_count} expired conversations during argue call")
    
    service = ArgumentPropositionService(args, snapshot_id)
    result = service.argue()
    return {"reply": result}

@router.post('/gen-name')
async def gen_name(args: ArgumentsWithProposition,
        handler = Depends(get_conversation_handler("gen_name"))):
    args, snapshot_id = handler(args)
    # logger.info(f"🔤 Received name generation request for conversation {args.conversation_id}")
    # logger.info(f"🔤 Proposition: {args.proposition}")
    # logger.info(f"🔤 Assumptions count: {len(args.assumptions)}, Argument count: {len(args.argument)}")
    
    coordinator.queue_name_generation_task(
        args.conversation_id,
        args.proposition,
        args.assumptions,
        args.argument,
        args.file_ids
    )
    # logger.info(f"🔤 Name generation task queued for conversation {args.conversation_id}")
    return {"reply": "{}", "message": "Name generation queued"}

@router.post("/assume")
async def assume(args: ArgumentsWithStep,
        handler = Depends(get_conversation_handler("Assume"))):
    args, snapshot_id = handler(args)
    service = ArgumentStepService(args, snapshot_id)
    result = service.assume()
    return {"reply": result}

@router.post("/remove")
async def remove(args: ArgumentsWithStep,
        handler = Depends(get_conversation_handler("Remove"))):
    args, snapshot_id = handler(args)
    service = ArgumentStepService(args, snapshot_id)
    result = service.remove()
    return {"reply": result}

@router.post("/user-justify")
async def user_justify(args: ArgumentsWithStepAndProposition,
        handler = Depends(get_conversation_handler("User justify"))):
    args, snapshot_id = handler(args)
    service = ArgumentStepAndPropositionService(args, snapshot_id)
    result = service.user_justify()
    return {"reply": result}

@router.post("/explain")
async def explain(args: ArgumentsWithStep,
        handler = Depends(get_conversation_handler("Explain"))):
    args, snapshot_id = handler(args)
    service = ArgumentStepService(args, snapshot_id)
    result = service.explain()
    return {"reply": result}

@router.post("/reject-formalization")
async def reject_formalization(args: ArgumentsWithStep,
        handler = Depends(get_conversation_handler("Reject formalization"))):
    """Reject a formalization and trigger re-formalization"""
    args, snapshot_id = handler(args)
    service = ArgumentStepService(args, snapshot_id)
    result = service.reject_formalization()
    return {"reply": result}

@router.post("/endorse-formalization")
async def endorse_formalization(args: ArgumentsWithStep,
        handler = Depends(get_conversation_handler("Endorse formalization"))):
    """Endorse a formalization and potentially trigger formal evaluator"""
    args, snapshot_id = handler(args)
    service = ArgumentStepService(args, snapshot_id)
    result = service.endorse_formalization()
    return {"reply": result}

@router.post("/upload")
async def upload(file: UploadFile = File(...)):
    content = await file.read()
    file_data = FileData(
        content=content,
        filename=file.filename)
    file_ref = create_file(file_data)
    return {"reply": file_ref}

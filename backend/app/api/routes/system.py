from fastapi import APIRouter

from app.core import warmup

router = APIRouter()


@router.get("/warmup")
async def warmup_status():
    """LLM warm-up state ({status, device, model}) — polled by the frontend so
    the progress UI can say "loading the model onto the GPU" (or CPU wording)
    while the first mapping of a session waits on the model load."""
    return warmup.get_state()

from fastapi import APIRouter, HTTPException

router = APIRouter()


@router.post("/chat")
async def chat():
    raise HTTPException(status_code=501, detail="Chat is not implemented yet")

import os
import uuid

from fastapi import APIRouter, HTTPException, UploadFile

from app.core.config import settings
from app.ingest.pdf_to_markdown import pdf_to_markdown

router = APIRouter()


@router.post("/ingest")
async def ingest(file: UploadFile):
    if file.content_type != "application/pdf":
        raise HTTPException(status_code=400, detail="Only PDF uploads are supported")

    os.makedirs(settings.upload_dir, exist_ok=True)
    dest_path = os.path.join(settings.upload_dir, f"{uuid.uuid4()}_{file.filename}")
    with open(dest_path, "wb") as f:
        f.write(await file.read())

    markdown = pdf_to_markdown(dest_path)
    return {"filename": file.filename, "markdown": markdown}

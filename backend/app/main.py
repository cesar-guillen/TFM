from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import attack, chat, ingest, matrix
from app.core.config import settings

app = FastAPI(title="TFM ATT&CK Mapper")

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(ingest.router, prefix="/api")
app.include_router(chat.router, prefix="/api")
app.include_router(matrix.router, prefix="/api")
app.include_router(attack.router, prefix="/api")


@app.get("/health")
async def health():
    return {"status": "ok"}

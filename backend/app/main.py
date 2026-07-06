from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import attack, chat, ingest, mapping, matrix
from app.attack.build_kb import build_kb
from app.core.config import settings


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Instant no-op once the collection is populated; on a fresh volume it
    # restores the bundled pre-embedded seed, so `docker compose up` alone
    # yields a working KB (retrieval divides by the KB size — see bm25.py).
    build_kb()
    yield


app = FastAPI(title="TFM ATT&CK Mapper", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(ingest.router, prefix="/api")
app.include_router(chat.router, prefix="/api")
app.include_router(matrix.router, prefix="/api")
app.include_router(mapping.router, prefix="/api")
app.include_router(attack.router, prefix="/api")


@app.get("/health")
async def health():
    return {"status": "ok"}

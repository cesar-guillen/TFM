import logging
import threading
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import attack, chat, ingest, mapping, matrix, system
from app.attack.build_kb import build_kb
from app.attack.embeddings import embed_texts
from app.core import warmup
from app.core.config import settings
from app.core.llm import warm_chat_model

logging.basicConfig(level=logging.INFO)


def _warm_models() -> None:
    """Load both Ollama models at startup so the first run of a session pays
    warm-model latency. Chat model first: it is the big one, and loading the
    small embed model first only gets it evicted. Ready is marked once *both*
    are warm — an ingest racing this thread queues behind the chat load."""
    warmup.mark_loading()
    try:
        warm_chat_model()
    except Exception:
        warmup.mark_unavailable()
        return
    try:
        embed_texts(["warmup"])
    except Exception:
        pass
    warmup.mark_ready(warmup.detect_device())


@asynccontextmanager
async def lifespan(app: FastAPI):
    threading.Thread(target=_warm_models, daemon=True).start()
    # No-op once the collection is populated; on a fresh volume it restores the
    # bundled pre-embedded seed, so `docker compose up` alone yields a usable KB.
    build_kb()
    yield


app = FastAPI(title="TFM ATT&CK Mapper", lifespan=lifespan)

# The API is unauthenticated by design (single-user, local-only). Keep the
# allowed origins to the frontend dev server; the deployment compose file puts
# Caddy with HTTP Basic Auth in front and serves both same-origin.
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_methods=["GET", "POST", "PUT", "DELETE"],
    allow_headers=["Content-Type"],
)

app.include_router(ingest.router, prefix="/api")
app.include_router(chat.router, prefix="/api")
app.include_router(matrix.router, prefix="/api")
app.include_router(mapping.router, prefix="/api")
app.include_router(attack.router, prefix="/api")
app.include_router(system.router, prefix="/api")


@app.get("/health")
async def health():
    return {"status": "ok"}

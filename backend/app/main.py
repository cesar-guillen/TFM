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


def _warm_models() -> None:
    """Load both Ollama models up front so the first upload/mapping of a
    session runs at warm-model speed — the cold cost (CUDA init + model load,
    ~40s on first GPU use after a container start) is paid here, during
    startup, instead. Sequential, chat model first: it's the big one (~7 GB),
    and the small embed model fits in the VRAM left over — loading in the
    other order ends with chat evicting embed. With OLLAMA_KEEP_ALIVE=-1
    (docker-compose.yml) they then stay resident. Errors are ignored — real
    requests surface them with proper messages. Progress is reported into
    app.core.warmup so the UI can show "GPU being set up / LLM warming up"
    if an upload races this."""
    warmup.mark_loading()
    try:
        warm_chat_model()
        warmup.mark_ready(warmup.detect_device())
    except Exception:
        warmup.mark_unavailable()
    try:
        embed_texts(["warmup"])
    except Exception:
        pass


@asynccontextmanager
async def lifespan(app: FastAPI):
    threading.Thread(target=_warm_models, daemon=True).start()
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
app.include_router(system.router, prefix="/api")


@app.get("/health")
async def health():
    return {"status": "ok"}

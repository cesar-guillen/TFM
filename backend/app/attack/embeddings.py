import httpx

from app.core.config import settings


def embed_text(text: str, client: httpx.Client | None = None) -> list[float]:
    kwargs = {"json": {"model": settings.ollama_embed_model, "prompt": text}}
    if client is not None:
        response = client.post(f"{settings.ollama_host}/api/embeddings", **kwargs)
    else:
        response = httpx.post(f"{settings.ollama_host}/api/embeddings", timeout=60, **kwargs)
    response.raise_for_status()
    return response.json()["embedding"]

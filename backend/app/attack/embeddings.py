import httpx

from app.core.config import settings

DEFAULT_TIMEOUT = 120.0  # one batch on a slow CPU can take tens of seconds


def embed_texts(texts: list[str], client: httpx.Client | None = None) -> list[list[float]]:
    """Embed a batch of texts in one /api/embed request.

    The embed runner serves a single slot, so client-side concurrency buys
    nothing and batching within a request is the only way to amortize
    per-request overhead. Note the returned vectors are L2-normalized, unlike
    the legacy /api/embeddings endpoint's — which is why both collections use
    cosine distance (see app.core.chroma).
    """
    payload = {"model": settings.ollama_embed_model, "input": texts}
    if client is not None:
        response = client.post(f"{settings.ollama_host}/api/embed", json=payload)
    else:
        response = httpx.post(f"{settings.ollama_host}/api/embed", timeout=DEFAULT_TIMEOUT, json=payload)
    response.raise_for_status()
    return response.json()["embeddings"]


def embed_text(text: str, client: httpx.Client | None = None) -> list[float]:
    return embed_texts([text], client)[0]

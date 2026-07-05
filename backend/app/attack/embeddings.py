import httpx

from app.core.config import settings

DEFAULT_TIMEOUT = 120.0  # generous: one batch on a slow (no-AVX VM) CPU can take tens of seconds


def embed_texts(texts: list[str], client: httpx.Client | None = None) -> list[list[float]]:
    """Embed a batch of texts in one request via Ollama's /api/embed.

    One request per batch beats one request per text: it drops per-request
    HTTP/scheduling overhead, which matters more the faster the model runs
    (the embed runner serves a single slot, so client-side concurrency never
    helps — batching within a request is the only way to amortize overhead).

    NOTE: /api/embed returns L2-normalized vectors, unlike the legacy
    /api/embeddings endpoint this replaced (same direction, cosine == 1.0,
    but unit magnitude). That's why the ATT&CK KB collection uses cosine
    distance (see app.core.chroma) — magnitude differences between old
    (unnormalized) stored vectors and new queries don't affect ranking there.
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

"""Ollama chat client for the LLM mapping stage (pipeline stage 6).

Uses /api/chat with a JSON-schema `format` constraint so the model's output is
grammar-constrained server-side — the decoder literally cannot emit tokens that
violate the schema. That, plus temperature 0, is most of the reliability story
for a small (3B) local model; the rest is validation of the *content* (e.g.
technique ids actually being among the offered candidates), which lives with
the caller in app.mapping.mapper.
"""

import json

import httpx

from app.core.config import settings

# One chunk + 8 trimmed candidates + instructions ≈ 1.7k tokens; Ollama's
# default 2048 ctx would silently truncate the tail, so size it explicitly.
NUM_CTX = 4096
# Hard cap on generated tokens per verdict. A few mappings with short quotes
# fit comfortably; without a cap, a small model in constrained-JSON mode can
# ramble for minutes on a slow CPU before closing the object.
NUM_PREDICT = 400
# Generation on a slow CPU takes a while per chunk; the per-request timeout has
# to absorb worst-case model load + prompt eval + decode.
CHAT_TIMEOUT = 600.0


def warm_chat_model() -> None:
    """Make Ollama load the chat model without generating anything: a
    /api/generate call with no prompt returns once the model is in memory.
    Called fire-and-forget at backend startup (app.main) so the first mapping
    run doesn't pay the cold load."""
    httpx.post(
        f"{settings.ollama_host}/api/generate",
        json={"model": settings.ollama_model},
        timeout=CHAT_TIMEOUT,
    ).raise_for_status()


def chat_json(
    prompt: str,
    response_schema: dict,
    client: httpx.Client | None = None,
    system: str | None = None,
) -> dict:
    """One chat turn, response constrained to `response_schema`, parsed to a dict."""
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})

    payload = {
        "model": settings.ollama_model,
        "messages": messages,
        "stream": False,
        "format": response_schema,
        "options": {"temperature": 0, "num_ctx": NUM_CTX, "num_predict": NUM_PREDICT},
    }
    url = f"{settings.ollama_host}/api/chat"
    if client is not None:
        response = client.post(url, json=payload)
    else:
        response = httpx.post(url, timeout=CHAT_TIMEOUT, json=payload)
    response.raise_for_status()
    return json.loads(response.json()["message"]["content"])

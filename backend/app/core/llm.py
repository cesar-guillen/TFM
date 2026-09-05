"""Ollama chat client for the LLM mapping stage.

Requests go to /api/chat with a JSON-schema `format` constraint, so the
model's output is grammar-constrained server-side and cannot violate the
schema. That plus temperature 0 is most of the reliability story for a small
local model; validating the *content* (technique ids being among the offered
candidates, quotes occurring in the chunk) is the caller's job — see
app.mapping.mapper.
"""

import json
import logging
import os
from functools import lru_cache

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)

# One chunk + candidates + instructions is ~1.7k tokens; Ollama's 2048 default
# would silently truncate the tail.
NUM_CTX = 4096
# Bounds worst-case latency, not correctness: a verdict cut off at the cap is
# recovered by _salvage_truncated_json below.
NUM_PREDICT = 700
# Must absorb worst-case model load + prompt eval + decode on a slow CPU.
CHAT_TIMEOUT = 600.0


def warm_chat_model() -> None:
    """Make Ollama load the chat model without generating anything: an empty
    /api/generate call returns once the model is in memory."""
    httpx.post(
        f"{settings.ollama_host}/api/generate",
        json={"model": settings.ollama_model},
        timeout=CHAT_TIMEOUT,
    ).raise_for_status()


@lru_cache(maxsize=1)
def _physical_cores() -> int:
    """Unique (physical id, core id) pairs from /proc/cpuinfo — the count
    Ollama itself sizes threads by. Falls back to cpu_count if unreadable."""
    try:
        cores: set[tuple[str, str]] = set()
        physical_id = "0"
        with open("/proc/cpuinfo") as f:
            for line in f:
                if line.startswith("physical id"):
                    physical_id = line.split(":", 1)[1].strip()
                elif line.startswith("core id"):
                    cores.add((physical_id, line.split(":", 1)[1].strip()))
        if cores:
            return len(cores)
    except OSError:
        pass
    return os.cpu_count() or 1


@lru_cache(maxsize=1)
def resolve_num_thread() -> int | None:
    """Threads per request; None leaves it to Ollama (settings.map_num_thread
    == 0). Auto (-1) never exceeds the cores the CPU profiles' pinning allows,
    nor the physical core count — oversubscribed threads slow decode down."""
    n = settings.map_num_thread
    if n == 0:
        return None
    if n > 0:
        return n
    allowed = max(1, (os.cpu_count() or 3) - 2)
    return min(_physical_cores(), allowed)


@lru_cache(maxsize=1)
def resolve_map_workers() -> int:
    """Concurrent mapping calls. Auto (-1) uses the same >= 10 GiB threshold as
    the CPU profile's OLLAMA_NUM_PARALLEL sizing, so the backend never sends
    more concurrent verdicts than the server has slots."""
    n = settings.map_workers
    if n > 0:
        return n
    try:
        with open("/proc/meminfo") as f:
            for line in f:
                if line.startswith("MemTotal"):
                    mem_gib = int(line.split()[1]) / 1048576
                    return 4 if mem_gib >= 10 else 2
    except (OSError, ValueError, IndexError):
        pass
    return 4


def _salvage_truncated_json(content: str) -> dict | None:
    """Best-effort parse of a response cut off at the num_predict cap.

    Grammar-constrained decoding guarantees `content` is a prefix of valid
    JSON, so the complete part is recoverable: re-parse at successively earlier
    value boundaries (positions outside string literals, so quotes and braces
    in generated text can't fool the cut) with the containers open at that
    point closed. The truncated tail item is dropped. None if nothing
    parseable remains, and the caller re-raises.
    """
    cuts: list[tuple[int, str]] = []  # (cut position, closing suffix)
    stack: list[str] = []
    in_string = escape = False
    for i, ch in enumerate(content):
        if in_string:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_string = False
                cuts.append((i + 1, "".join(reversed(stack))))
        elif ch == '"':
            in_string = True
        elif ch in "{[":
            stack.append("}" if ch == "{" else "]")
            cuts.append((i + 1, "".join(reversed(stack))))
        elif ch in "}]":
            if not stack:
                return None  # not a prefix of valid JSON after all
            stack.pop()
            cuts.append((i + 1, "".join(reversed(stack))))
    for pos, suffix in reversed(cuts[-200:]):
        try:
            parsed = json.loads(content[:pos] + suffix)
        except json.JSONDecodeError:
            continue  # cut after an object key etc. — try an earlier boundary
        if isinstance(parsed, dict):
            return parsed
    return None


def chat_json(
    prompt: str,
    response_schema: dict,
    client: httpx.Client | None = None,
    system: str | None = None,
) -> dict:
    """One chat turn, response constrained to `response_schema` and parsed."""
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})

    options: dict = {"temperature": 0, "num_ctx": NUM_CTX, "num_predict": NUM_PREDICT}
    num_thread = resolve_num_thread()
    if num_thread is not None:
        options["num_thread"] = num_thread

    payload = {
        "model": settings.ollama_model,
        "messages": messages,
        "stream": False,
        "format": response_schema,
        "options": options,
    }
    url = f"{settings.ollama_host}/api/chat"
    if client is not None:
        response = client.post(url, json=payload)
    else:
        response = httpx.post(url, timeout=CHAT_TIMEOUT, json=payload)
    response.raise_for_status()
    content = response.json()["message"]["content"]
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        salvaged = _salvage_truncated_json(content)
        if salvaged is None:
            raise
        logger.warning(
            "LLM response hit the %d-token cap mid-JSON (%d chars); salvaged the prefix",
            NUM_PREDICT,
            len(content),
        )
        return salvaged

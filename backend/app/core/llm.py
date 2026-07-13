"""Ollama chat client for the LLM mapping stage (pipeline stage 6).

Uses /api/chat with a JSON-schema `format` constraint so the model's output is
grammar-constrained server-side — the decoder literally cannot emit tokens that
violate the schema. That, plus temperature 0, is most of the reliability story
for a small (3B) local model; the rest is validation of the *content* (e.g.
technique ids actually being among the offered candidates), which lives with
the caller in app.mapping.mapper.
"""

import json
import logging
import os
from functools import lru_cache

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)

# One chunk + 8 trimmed candidates + instructions ≈ 1.7k tokens; Ollama's
# default 2048 ctx would silently truncate the tail, so size it explicitly.
NUM_CTX = 4096
# Hard cap on generated tokens per verdict. Without a cap, a small model in
# constrained-JSON mode can ramble for minutes on a slow CPU before closing
# the object. Hitting the cap cuts the JSON mid-token (seen at 400 and again
# at 700 with an evidence-rich chunk); chat_json salvages the complete prefix
# instead of failing, so the cap bounds latency, not correctness.
NUM_PREDICT = 700
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
    """None = leave it to Ollama. See settings.map_num_thread for the modes."""
    n = settings.map_num_thread
    if n == 0:
        return None
    if n > 0:
        return n
    # auto: never more threads than the cores the CPU profiles' pinning allows
    # ollama to run on (all-but-two), and never more than physical cores
    # (hyperthreads slow decode down — measured on the 16-thread dev host).
    allowed = max(1, (os.cpu_count() or 3) - 2)
    return min(_physical_cores(), allowed)


@lru_cache(maxsize=1)
def resolve_map_workers() -> int:
    """Concurrent mapping calls: settings.map_workers, or -1 = auto by RAM.

    Auto uses the same >= 10 GiB threshold as the docker-compose.cpu.yml
    ollama entrypoint sizing OLLAMA_NUM_PARALLEL, so the backend never sends
    more concurrent verdicts than the server has slots (extras would just
    queue server-side). /proc/meminfo shows the whole VM/host total, the same
    number the ollama container sees."""
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
    JSON, so the complete part is recoverable: re-parse at successively
    earlier value boundaries (positions outside string literals, so quotes
    and braces inside generated text can't fool the cut) with the containers
    still open at that point closed. The truncated tail item is dropped —
    for mapping verdicts its half quote would fail the evidence check anyway.
    Returns None if nothing parseable remains (caller re-raises the original).
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
            continue  # cut after an object key etc. — try one boundary earlier
        if isinstance(parsed, dict):
            return parsed
    return None


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
            "LLM response hit the %d-token cap mid-JSON (%d chars); "
            "salvaged the complete prefix",
            NUM_PREDICT,
            len(content),
        )
        return salvaged

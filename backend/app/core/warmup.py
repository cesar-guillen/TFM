"""Tracks whether the Ollama chat model is loaded, and on which device — so the
UI can tell the user "the GPU is being set up / the LLM is warming up" instead
of showing a stalled progress bar, and can word it correctly for the hardware
actually in use (a CPU-only machine must never see "GPU").

The device can't be asked for directly: Ollama has no capability endpoint, but
/api/ps reports `size_vram` per *loaded* model, so gpu-vs-cpu is derivable the
moment any model (even just the small embed model) is resident. Until then it
stays None and the frontend uses a device-neutral wording.
"""

import threading
from typing import Literal

import httpx

from app.core.config import settings

Status = Literal["unknown", "loading", "ready", "unavailable"]
Device = Literal["gpu", "cpu"] | None

_lock = threading.Lock()
_status: Status = "unknown"
_device: Device = None

PROBE_TIMEOUT = 2.0


def mark_loading() -> None:
    global _status
    with _lock:
        _status = "loading"


def mark_ready(device: Device) -> None:
    global _status, _device
    with _lock:
        _status = "ready"
        if device is not None:
            _device = device


def mark_unavailable() -> None:
    global _status
    with _lock:
        _status = "unavailable"


def _loaded_models() -> list[dict]:
    response = httpx.get(f"{settings.ollama_host}/api/ps", timeout=PROBE_TIMEOUT)
    response.raise_for_status()
    return response.json().get("models") or []


def detect_device() -> Device:
    """gpu/cpu judged from whatever models are currently loaded; None if
    nothing is loaded yet (or Ollama is unreachable) — i.e. not yet knowable."""
    try:
        models = _loaded_models()
    except Exception:
        return None
    if not models:
        return None
    return "gpu" if any(m.get("size_vram", 0) > 0 for m in models) else "cpu"


def is_chat_model_loaded() -> bool:
    """Whether the mapping model is resident right now. False on any probe
    failure — callers then warm it, which surfaces the real error properly."""
    try:
        models = _loaded_models()
    except Exception:
        return False
    return any(
        m.get("name") == settings.ollama_model or m.get("model") == settings.ollama_model
        for m in models
    )


def get_state() -> dict:
    """Current warm-up state for the /api/warmup endpoint. While loading, the
    device may become knowable mid-flight (the embed model loads first and
    already betrays gpu-vs-cpu), so probe lazily until it's cached."""
    global _device
    with _lock:
        status, device = _status, _device
    if device is None and status == "loading":
        device = detect_device()
        if device is not None:
            with _lock:
                _device = device
    return {"status": status, "device": device, "model": settings.ollama_model}

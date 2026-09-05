"""Tracks whether the Ollama chat model is loaded, and on which device, so the
UI can say "the GPU is being set up" / "loading the LLM (CPU mode)" instead of
showing a stalled progress bar — and never shows GPU wording on a CPU-only
machine.

Ollama has no capability endpoint, but /api/ps reports `size_vram` per loaded
model, so the device is derivable as soon as anything is resident. Until then
it stays None and the frontend words it neutrally.
"""

import threading
from typing import Literal

import httpx

from app.core.config import settings

Status = Literal["unknown", "loading", "ready", "unavailable"]
Device = Literal["gpu", "cpu"] | None

PROBE_TIMEOUT = 2.0

_lock = threading.Lock()
_status: Status = "unknown"
_device: Device = None


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
    """gpu/cpu judged from the currently loaded models; None while nothing is
    loaded (or Ollama is unreachable), i.e. not yet knowable."""
    try:
        models = _loaded_models()
    except Exception:
        return None
    if not models:
        return None
    return "gpu" if any(m.get("size_vram", 0) > 0 for m in models) else "cpu"


def is_chat_model_loaded() -> bool:
    """Whether the mapping model is resident. False on any probe failure —
    callers then warm it, which surfaces the real error properly."""
    try:
        models = _loaded_models()
    except Exception:
        return False
    return any(
        m.get("name") == settings.ollama_model or m.get("model") == settings.ollama_model
        for m in models
    )


def get_state() -> dict:
    """Warm-up state for GET /api/warmup. The device can become knowable
    mid-load (the embed model lands first), so probe until it is cached."""
    global _device
    with _lock:
        status, device = _status, _device
    if device is None and status == "loading":
        device = detect_device()
        if device is not None:
            with _lock:
                _device = device
    return {"status": status, "device": device, "model": settings.ollama_model}

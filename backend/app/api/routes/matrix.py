import threading

from fastapi import APIRouter

router = APIRouter()

# Most recently generated layer (stages 6-7 output), served to any client that
# asks. In-memory module state, consistent with the scaffold's job registries —
# no session/persistence concept yet, so "the current matrix" is process-wide
# and resets on backend restart.
_current_layer: dict | None = None
_lock = threading.Lock()


def set_current_layer(layer: dict) -> None:
    global _current_layer
    with _lock:
        _current_layer = layer


def clear_current_layer() -> None:
    """Drop the previous report's layer. Called when a new report is uploaded,
    so /matrix never serves mappings that belong to a replaced report."""
    global _current_layer
    with _lock:
        _current_layer = None


def empty_layer() -> dict:
    return {
        "name": "TFM generated layer",
        "versions": {"attack": "19", "navigator": "5.1.0", "layer": "4.5"},
        "domain": "enterprise-attack",
        "description": "No report has been mapped yet",
        "techniques": [],
    }


@router.get("/matrix")
async def get_matrix():
    with _lock:
        return _current_layer if _current_layer is not None else empty_layer()

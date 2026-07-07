import threading
import uuid

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.mapping import history

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


# ── Saved-matrix history (see app.mapping.history) ──────────────────────────
# Unlike the current layer above, these survive new uploads and backend
# restarts: every completed mapping run is written to disk automatically, and
# the /matrix editor saves manual edits back here (PUT to the entry being
# edited, POST for a hand-built or imported matrix that has no entry yet).


class SavedMatrixBody(BaseModel):
    name: str
    layer: dict


@router.get("/matrix/history")
async def matrix_history():
    return history.list_layers()


@router.post("/matrix/history")
async def create_matrix_history_entry(body: SavedMatrixBody):
    # filename=None marks a manually saved matrix (vs. a generated run, whose
    # entry carries its source report's filename).
    return history.save_layer(str(uuid.uuid4()), body.name, None, body.layer)


@router.get("/matrix/history/{layer_id}")
async def matrix_history_entry(layer_id: str):
    entry = history.load_layer(layer_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="No saved matrix with that id")
    return entry


@router.put("/matrix/history/{layer_id}")
async def update_matrix_history_entry(layer_id: str, body: SavedMatrixBody):
    entry = history.update_layer(layer_id, body.name, body.layer)
    if entry is None:
        raise HTTPException(status_code=404, detail="No saved matrix with that id")
    return entry


@router.delete("/matrix/history/{layer_id}")
async def delete_matrix_history_entry(layer_id: str):
    if not history.delete_layer(layer_id):
        raise HTTPException(status_code=404, detail="No saved matrix with that id")
    return {"deleted": layer_id}

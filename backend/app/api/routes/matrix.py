import re
import threading
import uuid

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field, field_validator

from app.mapping import history

router = APIRouter()

# Layer entries a saved matrix may carry: comfortably above the ~1000 entries
# a full ATT&CK layer needs, low enough to reject absurd payloads.
MAX_LAYER_TECHNIQUES = 5000

_SAFE_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")

# Most recently generated layer, served process-wide. In-memory like the job
# registries: there is no session concept, so it resets on backend restart.
# Completed runs also live on disk in the matrix library (app.mapping.history).
_current_layer: dict | None = None
_lock = threading.Lock()


def set_current_layer(layer: dict) -> None:
    global _current_layer
    with _lock:
        _current_layer = layer


def clear_current_layer() -> None:
    """Drop the previous report's layer, so /matrix never serves mappings that
    belong to a replaced report."""
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


def _validated_id(layer_id: str) -> str:
    if not _SAFE_ID_RE.match(layer_id):
        raise HTTPException(status_code=404, detail="No saved matrix with that id")
    return layer_id


@router.get("/matrix")
async def get_matrix():
    with _lock:
        return _current_layer if _current_layer is not None else empty_layer()


class SavedMatrixBody(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    layer: dict

    @field_validator("layer")
    @classmethod
    def _check_layer(cls, layer: dict) -> dict:
        techniques = layer.get("techniques")
        if not isinstance(techniques, list):
            raise ValueError("layer.techniques must be a list")
        if len(techniques) > MAX_LAYER_TECHNIQUES:
            raise ValueError(f"layer carries more than {MAX_LAYER_TECHNIQUES} techniques")
        return layer


@router.get("/matrix/history")
async def matrix_history():
    return history.list_layers()


@router.post("/matrix/history")
async def create_matrix_history_entry(body: SavedMatrixBody):
    # filename=None marks a hand-saved matrix, as opposed to a generated run.
    return history.save_layer(str(uuid.uuid4()), body.name, None, body.layer)


@router.get("/matrix/history/{layer_id}")
async def matrix_history_entry(layer_id: str):
    entry = history.load_layer(_validated_id(layer_id))
    if entry is None:
        raise HTTPException(status_code=404, detail="No saved matrix with that id")
    return entry


@router.put("/matrix/history/{layer_id}")
async def update_matrix_history_entry(layer_id: str, body: SavedMatrixBody):
    entry = history.update_layer(_validated_id(layer_id), body.name, body.layer)
    if entry is None:
        raise HTTPException(status_code=404, detail="No saved matrix with that id")
    return entry


@router.delete("/matrix/history/{layer_id}")
async def delete_matrix_history_entry(layer_id: str):
    if not history.delete_layer(_validated_id(layer_id)):
        raise HTTPException(status_code=404, detail="No saved matrix with that id")
    return {"deleted": layer_id}

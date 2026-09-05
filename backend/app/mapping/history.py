"""On-disk matrix library: one JSON file per saved layer under
settings.layers_dir. Every finished mapping run is saved automatically, and
the editor saves manual edits back here (see the history routes in
app.api.routes.matrix)."""

import json
import os
from datetime import datetime, timezone

from app.core.config import settings

_SUMMARY_KEYS = (
    "id",
    "name",
    "filename",
    "created_at",
    "updated_at",
    "technique_count",
    "duration_seconds",
)


def _path(layer_id: str) -> str:
    # basename() guards the path: ids arrive via URL in the routes.
    return os.path.join(settings.layers_dir, f"{os.path.basename(layer_id)}.json")


def _write(entry: dict) -> None:
    """Write via a temporary file and rename, so an interrupted save can never
    leave a half-written entry behind."""
    os.makedirs(settings.layers_dir, exist_ok=True)
    path = _path(entry["id"])
    tmp_path = f"{path}.tmp"
    with open(tmp_path, "w") as f:
        json.dump(entry, f)
    os.replace(tmp_path, path)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def save_layer(
    layer_id: str,
    name: str,
    filename: str | None,
    layer: dict,
    duration_seconds: float | None = None,
) -> dict:
    """Persist a layer, overwriting any previous entry for the same id (a
    re-run of the same report keeps its original created_at). Stamps the layer
    with `tfm_saved_id` so a client holding only the layer knows which entry it
    belongs to. `duration_seconds` is the mapping run's wall time, None for
    hand-saved matrices."""
    existing = load_layer(layer_id)
    layer["tfm_saved_id"] = layer_id
    entry = {
        "id": layer_id,
        "name": name,
        "filename": filename,
        "created_at": existing["created_at"] if existing else _now(),
        "updated_at": _now(),
        "technique_count": len(layer.get("techniques", [])),
        "duration_seconds": duration_seconds,
        "layer": layer,
    }
    _write(entry)
    return entry


def update_layer(layer_id: str, name: str, layer: dict) -> dict | None:
    """Overwrite an existing entry's name and layer, keeping its filename,
    created_at and duration. None if the id is unknown, which the route turns
    into a 404 rather than resurrecting a deleted entry."""
    entry = load_layer(layer_id)
    if entry is None:
        return None
    layer["tfm_saved_id"] = layer_id
    entry.update(
        name=name,
        layer=layer,
        technique_count=len(layer.get("techniques", [])),
        updated_at=_now(),
    )
    _write(entry)
    return entry


def list_layers() -> list[dict]:
    """Summaries (without the layer body) of every saved entry, most recently
    touched first. Unreadable files are skipped rather than fatal."""
    if not os.path.isdir(settings.layers_dir):
        return []
    summaries = []
    for entry_file in os.listdir(settings.layers_dir):
        if not entry_file.endswith(".json"):
            continue
        try:
            with open(os.path.join(settings.layers_dir, entry_file)) as f:
                entry = json.load(f)
            summaries.append({k: entry.get(k) for k in _SUMMARY_KEYS})
        except (OSError, ValueError):
            continue
    summaries.sort(key=lambda s: s.get("updated_at") or s.get("created_at") or "", reverse=True)
    return summaries


def load_layer(layer_id: str) -> dict | None:
    try:
        with open(_path(layer_id)) as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def delete_layer(layer_id: str) -> bool:
    try:
        os.remove(_path(layer_id))
        return True
    except OSError:
        return False

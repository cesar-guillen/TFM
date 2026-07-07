"""Disk persistence of computed matrices, one JSON file per entry under
settings.layers_dir. This is what backs the dashboard's matrix library: every
finished mapping run is saved automatically, and the /matrix editor can save
manual edits back (PUT) or save a hand-built/imported matrix as a new entry
(POST) — see the history routes in app.api.routes.matrix."""

import json
import os
from datetime import datetime, timezone

from app.core.config import settings

_SUMMARY_KEYS = ("id", "name", "filename", "created_at", "updated_at", "technique_count")


def _path(layer_id: str) -> str:
    # basename() guards the path — ids arrive via URL in the routes.
    return os.path.join(settings.layers_dir, f"{os.path.basename(layer_id)}.json")


def _write(entry: dict) -> None:
    os.makedirs(settings.layers_dir, exist_ok=True)
    with open(_path(entry["id"]), "w") as f:
        json.dump(entry, f)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def save_layer(layer_id: str, name: str, filename: str | None, layer: dict) -> dict:
    """Persist a layer under `layer_id`, overwriting any previous entry for it
    (a re-run of the same report keeps its original created_at). Stamps the
    layer itself with `tfm_saved_id` so a client holding just the layer (e.g.
    via GET /api/matrix) can tell which history entry it belongs to and update
    it instead of saving a duplicate."""
    existing = load_layer(layer_id)
    layer["tfm_saved_id"] = layer_id
    entry = {
        "id": layer_id,
        "name": name,
        "filename": filename,
        "created_at": existing["created_at"] if existing else _now(),
        "updated_at": _now(),
        "technique_count": len(layer.get("techniques", [])),
        "layer": layer,
    }
    _write(entry)
    return entry


def update_layer(layer_id: str, name: str, layer: dict) -> dict | None:
    """Overwrite an existing entry's name + layer (manual edits from the
    editor), keeping its filename and created_at. None if the id is unknown —
    the route turns that into a 404 rather than resurrecting a deleted entry."""
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
    """Summaries (no layer body — the list endpoint stays light) of every
    saved entry, most recently touched first. Unreadable files are skipped,
    not fatal."""
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

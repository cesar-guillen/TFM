import logging
import os
import time
from typing import Literal

import httpx
from fastapi import APIRouter, BackgroundTasks, HTTPException
from pydantic import BaseModel

from app.api.routes import matrix
from app.core import warmup
from app.core.config import settings
from app.core.llm import warm_chat_model
from app.ingest.jobs import get_job as get_ingest_job
from app.mapping import history
from app.mapping.aggregate import aggregate_mappings
from app.mapping.jobs import (
    TERMINAL_STATUSES,
    create_job,
    get_job,
    is_cancel_requested,
    request_cancel,
    step_seconds_snapshot,
    update_job,
)
from app.mapping.mapper import MappingAborted, map_report

router = APIRouter()
logger = logging.getLogger(__name__)


class MapOptions(BaseModel):
    """Per-run overrides; each None falls back to the configured default."""

    verify_mode: Literal["off", "demote", "drop"] | None = None
    verdict_mode: Literal["menu", "independent"] | None = None
    report_type: Literal["incident", "pentest"] | None = None


def _process(
    report_id: str,
    verify: str | None = None,
    verdict: str | None = None,
    report_type: str | None = None,
) -> None:
    """Background mapping + aggregation run, polled via
    GET /reports/{report_id}/map/status."""
    try:
        # Surface a cold model as its own phase instead of silently absorbing
        # the load into the first chunk's verdict.
        if not warmup.is_chat_model_loaded():
            update_job(report_id, status="warming")
            warmup.mark_loading()
            try:
                warm_chat_model()
            except Exception:
                warmup.mark_unavailable()
                raise
            warmup.mark_ready(warmup.detect_device())

        # The model load can't be interrupted; honor a cancel that arrived
        # while it was underway.
        if is_cancel_requested(report_id):
            raise MappingAborted()

        update_job(report_id, status="retrieving")

        def on_progress(chunks_mapped: int, chunk_count: int, mappings_so_far) -> None:
            # Re-aggregate after every chunk so the dashboard matrix fills in
            # live. Cheap: a few dozen mappings per report.
            partial = aggregate_mappings(mappings_so_far)
            matrix.set_current_layer(partial)
            update_job(
                report_id,
                status="mapping",
                chunk_count=chunk_count,
                chunks_mapped=chunks_mapped,
                layer=partial,
            )

        mappings = map_report(
            report_id,
            on_progress=on_progress,
            should_abort=lambda: is_cancel_requested(report_id),
            on_phase=lambda phase: update_job(report_id, status=phase),
            verify=verify,
            verdict=verdict,
            report_type=report_type,
        )
        update_job(report_id, status="aggregating")
        layer = aggregate_mappings(mappings)

        ingest_job = get_ingest_job(report_id)
        source_filename = ingest_job.filename if ingest_job else report_id
        layer["name"] = os.path.splitext(source_filename)[0]

        # Save first: save_layer stamps tfm_saved_id into the layer, so the
        # published current layer tells the editor which entry to update.
        job = get_job(report_id)
        duration = round(time.time() - job.started_at, 1) if job else None
        history.save_layer(
            report_id, layer["name"], source_filename, layer, duration_seconds=duration
        )
        matrix.set_current_layer(layer)
        update_job(report_id, status="done", layer=layer)
    except MappingAborted:
        # Drop the partial layer published during the run; only completed runs
        # are saved to the library.
        matrix.clear_current_layer()
        update_job(report_id, status="cancelled", layer=None)
    except httpx.HTTPError:
        update_job(
            report_id,
            status="error",
            error=f"Mapping failed talking to Ollama — is '{settings.ollama_model}' pulled?",
        )
    except Exception:
        logger.exception("mapping failed for report %s", report_id)
        update_job(report_id, status="error", error="Mapping failed — see the backend logs.")


@router.post("/reports/{report_id}/map")
def start_mapping(
    report_id: str, background_tasks: BackgroundTasks, options: MapOptions | None = None
):
    """Start LLM mapping for an ingested report. Returns immediately; poll the
    status endpoint for progress and the resulting layer."""
    ingest_job = get_ingest_job(report_id)
    if ingest_job is None:
        raise HTTPException(status_code=404, detail="Unknown report_id")
    if ingest_job.status != "done":
        raise HTTPException(
            status_code=409, detail=f"Report is not ingested yet (status: {ingest_job.status})"
        )

    existing = get_job(report_id)
    if existing is not None and existing.status not in TERMINAL_STATUSES:
        return {"report_id": report_id, "status": existing.status}

    create_job(report_id)
    background_tasks.add_task(
        _process,
        report_id,
        options.verify_mode if options else None,
        options.verdict_mode if options else None,
        options.report_type if options else None,
    )
    return {"report_id": report_id, "status": "retrieving"}


@router.post("/reports/{report_id}/map/cancel")
def cancel_mapping(report_id: str):
    """Ask a running mapping job to stop. Queued chunks are dropped; verdicts
    already in flight finish server-side and are discarded."""
    job = get_job(report_id)
    if job is None:
        raise HTTPException(status_code=404, detail="No mapping job for this report_id")
    cancelling = job.status not in TERMINAL_STATUSES and request_cancel(report_id)
    return {"report_id": report_id, "status": job.status, "cancelling": bool(cancelling)}


@router.get("/reports/{report_id}/map/status")
def mapping_status(report_id: str):
    job = get_job(report_id)
    if job is None:
        raise HTTPException(status_code=404, detail="No mapping job for this report_id")

    return {
        "report_id": job.report_id,
        "status": job.status,
        "chunk_count": job.chunk_count,
        "chunks_mapped": job.chunks_mapped,
        "layer": job.layer,  # partial while mapping, final at "done"
        "error": job.error,
        "elapsed_seconds": round((job.finished_at or time.time()) - job.started_at, 1),
        "step_seconds": step_seconds_snapshot(job),
    }

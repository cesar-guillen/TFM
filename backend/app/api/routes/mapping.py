import os

import httpx
from fastapi import APIRouter, BackgroundTasks, HTTPException

from app.api.routes import matrix
from app.core import warmup
from app.core.config import settings
from app.core.llm import warm_chat_model
from app.ingest.jobs import get_job as get_ingest_job
from app.mapping import history
from app.mapping.aggregate import aggregate_mappings
from app.mapping.jobs import create_job, get_job, update_job
from app.mapping.mapper import map_report

router = APIRouter()


def _process(report_id: str) -> None:
    """Background stage 6+7 run; mirrors the ingest job pattern (poll via
    GET /reports/{report_id}/map/status) since mapping is minutes-slow on CPU."""
    try:
        # If the chat model isn't resident (first run after startup racing the
        # warm-up thread, or evicted after idle under a KEEP_ALIVE duration),
        # the first chunk verdicts would silently absorb the whole model-load
        # wait. Surface it as its own job phase instead, and keep
        # app.core.warmup current so the UI can word it per-device.
        if not warmup.is_chat_model_loaded():
            update_job(report_id, status="warming")
            warmup.mark_loading()
            try:
                warm_chat_model()
            except Exception:
                warmup.mark_unavailable()
                raise
            warmup.mark_ready(warmup.detect_device())

        update_job(report_id, status="retrieving")

        def on_progress(chunks_mapped: int, chunk_count: int, mappings_so_far) -> None:
            # Re-aggregate and publish after every chunk so the dashboard
            # matrix fills in live while the run is still going. Cheap: a few
            # dozen mappings per report.
            partial = aggregate_mappings(mappings_so_far)
            matrix.set_current_layer(partial)
            update_job(
                report_id,
                status="mapping",
                chunk_count=chunk_count,
                chunks_mapped=chunks_mapped,
                layer=partial,
            )

        mappings = map_report(report_id, on_progress=on_progress)
        update_job(report_id, status="aggregating")
        layer = aggregate_mappings(mappings)

        # Name the finished layer after the report (the aggregate default is
        # generic) and persist it to the on-disk history, so it stays openable
        # after the next upload replaces the current layer.
        ingest_job = get_ingest_job(report_id)
        source_filename = ingest_job.filename if ingest_job else report_id
        layer["name"] = os.path.splitext(source_filename)[0]

        # Save first: save_layer stamps `tfm_saved_id` into the layer dict, so
        # the published current layer tells the editor which entry to update.
        history.save_layer(report_id, layer["name"], source_filename, layer)
        matrix.set_current_layer(layer)
        update_job(report_id, status="done", layer=layer)
    except httpx.HTTPError as exc:
        update_job(
            report_id,
            status="error",
            error=(
                f"Mapping failed talking to Ollama — is '{settings.ollama_model}' pulled? ({exc})"
            ),
        )
    except Exception as exc:  # surface any other failure to the poller instead of dying silently
        update_job(report_id, status="error", error=str(exc))


@router.post("/reports/{report_id}/map")
def start_mapping(report_id: str, background_tasks: BackgroundTasks):
    """Kick off LLM mapping for an ingested report. Returns immediately; poll
    the status endpoint for progress and the resulting layer."""
    ingest_job = get_ingest_job(report_id)
    if ingest_job is None:
        raise HTTPException(status_code=404, detail="Unknown report_id")
    if ingest_job.status != "done":
        raise HTTPException(status_code=409, detail=f"Report is not ingested yet (status: {ingest_job.status})")

    existing = get_job(report_id)
    if existing is not None and existing.status not in ("done", "error"):
        return {"report_id": report_id, "status": existing.status}

    create_job(report_id)
    background_tasks.add_task(_process, report_id)
    return {"report_id": report_id, "status": "retrieving"}


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
        "layer": job.layer,  # partial while status == "mapping", final at "done"
        "error": job.error,
    }

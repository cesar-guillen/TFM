import os
import threading
import uuid

import httpx
from fastapi import APIRouter, BackgroundTasks, HTTPException, UploadFile

from app.api.routes import matrix
from app.attack.embeddings import embed_texts
from app.core.config import settings
from app.ingest.indexing import IndexingAborted, index_report
from app.ingest.jobs import (
    TERMINAL_STATUSES,
    create_job,
    get_job,
    is_cancel_requested,
    request_cancel,
    step_seconds_snapshot,
    update_job,
)
from app.ingest.pdf_to_markdown import pdf_to_markdown

router = APIRouter()


def _warm_embed_model() -> None:
    """Fire-and-forget: make Ollama load the embedding model now, so the load
    overlaps PDF parsing instead of stalling the first chunk's embed request.
    Errors are ignored — if Ollama is down, the real embed step reports it."""
    try:
        embed_texts(["warmup"])
    except Exception:
        pass


def _process(report_id: str, filename: str, dest_path: str) -> None:
    """Runs in a background task, after the response is already sent — parsing
    and (especially) embedding are slow, so the client shouldn't block on them.
    Progress is polled via GET /ingest/{report_id}/status instead."""
    try:
        threading.Thread(target=_warm_embed_model, daemon=True).start()
        update_job(report_id, status="parsing")
        markdown = pdf_to_markdown(dest_path)

        if is_cancel_requested(report_id):
            raise IndexingAborted()

        markdown_path = os.path.join(settings.upload_dir, f"{report_id}.md")
        with open(markdown_path, "w") as f:
            f.write(markdown)

        update_job(report_id, status="chunking")

        def on_progress(chunks_embedded: int, chunk_count: int) -> None:
            update_job(report_id, status="embedding", chunk_count=chunk_count, chunks_embedded=chunks_embedded)

        chunks, skipped = index_report(
            report_id,
            filename,
            markdown,
            on_progress=on_progress,
            should_abort=lambda: is_cancel_requested(report_id),
        )
        update_job(
            report_id, status="done", markdown=markdown, chunk_count=len(chunks), chunks_skipped=skipped
        )
    except IndexingAborted:
        # User cancelled. Nothing reached Chroma (indexing writes once, at the
        # end); the uploaded PDF stays on disk like any other upload.
        update_job(report_id, status="cancelled")
    except httpx.HTTPError as exc:
        update_job(
            report_id,
            status="error",
            error=(
                "Report was parsed but chunks could not be embedded — is Ollama running "
                f"with '{settings.ollama_embed_model}' pulled? ({exc})"
            ),
        )
    except Exception as exc:  # surface any other failure to the poller instead of dying silently
        update_job(report_id, status="error", error=str(exc))


@router.post("/ingest")
def ingest(file: UploadFile, background_tasks: BackgroundTasks):
    """Returns as soon as the upload is saved to disk — parsing and embedding
    happen in a background task, tracked via app.ingest.jobs and polled through
    GET /ingest/{report_id}/status, instead of making the client wait out the
    full ~100s+ an embedding-heavy report takes."""
    if file.content_type != "application/pdf":
        raise HTTPException(status_code=400, detail="Only PDF uploads are supported")

    report_id = str(uuid.uuid4())
    os.makedirs(settings.upload_dir, exist_ok=True)
    dest_path = os.path.join(settings.upload_dir, f"{report_id}_{file.filename}")
    with open(dest_path, "wb") as f:
        f.write(file.file.read())

    # A new report replaces the previous one everywhere: the old report's
    # matrix must not linger while (or after) the new one is processed.
    matrix.clear_current_layer()

    create_job(report_id, file.filename)
    background_tasks.add_task(_process, report_id, file.filename, dest_path)

    return {"report_id": report_id, "filename": file.filename, "status": "parsing"}


@router.post("/ingest/{report_id}/cancel")
def cancel_ingest(report_id: str):
    """Ask a running ingest to stop. Takes effect at the next safe boundary
    (between pipeline steps / embedding batches); no-op if already finished."""
    job = get_job(report_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Unknown report_id")
    cancelling = job.status not in TERMINAL_STATUSES and request_cancel(report_id)
    return {"report_id": report_id, "status": job.status, "cancelling": bool(cancelling)}


@router.get("/ingest/{report_id}/status")
def ingest_status(report_id: str):
    job = get_job(report_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Unknown report_id")

    return {
        "report_id": job.report_id,
        "filename": job.filename,
        "status": job.status,
        "chunk_count": job.chunk_count,
        "chunks_embedded": job.chunks_embedded,
        "chunks_skipped": job.chunks_skipped,
        "markdown": job.markdown if job.status == "done" else None,
        "error": job.error,
        # Per-step durations (parsing/chunking/embedding), the running step
        # included at its elapsed-so-far.
        "step_seconds": step_seconds_snapshot(job),
    }

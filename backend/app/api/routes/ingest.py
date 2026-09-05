import logging
import os
import re
import threading
import uuid

import httpx
from fastapi import APIRouter, BackgroundTasks, Form, HTTPException, UploadFile

from app.api.routes import matrix
from app.attack.embeddings import embed_texts
from app.core import warmup
from app.core.config import settings
from app.core.llm import warm_chat_model
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
from app.ingest.pdf_to_markdown import PdfParseError, pdf_to_markdown

router = APIRouter()
logger = logging.getLogger(__name__)

MAX_UPLOAD_BYTES = 64 * 1024 * 1024
UPLOAD_CHUNK_BYTES = 1024 * 1024
PDF_MAGIC = b"%PDF-"
_UNSAFE_FILENAME_CHARS = re.compile(r"[^A-Za-z0-9._-]")


def _safe_filename(filename: str | None) -> str:
    """A display/storage-safe basename: no directory components, no separators
    or shell metacharacters, bounded length."""
    name = _UNSAFE_FILENAME_CHARS.sub("_", os.path.basename(filename or "").strip())
    name = name.lstrip(".")[:120]
    return name or "report.pdf"


def _save_upload(file: UploadFile, dest_path: str) -> None:
    """Stream the upload to disk, rejecting anything that isn't a PDF or that
    exceeds MAX_UPLOAD_BYTES. A rejected upload leaves no file behind."""
    size = 0
    try:
        with open(dest_path, "wb") as out:
            while chunk := file.file.read(UPLOAD_CHUNK_BYTES):
                if size == 0 and not chunk.startswith(PDF_MAGIC):
                    raise HTTPException(status_code=400, detail="File is not a PDF")
                size += len(chunk)
                if size > MAX_UPLOAD_BYTES:
                    raise HTTPException(
                        status_code=413,
                        detail=f"PDF is larger than {MAX_UPLOAD_BYTES // (1024 * 1024)} MB",
                    )
                out.write(chunk)
        if size == 0:
            raise HTTPException(status_code=400, detail="Uploaded file is empty")
    except BaseException:
        if os.path.exists(dest_path):
            os.remove(dest_path)
        raise


def _warm_models_for_run() -> None:
    """Fire-and-forget: load the embedding model while the PDF is still being
    parsed, then the chat model so its (minutes-long on CPU) load overlaps
    embedding instead of stalling the mapping run that auto-starts next. Both
    are no-ops when the model is already resident; errors are left for the real
    pipeline steps to report."""
    try:
        embed_texts(["warmup"])
    except Exception:
        pass
    if warmup.is_chat_model_loaded():
        return
    warmup.mark_loading()
    try:
        warm_chat_model()
        warmup.mark_ready(warmup.detect_device())
    except Exception:
        warmup.mark_unavailable()


def _process(report_id: str, filename: str, dest_path: str, ocr_enabled: bool) -> None:
    """Parse, chunk and embed the report. Runs after the response is sent;
    progress is polled via GET /ingest/{report_id}/status."""
    try:
        threading.Thread(target=_warm_models_for_run, daemon=True).start()
        update_job(report_id, status="parsing")
        markdown = pdf_to_markdown(dest_path, ocr_enabled=ocr_enabled)

        if is_cancel_requested(report_id):
            raise IndexingAborted()

        markdown_path = os.path.join(settings.upload_dir, f"{report_id}.md")
        with open(markdown_path, "w") as f:
            f.write(markdown)

        update_job(report_id, status="chunking")

        def on_progress(chunks_embedded: int, chunk_count: int) -> None:
            update_job(
                report_id,
                status="embedding",
                chunk_count=chunk_count,
                chunks_embedded=chunks_embedded,
            )

        chunks, skipped = index_report(
            report_id,
            filename,
            markdown,
            on_progress=on_progress,
            should_abort=lambda: is_cancel_requested(report_id),
        )
        update_job(
            report_id,
            status="done",
            markdown=markdown,
            chunk_count=len(chunks),
            chunks_skipped=skipped,
        )
    except IndexingAborted:
        update_job(report_id, status="cancelled")
    except PdfParseError:
        logger.warning("could not parse the PDF for report %s", report_id, exc_info=True)
        update_job(
            report_id,
            status="error",
            error="Could not read that PDF — it may be corrupt, encrypted, or password-protected.",
        )
    except httpx.HTTPError:
        update_job(
            report_id,
            status="error",
            error=(
                "Report was parsed but chunks could not be embedded — is Ollama running "
                f"with '{settings.ollama_embed_model}' pulled?"
            ),
        )
    except Exception:
        logger.exception("ingest failed for report %s", report_id)
        update_job(report_id, status="error", error="Ingest failed — see the backend logs.")


@router.post("/ingest")
def ingest(
    file: UploadFile,
    background_tasks: BackgroundTasks,
    ocr: bool = Form(True),
):
    """Save an uploaded PDF and start the ingest pipeline in the background.
    Returns as soon as the file is on disk. `ocr` (default on) controls
    whether embedded screenshots are OCR'd (app/ingest/ocr.py) — exposed as a
    per-run toggle in the upload options dialog rather than a fixed setting,
    since measured effect is genre-dependent (a clear recall win on
    log/terminal-heavy reports, noisier on UI-screenshot-heavy ones — see
    CLAUDE.md's DFIR OCR evaluation notes)."""
    report_id = str(uuid.uuid4())
    filename = _safe_filename(file.filename)
    os.makedirs(settings.upload_dir, exist_ok=True)
    dest_path = os.path.join(settings.upload_dir, f"{report_id}_{filename}")
    _save_upload(file, dest_path)

    # A new report replaces the previous one: its matrix must not linger.
    matrix.clear_current_layer()

    create_job(report_id, filename)
    background_tasks.add_task(_process, report_id, filename, dest_path, ocr)

    return {"report_id": report_id, "filename": filename, "status": "parsing"}


@router.post("/ingest/{report_id}/cancel")
def cancel_ingest(report_id: str):
    """Ask a running ingest to stop; it settles at the next safe boundary."""
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
        "step_seconds": step_seconds_snapshot(job),
    }

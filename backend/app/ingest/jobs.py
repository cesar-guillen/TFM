import threading
from dataclasses import dataclass
from typing import Literal

Status = Literal["parsing", "chunking", "embedding", "done", "error", "cancelled"]

TERMINAL_STATUSES = ("done", "error", "cancelled")


@dataclass
class IngestJob:
    report_id: str
    filename: str
    status: Status = "parsing"
    chunk_count: int = 0
    chunks_embedded: int = 0
    chunks_skipped: int = 0  # remediation/boilerplate chunks excluded by the section filter
    markdown: str | None = None
    error: str | None = None
    # Cooperative cancellation: set via request_cancel(), checked by the worker
    # between pipeline steps and embedding batches. Chroma is written once,
    # atomically, at the end of indexing — an aborted ingest stores nothing.
    cancel_requested: bool = False


_jobs: dict[str, IngestJob] = {}
_lock = threading.Lock()


def create_job(report_id: str, filename: str) -> IngestJob:
    job = IngestJob(report_id=report_id, filename=filename)
    with _lock:
        _jobs[report_id] = job
    return job


def get_job(report_id: str) -> IngestJob | None:
    with _lock:
        return _jobs.get(report_id)


def update_job(report_id: str, **fields: object) -> None:
    with _lock:
        job = _jobs.get(report_id)
        if job is None:
            return
        for key, value in fields.items():
            setattr(job, key, value)


def request_cancel(report_id: str) -> bool:
    """Flag a running job for cancellation. Returns False if there's no job or
    it already reached a terminal state (nothing to cancel)."""
    with _lock:
        job = _jobs.get(report_id)
        if job is None or job.status in TERMINAL_STATUSES:
            return False
        job.cancel_requested = True
        return True


def is_cancel_requested(report_id: str) -> bool:
    with _lock:
        job = _jobs.get(report_id)
        return job is not None and job.cancel_requested

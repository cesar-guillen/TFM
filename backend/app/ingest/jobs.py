import threading
import time
from dataclasses import dataclass, field
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
    # Per-step timing: update_job records how long each status lasted when it
    # transitions away from it (accumulating, in case a status recurs). The
    # status endpoint adds the still-running step's elapsed on top.
    status_changed_at: float = field(default_factory=time.time)
    step_seconds: dict[str, float] = field(default_factory=dict)
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
        previous = job.status
        for key, value in fields.items():
            setattr(job, key, value)
        if job.status != previous:
            now = time.time()
            job.step_seconds[previous] = job.step_seconds.get(previous, 0.0) + (now - job.status_changed_at)
            job.status_changed_at = now


def step_seconds_snapshot(job: IngestJob) -> dict[str, float]:
    """Completed steps' durations plus the still-running step's elapsed so far
    (frozen once the job is terminal)."""
    steps = {k: round(v, 1) for k, v in job.step_seconds.items()}
    if job.status not in TERMINAL_STATUSES:
        steps[job.status] = round(
            steps.get(job.status, 0.0) + (time.time() - job.status_changed_at), 1
        )
    return steps


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

"""In-memory registry for LLM mapping jobs (pipeline stages 6-7), polled by the
client the same way ingest jobs are — see app.ingest.jobs for the pattern
rationale (plain dict + lock, fine for a single-process dev scaffold)."""

import threading
import time
from dataclasses import dataclass, field
from typing import Literal

Status = Literal["warming", "retrieving", "mapping", "aggregating", "done", "error", "cancelled"]

TERMINAL_STATUSES = ("done", "error", "cancelled")


@dataclass
class MappingJob:
    report_id: str
    status: Status = "retrieving"
    chunk_count: int = 0
    chunks_mapped: int = 0
    layer: dict | None = None  # Navigator layer JSON; partial during "mapping", final at "done"
    error: str | None = None
    # Run timing: started when the job is created (so warming/retrieving count
    # too), frozen by update_job the moment the status turns terminal. The
    # status endpoint derives elapsed_seconds from these.
    started_at: float = field(default_factory=time.time)
    finished_at: float | None = None
    # Per-phase timing, mirroring app.ingest.jobs: update_job accumulates a
    # phase's duration when the status transitions away from it; the status
    # endpoint adds the running phase's elapsed on top.
    status_changed_at: float = field(default_factory=time.time)
    step_seconds: dict[str, float] = field(default_factory=dict)
    # Cooperative cancellation: set via request_cancel(), checked by the worker
    # at safe boundaries (between stages / chunk verdicts) — an in-flight LLM
    # call is never interrupted, its result is just discarded.
    cancel_requested: bool = False


_jobs: dict[str, MappingJob] = {}
_lock = threading.Lock()


def create_job(report_id: str) -> MappingJob:
    job = MappingJob(report_id=report_id)
    with _lock:
        _jobs[report_id] = job
    return job


def get_job(report_id: str) -> MappingJob | None:
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
        if job.status in TERMINAL_STATUSES and job.finished_at is None:
            job.finished_at = time.time()


def step_seconds_snapshot(job: MappingJob) -> dict[str, float]:
    """Completed phases' durations plus the running phase's elapsed so far
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

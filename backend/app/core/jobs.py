"""Shared in-memory job registry for the pipeline's background stages.

Ingest and mapping both expose the same shape to the frontend: a job keyed by
report_id, a status that walks through named phases, per-phase timings, and
cooperative cancellation. There is no session or persistence concept — jobs
live for the backend process's lifetime, which is all the polling endpoints
need.
"""

import threading
import time
from dataclasses import dataclass, field

TERMINAL_STATUSES = ("done", "error", "cancelled")


@dataclass(kw_only=True)
class Job:
    report_id: str
    status: str
    error: str | None = None
    # Timing: started when the job is created, frozen the moment the status
    # turns terminal.
    started_at: float = field(default_factory=time.time)
    finished_at: float | None = None
    # Per-phase timing: a phase's duration is accumulated when the status
    # transitions away from it.
    status_changed_at: float = field(default_factory=time.time)
    step_seconds: dict[str, float] = field(default_factory=dict)
    # Set via request_cancel, polled by the worker at safe boundaries; work
    # already in flight is never interrupted, only discarded.
    cancel_requested: bool = False


def step_seconds_snapshot(job: Job) -> dict[str, float]:
    """Completed phases' durations plus the running phase's elapsed so far,
    frozen once the job is terminal."""
    steps = {k: round(v, 1) for k, v in job.step_seconds.items()}
    if job.status not in TERMINAL_STATUSES:
        steps[job.status] = round(
            steps.get(job.status, 0.0) + (time.time() - job.status_changed_at), 1
        )
    return steps


class JobRegistry:
    """Thread-safe map of report_id -> job."""

    def __init__(self) -> None:
        self._jobs: dict[str, Job] = {}
        self._lock = threading.Lock()

    def add(self, job: Job) -> Job:
        with self._lock:
            self._jobs[job.report_id] = job
        return job

    def get(self, report_id: str) -> Job | None:
        with self._lock:
            return self._jobs.get(report_id)

    def update(self, report_id: str, **fields: object) -> None:
        with self._lock:
            job = self._jobs.get(report_id)
            if job is None:
                return
            previous = job.status
            for key, value in fields.items():
                setattr(job, key, value)
            if job.status != previous:
                now = time.time()
                job.step_seconds[previous] = job.step_seconds.get(previous, 0.0) + (
                    now - job.status_changed_at
                )
                job.status_changed_at = now
            if job.status in TERMINAL_STATUSES and job.finished_at is None:
                job.finished_at = time.time()

    def request_cancel(self, report_id: str) -> bool:
        """Flag a running job for cancellation. False when there is no job, or
        it already reached a terminal state."""
        with self._lock:
            job = self._jobs.get(report_id)
            if job is None or job.status in TERMINAL_STATUSES:
                return False
            job.cancel_requested = True
            return True

    def is_cancel_requested(self, report_id: str) -> bool:
        with self._lock:
            job = self._jobs.get(report_id)
            return job is not None and job.cancel_requested

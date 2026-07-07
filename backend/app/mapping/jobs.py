"""In-memory registry for LLM mapping jobs (pipeline stages 6-7), polled by the
client the same way ingest jobs are — see app.ingest.jobs for the pattern
rationale (plain dict + lock, fine for a single-process dev scaffold)."""

import threading
from dataclasses import dataclass
from typing import Literal

Status = Literal["warming", "retrieving", "mapping", "aggregating", "done", "error"]


@dataclass
class MappingJob:
    report_id: str
    status: Status = "retrieving"
    chunk_count: int = 0
    chunks_mapped: int = 0
    layer: dict | None = None  # Navigator layer JSON; partial during "mapping", final at "done"
    error: str | None = None


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
        for key, value in fields.items():
            setattr(job, key, value)

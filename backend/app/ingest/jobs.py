import threading
from dataclasses import dataclass
from typing import Literal

Status = Literal["parsing", "chunking", "embedding", "done", "error"]


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

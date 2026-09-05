"""Ingest job registry (parse -> chunk -> embed), polled by the client."""

from dataclasses import dataclass
from typing import Literal

from app.core.jobs import TERMINAL_STATUSES, Job, JobRegistry, step_seconds_snapshot

__all__ = [
    "TERMINAL_STATUSES",
    "IngestJob",
    "create_job",
    "get_job",
    "update_job",
    "request_cancel",
    "is_cancel_requested",
    "step_seconds_snapshot",
]

Status = Literal["parsing", "chunking", "embedding", "done", "error", "cancelled"]


@dataclass(kw_only=True)
class IngestJob(Job):
    filename: str
    status: Status = "parsing"
    chunk_count: int = 0
    chunks_embedded: int = 0
    chunks_skipped: int = 0  # guidance/boilerplate chunks the section filter dropped
    markdown: str | None = None


_registry = JobRegistry()


def create_job(report_id: str, filename: str) -> IngestJob:
    return _registry.add(IngestJob(report_id=report_id, filename=filename))


def get_job(report_id: str) -> IngestJob | None:
    return _registry.get(report_id)


def update_job(report_id: str, **fields: object) -> None:
    _registry.update(report_id, **fields)


def request_cancel(report_id: str) -> bool:
    return _registry.request_cancel(report_id)


def is_cancel_requested(report_id: str) -> bool:
    return _registry.is_cancel_requested(report_id)

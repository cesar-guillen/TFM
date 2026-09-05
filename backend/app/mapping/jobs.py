"""Mapping job registry (retrieve -> LLM verdicts -> aggregate)."""

from dataclasses import dataclass
from typing import Literal

from app.core.jobs import TERMINAL_STATUSES, Job, JobRegistry, step_seconds_snapshot

__all__ = [
    "TERMINAL_STATUSES",
    "MappingJob",
    "create_job",
    "get_job",
    "update_job",
    "request_cancel",
    "is_cancel_requested",
    "step_seconds_snapshot",
]

Status = Literal[
    "warming", "retrieving", "mapping", "filtering", "aggregating", "done", "error", "cancelled"
]


@dataclass(kw_only=True)
class MappingJob(Job):
    status: Status = "retrieving"
    chunk_count: int = 0
    chunks_mapped: int = 0
    layer: dict | None = None  # partial while mapping, final at "done"


_registry = JobRegistry()


def create_job(report_id: str) -> MappingJob:
    return _registry.add(MappingJob(report_id=report_id))


def get_job(report_id: str) -> MappingJob | None:
    return _registry.get(report_id)


def update_job(report_id: str, **fields: object) -> None:
    _registry.update(report_id, **fields)


def request_cancel(report_id: str) -> bool:
    return _registry.request_cancel(report_id)


def is_cancel_requested(report_id: str) -> bool:
    return _registry.is_cancel_requested(report_id)

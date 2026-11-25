from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Iterable


class JobStatus(str, Enum):
    PENDING = "pending"
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    TIMEOUT = "timeout"


@dataclass
class JobRecord:
    job_id: str
    user_id: str
    image: str
    command: list[str]
    job_root: str
    status: JobStatus = JobStatus.QUEUED
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"))
    started_at: str | None = None
    finished_at: str | None = None
    exit_code: int | None = None
    error_message: str | None = None
    timeout_seconds: int = 300


class JobQueue:
    def __init__(self, jobs: Iterable[JobRecord] | None = None):
        self._jobs: list[JobRecord] = list(jobs or [])

    def enqueue(
        self,
        job_id: str,
        user_id: str,
        image: str,
        command: list[str],
        job_root: str | None = None,
        status: JobStatus = JobStatus.QUEUED,
    ) -> JobRecord:
        if any(job.job_id == job_id for job in self._jobs):
            raise ValueError(f"Job {job_id} já existe na fila.")

        root = str(job_root or str(Path("/tmp") / job_id))
        job = JobRecord(
            job_id=job_id,
            user_id=user_id,
            image=image,
            command=list(command),
            job_root=root,
            status=status,
        )
        self._jobs.append(job)
        return job

    def enqueue_record(self, record: JobRecord) -> JobRecord:
        """Insere um JobRecord existente na fila (usado na recuperação de boot)."""
        existing = self.get_by_id(record.job_id)
        if existing:
            return existing
        self._jobs.append(record)
        return record

    def get_by_id(self, job_id: str) -> JobRecord | None:
        for job in self._jobs:
            if job.job_id == job_id:
                return job
        return None

    def peek_next(self) -> JobRecord | None:
        for job in self._jobs:
            if job.status in {JobStatus.QUEUED, JobStatus.PENDING}:
                return job
        return None

    def list_jobs(self) -> list[JobRecord]:
        return list(self._jobs)

    def update_status(self, job_id: str, status: JobStatus, **kwargs: Any) -> JobRecord | None:
        job = self.get_by_id(job_id)
        if job is None:
            return None

        job.status = status
        for key, value in kwargs.items():
            if hasattr(job, key):
                setattr(job, key, value)

        return job

    def remove(self, job_id: str) -> JobRecord | None:
        for index, job in enumerate(self._jobs):
            if job.job_id == job_id:
                return self._jobs.pop(index)
        return None

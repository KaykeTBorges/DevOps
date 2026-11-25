from __future__ import annotations

import os
import subprocess
import sys
import threading
from datetime import datetime, timezone
from pathlib import Path

queue_dir = Path(__file__).resolve().parents[1] / "queue"
if str(queue_dir) not in sys.path:
    sys.path.insert(0, str(queue_dir))

# Carrega configuração centralizada do admin
config_dir = Path(__file__).resolve().parents[2] / "config"
if str(config_dir) not in sys.path:
    sys.path.insert(0, str(config_dir))

try:
    from server_config import (
        SERVER_CPUS,
        SERVER_MEMORY,
        SERVER_GPU_COUNT,
        SERVER_GPU_DEVICE,
        DEFAULT_TIMEOUT,
    )
except ImportError:
    # Fallback se a config não estiver disponível
    SERVER_CPUS = os.environ.get("SERVER_CPUS", "4.0")
    SERVER_MEMORY = os.environ.get("SERVER_MEMORY", "16g")
    SERVER_GPU_COUNT = int(os.environ.get("SERVER_GPU_COUNT", "0"))
    SERVER_GPU_DEVICE = os.environ.get("SERVER_GPU_DEVICE", None)
    DEFAULT_TIMEOUT = int(os.environ.get("DEFAULT_TIMEOUT", "300"))

from queue_manager import JobQueue, JobStatus


class JobScheduler:
    def __init__(self, queue: JobQueue, executor_path: str | None = None, claim_job=None):
        self.queue = queue
        self.executor_path = executor_path or str(Path(__file__).resolve().parents[1] / "executor" / "job_executor.py")
        self.claim_job = claim_job
        self._run_lock = threading.Lock()

    @staticmethod
    def _utc_now() -> str:
        return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    def run_next(self):
        if not self._run_lock.acquire(blocking=False):
            return None

        try:
            job = self.queue.peek_next()
            if job is None:
                return None

            if self.claim_job and not self.claim_job(job.job_id):
                self.queue.remove(job.job_id)
                return None

            self.queue.update_status(job.job_id, JobStatus.RUNNING, started_at=self._utc_now())
            running_job = self.queue.get_by_id(job.job_id)
            if running_job is None:
                return None

            # === PILAR 3: Usa SEMPRE os recursos definidos pelo admin ===
            cmd = [
                sys.executable,
                self.executor_path,
                "--job-id",
                running_job.job_id,
                "--job-root",
                running_job.job_root,
                "--image",
                running_job.image,
                "--cpu-limit",
                str(SERVER_CPUS),
                "--memory-limit",
                str(SERVER_MEMORY),
                "--timeout-seconds",
                str(running_job.timeout_seconds or DEFAULT_TIMEOUT),
            ]

            # GPU controlada pelo admin
            if SERVER_GPU_COUNT > 0:
                cmd.extend(["--gpu-count", str(SERVER_GPU_COUNT)])
                if SERVER_GPU_DEVICE:
                    cmd.extend(["--gpu-device", SERVER_GPU_DEVICE])

            cmd.append("--command")
            cmd.extend(running_job.command)

            completed = subprocess.run(cmd, capture_output=True, text=True)
            final_status = JobStatus.COMPLETED if completed.returncode == 0 else JobStatus.FAILED
            if completed.returncode == 124:
                final_status = JobStatus.TIMEOUT

            current_job = self.queue.get_by_id(running_job.job_id)
            if current_job and current_job.status == JobStatus.CANCELLED:
                return current_job

            self.queue.update_status(
                running_job.job_id,
                final_status,
                exit_code=completed.returncode,
                finished_at=self._utc_now(),
                error_message=(completed.stderr or completed.stdout or None),
            )

            return self.queue.get_by_id(running_job.job_id)
        finally:
            self._run_lock.release()

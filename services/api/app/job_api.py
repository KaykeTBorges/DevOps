from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

queue_dir = Path(__file__).resolve().parents[2] / "job-manager" / "queue"
scheduler_dir = Path(__file__).resolve().parents[2] / "job-manager" / "scheduler"
executor_dir = Path(__file__).resolve().parents[2] / "job-manager" / "executor"

for candidate in [queue_dir, scheduler_dir, executor_dir]:
    path_str = str(candidate)
    if path_str not in sys.path:
        sys.path.insert(0, path_str)

from queue_manager import JobQueue, JobRecord, JobStatus
from scheduler import JobScheduler
from job_executor import kill_job_container, inspect_job_container

try:
    from job_store import JobStore
except ImportError:
    from .job_store import JobStore


class JobApiService:
    def __init__(
        self,
        queue: JobQueue | None = None,
        scheduler: JobScheduler | None = None,
        store: JobStore | None = None,
        auto_recover: bool = True,
    ):
        self.store = store
        self.queue = queue or JobQueue()
        self.scheduler = scheduler or JobScheduler(
            self.queue,
            executor_path=str(executor_dir / "job_executor.py"),
            claim_job=self.store.claim_job if self.store else None,
        )
        if auto_recover and self.store:
            self.recover_state_on_startup()

    @staticmethod
    def _serialize(job) -> dict:
        return {
            "job_id": job.job_id,
            "user_id": job.user_id,
            "image": job.image,
            "command": job.command,
            "job_root": job.job_root,
            "status": job.status.value if hasattr(job.status, "value") else str(job.status),
            "created_at": job.created_at,
            "started_at": job.started_at,
            "finished_at": job.finished_at,
            "exit_code": job.exit_code,
            "error_message": job.error_message,
        }

    def create_job(
        self,
        job_id: str,
        user_id: str,
        image: str,
        command: list[str],
        job_root: str | None = None,
        original_filename: str | None = None,
        timeout_seconds: int = 300,
    ) -> dict:
        job = self.queue.enqueue(job_id, user_id, image, command, job_root=job_root)
        job.timeout_seconds = timeout_seconds
        if self.store is not None:
            self.store.create_job(
                job_id=job_id,
                user_id=user_id,
                original_filename=original_filename,
                status=job.status.value if hasattr(job.status, "value") else str(job.status),
                command=" ".join(command),
                image=image,
                output_path=str(Path(job.job_root) / "output"),
                timeout_seconds=timeout_seconds,
            )
        return self._serialize(job)

    def list_jobs(self, user_id: str | None = None) -> list[dict]:
        if self.store is not None:
            return self.store.list_jobs(user_id=user_id)
        jobs = self.queue.list_jobs()
        if user_id:
            jobs = [j for j in jobs if j.user_id == user_id]
        return [self._serialize(job) for job in jobs]

    def get_job(self, job_id: str) -> dict | None:
        job = self.queue.get_by_id(job_id)
        if job is None:
            if self.store is not None:
                record = self.store.get_job(job_id)
                if record:
                    return record
            return None
        return self._serialize(job)

    def get_status(self, job_id: str) -> dict | None:
        job = self.queue.get_by_id(job_id)
        if job is None:
            if self.store is not None:
                record = self.store.get_job(job_id)
                if record:
                    return {"job_id": record["job_id"], "status": record["status"]}
            return None
        return {"job_id": job.job_id, "status": job.status.value if hasattr(job.status, "value") else str(job.status)}

    def run_next_job(self) -> dict | None:
        job = self.scheduler.run_next()
        if job is None:
            return None
        if self.store is not None:
            status_val = job.status.value if hasattr(job.status, "value") else str(job.status)
            stored = self.store.get_job(job.job_id)
            if not stored or stored.get("status") != JobStatus.CANCELLED.value:
                self.store.update_status(
                    job.job_id,
                    status=status_val,
                    started_at=job.started_at,
                    finished_at=job.finished_at,
                    exit_code=job.exit_code,
                    error_message=job.error_message,
                )
        return self._serialize(job)

    def get_logs(self, job_id: str) -> dict | None:
        job = self.queue.get_by_id(job_id)
        if job is None:
            return None

        log_path = Path(job.job_root) / "logs" / "job.log"
        if not log_path.exists():
            return {"job_id": job.job_id, "logs": ""}

        return {"job_id": job.job_id, "logs": log_path.read_text(encoding="utf-8", errors="replace")}

    def get_output(self, job_id: str) -> dict | None:
        job = self.queue.get_by_id(job_id)
        if job is None:
            return None

        out_dir = Path(job.job_root) / "output"
        if not out_dir.exists():
            return {"job_id": job.job_id, "output_dir": str(out_dir), "files": []}

        files = [str(path.relative_to(out_dir)) for path in sorted(out_dir.rglob("*")) if path.is_file()]
        return {"job_id": job.job_id, "output_dir": str(out_dir), "files": files}

    def delete_job(self, job_id: str, user_id: str | None = None) -> bool:
        job_db = self.store.get_job(job_id) if self.store else None
        job_q = self.queue.get_by_id(job_id)

        if not job_db and not job_q:
            return False

        current_user = job_db.get("user_id") if job_db else (job_q.user_id if job_q else None)
        if user_id and current_user and user_id != current_user and user_id != "admin":
            return False

        # Garante que qualquer container ativo seja interrompido
        kill_job_container(job_id)

        deleted_any = False
        if job_q is not None:
            self.queue.remove(job_id)
            job_root = Path(job_q.job_root)
            if job_root.exists():
                shutil.rmtree(job_root, ignore_errors=True)
            deleted_any = True

        if self.store is not None:
            if not deleted_any and job_db and job_db.get("output_path"):
                job_root = Path(job_db["output_path"]).parent
                if job_root.exists():
                    shutil.rmtree(job_root, ignore_errors=True)
            if self.store.delete_job(job_id):
                deleted_any = True

        return deleted_any

    def cancel_job(self, job_id: str, user_id: str | None = None) -> tuple[bool, str]:
        """Cancela um job em execução ou na fila, encerrando o container com docker kill."""
        job_db = self.store.get_job(job_id) if self.store else None
        job_q = self.queue.get_by_id(job_id)

        if not job_db and not job_q:
            return False, f"Job {job_id} não encontrado."

        current_user = job_db.get("user_id") if job_db else (job_q.user_id if job_q else None)
        if user_id and current_user and user_id != current_user and user_id != "admin":
            return False, "Permissão negada: você só pode cancelar seus próprios jobs."

        # Interrompe o container Docker se estiver em execução
        kill_job_container(job_id)

        now = self.store._utc_now() if self.store else "now"

        # Atualiza status na fila
        if job_q:
            self.queue.update_status(
                job_id,
                JobStatus.CANCELLED,
                finished_at=now,
                error_message="Job cancelado pelo usuário.",
            )

        # Atualiza status no banco
        if self.store:
            self.store.update_status(
                job_id,
                status="cancelled",
                finished_at=now,
                error_message="Job cancelado pelo usuário.",
            )

        return True, f"Job {job_id} cancelado com sucesso."

    def recover_state_on_startup(self) -> dict[str, int]:
        """Recupera o estado da fila e de jobs em execução após reinício do servidor.
        
        - Para jobs que estavam rodando: verifica se o container Docker ainda está ativo;
          se já terminou, consolida exit_code e outputs; se não existe mais, finaliza.
        - Para jobs na fila: reinsere na fila em memória mantendo ordem e dados.
        """
        if not self.store:
            return {"recovered_running": 0, "recovered_queued": 0}

        recovered_running = 0
        recovered_queued = 0

        # 1. Trata jobs com status 'running' deixados pelo processo anterior
        running_jobs = self.store.get_running_jobs()
        for r_job in running_jobs:
            job_id = r_job["job_id"]
            state = inspect_job_container(job_id)

            if state and state.get("Running"):
                # O container continua executando na máquina!
                recovered_running += 1
            elif state and not state.get("Running"):
                # O container terminou enquanto o servidor estava fora
                exit_code = state.get("ExitCode", 0)
                final_status = "completed" if exit_code == 0 else "failed"
                self.store.update_status(
                    job_id,
                    status=final_status,
                    exit_code=exit_code,
                    finished_at=self.store._utc_now(),
                    error_message=None if exit_code == 0 else "Container finalizado durante reinício do servidor.",
                )
                recovered_running += 1
            else:
                # Container inexistente no Docker
                out_dir = Path(r_job.get("output_path") or "")
                has_output = out_dir.exists() and any(out_dir.iterdir())
                final_status = "completed" if has_output else "failed"
                self.store.update_status(
                    job_id,
                    status=final_status,
                    exit_code=0 if has_output else 137,
                    finished_at=self.store._utc_now(),
                    error_message=None if has_output else "Execução interrompida pela parada do servidor.",
                )
                recovered_running += 1

        # 2. Reinsere jobs pendentes/queued na fila de memória
        queued_jobs = self.store.get_queued_jobs()
        for q_job in queued_jobs:
            job_id = q_job["job_id"]
            if not self.queue.get_by_id(job_id):
                raw_cmd = q_job.get("command") or "python main.py"
                cmd_parts = raw_cmd.split() if isinstance(raw_cmd, str) else list(raw_cmd)
                root_path = (
                    str(Path(q_job.get("output_path", "")).parent)
                    if q_job.get("output_path")
                    else f"/tmp/{job_id}"
                )
                record = JobRecord(
                    job_id=job_id,
                    user_id=q_job["user_id"],
                    image=q_job.get("image") or "python:3.12-slim",
                    command=cmd_parts,
                    job_root=root_path,
                    status=JobStatus.QUEUED,
                    created_at=q_job.get("created_at") or self.store._utc_now(),
                    timeout_seconds=q_job.get("timeout_seconds") or 300,
                )
                self.queue.enqueue_record(record)
                recovered_queued += 1

        return {"recovered_running": recovered_running, "recovered_queued": recovered_queued}

    def build_response(self, action: str, payload: dict | None = None) -> dict:
        return {"action": action, "payload": payload or {}}

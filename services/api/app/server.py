#!/usr/bin/env python3
"""Servidor HTTP integrado para a API do AI Compute Server e interface Web.

Implementado utilizando a biblioteca padrão (sem necessidade de frameworks externos
e sem o módulo obsoleto 'cgi'), expondo os endpoints REST para autenticação
passwordless (@academico.ufpb.br), upload de ZIP, controle da fila, cancelamento
com 'docker kill', logs, outputs e servindo o frontend web.
"""

from __future__ import annotations

import io
import json
import logging
import mimetypes
import os
import shutil
import subprocess
import sys
import threading
import uuid
from datetime import datetime, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

# Resolução de paths
APP_DIR = Path(__file__).resolve().parent
REPO_ROOT = APP_DIR.parents[2]
QUEUE_DIR = REPO_ROOT / "services" / "job-manager" / "queue"
SCHEDULER_DIR = REPO_ROOT / "services" / "job-manager" / "scheduler"
EXECUTOR_DIR = REPO_ROOT / "services" / "job-manager" / "executor"
FRONTEND_DIR = REPO_ROOT / "services" / "frontend" / "web"
CONFIG_DIR = REPO_ROOT / "config"
STORAGE_ROOT = REPO_ROOT / "storage" / "jobs"
DB_PATH = REPO_ROOT / "db" / "jobs.db"
ALLOWED_ORIGIN = os.environ.get("ALLOWED_ORIGIN", "http://localhost:8000")
MAX_UPLOAD_REQUEST_BYTES = 110 * 1024 * 1024

for p in [str(APP_DIR), str(QUEUE_DIR), str(SCHEDULER_DIR), str(EXECUTOR_DIR), str(CONFIG_DIR)]:
    if p not in sys.path:
        sys.path.insert(0, p)

from job_api import JobApiService
from job_executor import build_job_layout
from job_store import JobStore, OtpRateLimitError
from job_upload import ZipSecurityValidator, ZipValidationError
from multipart_parser import parse_multipart
from server_config import (
    ADMIN_HARD_CAP_TIMEOUT,
    DEV_AUTH_MOCK,
    MAX_QUEUED_JOBS_PER_USER,
    MIN_TIMEOUT,
    OTP_MAX_ATTEMPTS,
    OTP_EXPIRATION_SECONDS,
    OTP_REQUEST_INTERVAL_SECONDS,
    SERVER_CPUS,
    SERVER_GPU_COUNT,
    SERVER_GPU_DEVICE,
    SERVER_MEMORY,
    get_active_images,
    validate_email_domain,
    validate_image_id,
    validate_timeout,
    validate_user_quota,
)

SCRIPTS_DIR = REPO_ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))
from cleanup_jobs import cleanup_expired_jobs

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("api-server")


def collect_system_metrics() -> dict:
    metrics: dict[str, object] = {}
    try:
        metrics["load_average"] = list(os.getloadavg())
    except (AttributeError, OSError):
        metrics["load_average"] = []

    try:
        memory = {}
        for line in Path("/proc/meminfo").read_text(encoding="utf-8").splitlines():
            key, value = line.split(":", 1)
            memory[key] = int(value.strip().split()[0]) * 1024
        metrics["memory"] = {
            "total_bytes": memory.get("MemTotal", 0),
            "available_bytes": memory.get("MemAvailable", 0),
        }
    except (OSError, ValueError):
        metrics["memory"] = {}

    try:
        disk = shutil.disk_usage(STORAGE_ROOT)
        metrics["disk"] = {
            "total_bytes": disk.total,
            "used_bytes": disk.used,
            "free_bytes": disk.free,
        }
    except OSError:
        metrics["disk"] = {}

    try:
        gpu = subprocess.run(
            ["nvidia-smi", "--query-gpu=index,name,utilization.gpu,memory.used,memory.total", "--format=csv,noheader,nounits"],
            capture_output=True,
            text=True,
            timeout=3,
            check=False,
        )
        metrics["gpu"] = [line.strip() for line in gpu.stdout.splitlines() if line.strip()] if gpu.returncode == 0 else []
    except (OSError, subprocess.SubprocessError):
        metrics["gpu"] = []

    return metrics


class ApiServerHandler(BaseHTTPRequestHandler):
    store = JobStore(DB_PATH)
    service = JobApiService(store=store)

    def _send_json(self, data: dict | list, status_code: int = HTTPStatus.OK) -> None:
        payload = json.dumps(data, indent=2).encode("utf-8")
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Access-Control-Allow-Origin", ALLOWED_ORIGIN)
        self.send_header("Access-Control-Allow-Methods", "GET, POST, DELETE, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
        self.end_headers()
        self.wfile.write(payload)

    def _send_text(self, text: str, status_code: int = HTTPStatus.OK, content_type: str = "text/plain; charset=utf-8") -> None:
        payload = text.encode("utf-8")
        self.send_response(status_code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Access-Control-Allow-Origin", ALLOWED_ORIGIN)
        self.end_headers()
        self.wfile.write(payload)

    def _send_file(self, file_path: Path) -> None:
        if not file_path.exists() or not file_path.is_file():
            self._send_json({"error": "Arquivo não encontrado"}, HTTPStatus.NOT_FOUND)
            return

        mime_type, _ = mimetypes.guess_type(str(file_path))
        mime_type = mime_type or "application/octet-stream"
        file_size = file_path.stat().st_size

        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", mime_type)
        self.send_header("Content-Length", str(file_size))
        self.send_header("Access-Control-Allow-Origin", ALLOWED_ORIGIN)
        self.end_headers()

        with file_path.open("rb") as f:
            shutil.copyfileobj(f, self.wfile)

    def _get_authenticated_user(self, form_token: str | None = None) -> dict | None:
        """Extrai e valida o token de autenticação do header ou formulário."""
        auth_header = self.headers.get("Authorization", "")
        token = ""
        if auth_header.startswith("Bearer "):
            token = auth_header[7:].strip()
        elif form_token:
            token = form_token.strip()
        if not token:
            return None
        return self.store.get_user_by_token(token)

    def _require_authenticated_user(self) -> dict | None:
        user = self._get_authenticated_user()
        if not user:
            self._send_json({"error": "Autenticação obrigatória."}, HTTPStatus.UNAUTHORIZED)
        return user

    def _get_authorized_job(self, job_id: str, user: dict | None) -> dict | None:
        if not user:
            return None
        job = self.store.get_job(job_id)
        if not job:
            self._send_json({"error": f"Job {job_id} não encontrado"}, HTTPStatus.NOT_FOUND)
            return None
        if user.get("role") != "admin" and job.get("user_id") != user.get("email"):
            self._send_json({"error": "Job não encontrado"}, HTTPStatus.NOT_FOUND)
            return None
        return job

    def do_OPTIONS(self) -> None:
        self.send_response(HTTPStatus.NO_CONTENT)
        self.send_header("Access-Control-Allow-Origin", ALLOWED_ORIGIN)
        self.send_header("Access-Control-Allow-Methods", "GET, POST, DELETE, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
        self.end_headers()

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/")
        if not path:
            path = "/"

        # Frontend estático
        if path == "/":
            index_path = FRONTEND_DIR / "index.html"
            if index_path.exists():
                self._send_file(index_path)
            else:
                self._send_text("Frontend web em construção. Acesse a API em /api/jobs", HTTPStatus.OK)
            return

        # GET /api/auth/me (Pilar 1: Consulta usuário autenticado)
        if path == "/api/auth/me":
            user = self._get_authenticated_user()
            if not user:
                self._send_json({"error": "Não autenticado ou token expirado."}, HTTPStatus.UNAUTHORIZED)
                return
            self._send_json({"user": user})
            return

        if path == "/api/health":
            try:
                status_counts = self.store.get_status_counts()
                storage_bytes = sum(
                    file_path.stat().st_size
                    for file_path in STORAGE_ROOT.rglob("*")
                    if file_path.is_file()
                ) if STORAGE_ROOT.exists() else 0
                self._send_json({
                    "status": "ok",
                    "jobs": status_counts,
                    "storage_bytes": storage_bytes,
                    "system": collect_system_metrics(),
                })
            except Exception:
                self._send_json({"status": "degraded"}, HTTPStatus.SERVICE_UNAVAILABLE)
            return

        if path == "/api/metrics":
            user = self._require_authenticated_user()
            if not user:
                return
            status_counts = self.store.get_status_counts()
            storage_bytes = sum(
                file_path.stat().st_size
                for file_path in STORAGE_ROOT.rglob("*")
                if file_path.is_file()
            ) if STORAGE_ROOT.exists() else 0
            self._send_json({
                "jobs": status_counts,
                "storage_bytes": storage_bytes,
                "system": collect_system_metrics(),
            })
            return

        # GET /api/catalog/images — retorna catálogo de imagens aprovadas (Pilar 2)
        if path == "/api/catalog/images":
            images = get_active_images()
            catalog = [
                {
                    "id": img["id"],
                    "display_name": img["display_name"],
                    "description": img["description"],
                    "gpu_required": img["gpu_required"],
                }
                for img in images
            ]
            self._send_json({
                "images": catalog,
                "admin_config": {
                    "hard_cap_timeout": ADMIN_HARD_CAP_TIMEOUT,
                    "min_timeout": MIN_TIMEOUT,
                    "max_queued_jobs_per_user": MAX_QUEUED_JOBS_PER_USER,
                },
            })
            return

        # GET /api/jobs (com filtro opcional de usuário)
        if path == "/api/jobs":
            user = self._require_authenticated_user()
            if not user:
                return
            params = parse_qs(parsed.query)
            requested_user = params.get("user_id", [None])[0]
            user_id = requested_user if user.get("role") == "admin" and requested_user else user["email"]
            jobs = self.store.list_jobs(user_id=user_id)
            self._send_json({"jobs": jobs})
            return

        # GET /api/jobs/{id}/logs
        if path.startswith("/api/jobs/") and path.endswith("/logs"):
            parts = path.split("/")
            job_id = parts[3]
            if not self._get_authorized_job(job_id, self._require_authenticated_user()):
                return
            log_data = self.service.get_logs(job_id)
            if not log_data:
                log_file = STORAGE_ROOT / job_id / "logs" / "job.log"
                if log_file.exists():
                    log_data = {"job_id": job_id, "logs": log_file.read_text(encoding="utf-8", errors="replace")}
                else:
                    self._send_json({"error": f"Job {job_id} não encontrado ou sem logs"}, HTTPStatus.NOT_FOUND)
                    return
            self._send_json(log_data)
            return

        # GET /api/jobs/{id}/output
        if path.startswith("/api/jobs/") and path.endswith("/output"):
            parts = path.split("/")
            job_id = parts[3]
            if not self._get_authorized_job(job_id, self._require_authenticated_user()):
                return
            output_dir = STORAGE_ROOT / job_id / "output"
            if not output_dir.exists():
                self._send_json({"job_id": job_id, "files": []})
                return
            files = [str(p.relative_to(output_dir)) for p in sorted(output_dir.rglob("*")) if p.is_file()]
            self._send_json({"job_id": job_id, "output_dir": str(output_dir), "files": files})
            return

        # GET /api/jobs/{id}/output/{filename}
        if path.startswith("/api/jobs/") and "/output/" in path:
            parts = path.split("/output/")
            prefix_parts = parts[0].split("/")
            job_id = prefix_parts[3]
            if not self._get_authorized_job(job_id, self._require_authenticated_user()):
                return
            filename = parts[1]
            file_path = (STORAGE_ROOT / job_id / "output" / filename).resolve()
            if not str(file_path).startswith(str((STORAGE_ROOT / job_id / "output").resolve())):
                self._send_json({"error": "Acesso não autorizado"}, HTTPStatus.FORBIDDEN)
                return
            self._send_file(file_path)
            return

        # GET /api/jobs/{id}/status
        if path.startswith("/api/jobs/") and path.endswith("/status"):
            parts = path.split("/")
            job_id = parts[3]
            if not self._get_authorized_job(job_id, self._require_authenticated_user()):
                return
            status_data = self.service.get_status(job_id)
            if not status_data:
                self._send_json({"error": f"Job {job_id} não encontrado"}, HTTPStatus.NOT_FOUND)
                return
            self._send_json(status_data)
            return

        # GET /api/jobs/{id}
        if path.startswith("/api/jobs/"):
            parts = path.split("/")
            if len(parts) == 4:
                job_id = parts[3]
                job = self._get_authorized_job(job_id, self._require_authenticated_user())
                if not job:
                    return
                self._send_json(job)
                return

        self._send_json({"error": f"Rota desconhecida: {path}"}, HTTPStatus.NOT_FOUND)

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/")

        # === PILAR 1: Rotas de Autenticação Passwordless (@academico.ufpb.br) ===
        if path == "/api/auth/request-otp":
            content_length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(content_length)
            try:
                data = json.loads(body.decode("utf-8"))
                email = data.get("email", "").strip().lower()
                valid, msg = validate_email_domain(email)
                if not valid:
                    self._send_json({"error": msg}, HTTPStatus.BAD_REQUEST)
                    return

                otp_code, expires_at = self.store.request_otp(
                    email,
                    OTP_EXPIRATION_SECONDS,
                    OTP_REQUEST_INTERVAL_SECONDS,
                )
                logger.info("[AUTH] OTP emitido para %s (expira em %s)", email, expires_at)

                resp_data = {
                    "message": f"Código de acesso enviado para {email}.",
                    "email": email,
                    "expires_at": expires_at,
                }
                if DEV_AUTH_MOCK:
                    resp_data["dev_otp"] = otp_code

                self._send_json(resp_data, HTTPStatus.OK)
            except OtpRateLimitError as e:
                self._send_json({"error": str(e)}, HTTPStatus.TOO_MANY_REQUESTS)
            except Exception as e:
                self._send_json({"error": f"Payload inválido: {e}"}, HTTPStatus.BAD_REQUEST)
            return

        if path == "/api/auth/verify-otp":
            content_length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(content_length)
            try:
                data = json.loads(body.decode("utf-8"))
                email = data.get("email", "").strip().lower()
                otp = data.get("otp", "").strip()

                token = self.store.verify_otp(email, otp, max_attempts=OTP_MAX_ATTEMPTS)
                if not token:
                    self._send_json({"error": "Código OTP inválido ou expirado."}, HTTPStatus.UNAUTHORIZED)
                    return

                self._send_json({
                    "message": "Autenticado com sucesso",
                    "token": token,
                    "email": email,
                }, HTTPStatus.OK)
            except Exception as e:
                self._send_json({"error": f"Payload inválido: {e}"}, HTTPStatus.BAD_REQUEST)
            return

        if path == "/api/auth/logout":
            user = self._get_authenticated_user()
            if user:
                auth_header = self.headers.get("Authorization", "")
                token = auth_header[7:].strip() if auth_header.startswith("Bearer ") else ""
                self.store.revoke_token(token)
            self._send_json({"message": "Sessão encerrada com sucesso."})
            return

        # POST /api/jobs/run-next
        if path == "/api/jobs/run-next":
            if not self._require_authenticated_user():
                return
            job = self.service.run_next_job()
            if not job:
                self._send_json({"message": "Nenhum job pendente na fila"}, HTTPStatus.OK)
                return
            self._send_json({"message": "Job executado com sucesso", "job": job})
            return

        # POST /api/jobs/{id}/cancel (Etapa C: Cancelamento forçado)
        if path.startswith("/api/jobs/") and path.endswith("/cancel"):
            parts = path.split("/")
            job_id = parts[3]
            user = self._require_authenticated_user()
            if not user:
                return
            user_id = user["email"]
            success, msg = self.service.cancel_job(job_id, user_id=user_id)
            if success:
                self._send_json({"message": msg})
            else:
                status_code = HTTPStatus.FORBIDDEN if "Permissão" in msg else HTTPStatus.BAD_REQUEST
                self._send_json({"error": msg}, status_code)
            return

        # POST /api/jobs/upload (Multipart seguro sem cgi)
        if path == "/api/jobs/upload":
            content_type = self.headers.get("Content-Type", "")
            if not content_type.startswith("multipart/form-data"):
                self._send_json({"error": "Content-Type deve ser multipart/form-data"}, HTTPStatus.BAD_REQUEST)
                return

            job_root: Path | None = None
            try:
                content_length = int(self.headers.get("Content-Length", 0))
                if content_length <= 0 or content_length > MAX_UPLOAD_REQUEST_BYTES:
                    self._send_json({"error": "Upload excede o tamanho máximo permitido."}, HTTPStatus.REQUEST_ENTITY_TOO_LARGE)
                    return
                body = self.rfile.read(content_length)

                form = parse_multipart(content_type, body)

                file_item = form.getfile("file")
                if not file_item:
                    self._send_json({"error": "Campo 'file' (ZIP) é obrigatório"}, HTTPStatus.BAD_REQUEST)
                    return

                filename = file_item["filename"] or "upload.zip"
                if not filename.lower().endswith(".zip"):
                    self._send_json({"error": "Apenas arquivos com extensão .zip são aceitos"}, HTTPStatus.BAD_REQUEST)
                    return

                zip_bytes = file_item["content"]
                ZipSecurityValidator.validate_file_size(len(zip_bytes))

                # === PILAR 1: Autenticação obrigatória ===
                user = self._get_authenticated_user(form.getvalue("token"))
                if not user:
                    self._send_json(
                        {"error": "Autenticação obrigatória. Faça login com seu e-mail institucional (@academico.ufpb.br)."},
                        HTTPStatus.UNAUTHORIZED,
                    )
                    return

                user_id = user["email"]
                entrypoint = form.getvalue("entrypoint", "main.py")
                entrypoint_path = Path(entrypoint)
                if (
                    not entrypoint
                    or entrypoint_path.is_absolute()
                    or ".." in entrypoint_path.parts
                    or entrypoint_path.suffix.lower() != ".py"
                ):
                    self._send_json({"error": "Entrypoint deve ser um caminho relativo para um arquivo .py."}, HTTPStatus.BAD_REQUEST)
                    return

                # === PILAR 2: Validação de imagem via allowlist ===
                image_id = form.getvalue("image_id", "")
                if not image_id:
                    raw_image = form.getvalue("image", "")
                    if raw_image:
                        self._send_json(
                            {"error": "O campo 'image' direto não é mais aceito. Use 'image_id' para selecionar do catálogo aprovado."},
                            HTTPStatus.BAD_REQUEST,
                        )
                        return
                    self._send_json(
                        {"error": "O campo 'image_id' é obrigatório. Selecione um ambiente do catálogo."},
                        HTTPStatus.BAD_REQUEST,
                    )
                    return

                image_ok, image_result = validate_image_id(image_id)
                if not image_ok:
                    self._send_json({"error": image_result}, HTTPStatus.BAD_REQUEST)
                    return
                image = image_result

                # === PILAR 3: Validação de timeout (time-boxing) ===
                raw_timeout = form.getvalue("timeout_seconds", None)
                requested_timeout = int(raw_timeout) if raw_timeout else None
                applied_timeout, timeout_msg = validate_timeout(requested_timeout)

                # === PILAR 3: Validação de cota (anti-starvation) ===
                active_count = self.store.count_active_jobs_by_user(user_id)
                quota_ok, quota_msg = validate_user_quota(active_count)
                if not quota_ok:
                    self._send_json({"error": quota_msg}, HTTPStatus.TOO_MANY_REQUESTS)
                    return

                job_id = f"job_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"
                job_root = STORAGE_ROOT / job_id
                layout = build_job_layout(job_root)

                extracted_files = ZipSecurityValidator.safe_extract(zip_bytes, layout["workspace"])
                command = ["python", entrypoint]

                created = self.service.create_job(
                    job_id=job_id,
                    user_id=user_id,
                    image=image,
                    command=command,
                    job_root=str(job_root),
                    original_filename=filename,
                    timeout_seconds=applied_timeout,
                )

                if self.store:
                    self.store.update_status(
                        job_id,
                        status="queued",
                        timeout_seconds=applied_timeout,
                        cpu_limit=SERVER_CPUS,
                        memory_limit=SERVER_MEMORY,
                        gpu_limit=SERVER_GPU_COUNT,
                    )

                self._send_json(
                    {
                        "message": "Job criado e colocado na fila com sucesso",
                        "job_id": job_id,
                        "status": "queued",
                        "files_extracted": len(extracted_files),
                        "image_id": image_id,
                        "image_tag": image,
                        "applied_timeout": applied_timeout,
                        "timeout_msg": timeout_msg,
                        "job": created,
                    },
                    HTTPStatus.CREATED,
                )
            except ZipValidationError as e:
                if job_root and job_root.exists():
                    shutil.rmtree(job_root, ignore_errors=True)
                self._send_json({"error": f"Validação do arquivo rejeitada: {e}"}, HTTPStatus.BAD_REQUEST)
            except Exception as e:
                if job_root and job_root.exists():
                    shutil.rmtree(job_root, ignore_errors=True)
                logger.exception("Erro ao processar upload do job: %s", e)
                self._send_json({"error": f"Erro interno ao processar upload: {e}"}, HTTPStatus.INTERNAL_SERVER_ERROR)
            return

        # POST /api/jobs (JSON direto para testes/integração)
        if path == "/api/jobs":
            content_length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(content_length)
            try:
                data = json.loads(body.decode("utf-8"))
                job_id = data.get("job_id") or f"job_{uuid.uuid4().hex[:8]}"

                user = self._require_authenticated_user()
                if not user:
                    return
                user_id = user["email"]

                image_id = data.get("image_id", "")
                if image_id:
                    img_ok, img_result = validate_image_id(image_id)
                    if not img_ok:
                        self._send_json({"error": img_result}, HTTPStatus.BAD_REQUEST)
                        return
                    image = img_result
                else:
                    self._send_json({"error": "O campo 'image_id' é obrigatório."}, HTTPStatus.BAD_REQUEST)
                    return

                command = data.get("command", ["python", "-c", "print('ok')"])
                job_root = str(STORAGE_ROOT / job_id)

                raw_timeout = data.get("timeout_seconds")
                applied_timeout, timeout_msg = validate_timeout(raw_timeout)

                build_job_layout(job_root)
                job = self.service.create_job(
                    job_id=job_id,
                    user_id=user_id,
                    image=image,
                    command=command,
                    job_root=job_root,
                    timeout_seconds=applied_timeout,
                )
                self._send_json(job, HTTPStatus.CREATED)
            except Exception as e:
                self._send_json({"error": f"Payload inválido: {e}"}, HTTPStatus.BAD_REQUEST)
            return

        self._send_json({"error": f"Rota desconhecida: {path}"}, HTTPStatus.NOT_FOUND)

    def do_DELETE(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/")
        if path.startswith("/api/jobs/"):
            parts = path.split("/")
            if len(parts) == 4:
                job_id = parts[3]
                user = self._require_authenticated_user()
                if not user:
                    return
                user_id = user["email"]
                success = self.service.delete_job(job_id, user_id=user_id)
                if success:
                    self._send_json({"message": f"Job {job_id} removido com sucesso"})
                else:
                    self._send_json({"error": f"Job {job_id} não encontrado ou permissão negada"}, HTTPStatus.NOT_FOUND)
                return

        self._send_json({"error": f"Rota desconhecida: {path}"}, HTTPStatus.NOT_FOUND)


class QueueWorker:
    """Worker em background que processa jobs da fila automaticamente em ordem FIFO."""

    def __init__(self, service: JobApiService, interval: float = 1.0):
        self.service = service
        self.interval = interval
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run, daemon=True, name="QueueWorkerThread")
        self._thread.start()
        logger.info("Worker automático ativado: jobs pendentes na fila serão executados automaticamente em ordem FIFO.")

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=3.0)

    def _run(self) -> None:
        while not self._stop_event.is_set():
            try:
                job = self.service.run_next_job()
                if job:
                    logger.info("Job executado automaticamente pelo worker: %s -> Status: %s (Exit Code: %s)",
                                job["job_id"], job["status"], job.get("exit_code"))
                else:
                    self._stop_event.wait(self.interval)
            except Exception as e:
                logger.exception("Erro no processamento automático da fila: %s", e)
                self._stop_event.wait(self.interval)


class RetentionWorker:
    """Executa a política de retenção sem depender de uma tarefa manual."""

    def __init__(self, interval: float = 3600.0):
        self.interval = interval
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run, daemon=True, name="RetentionWorkerThread")
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=3.0)

    def _run(self) -> None:
        while not self._stop_event.is_set():
            try:
                cleanup_expired_jobs()
            except Exception:
                logger.exception("Erro na limpeza automática de jobs expirados")
            self._stop_event.wait(self.interval)


def run_server(host: str = "0.0.0.0", port: int = 8000, auto_worker: bool = True) -> None:
    server_address = (host, port)
    httpd = HTTPServer(server_address, ApiServerHandler)
    logger.info("AI Compute Server rodando em http://%s:%d", host, port)

    # Etapa B: Recuperação de jobs ao inicializar o servidor
    recovered = ApiServerHandler.service.recover_state_on_startup()
    logger.info(
        "Recuperação de boot: %d jobs em execução analisados, %d jobs pendentes enfileirados.",
        recovered.get("recovered_running", 0),
        recovered.get("recovered_queued", 0),
    )

    worker: QueueWorker | None = None
    retention_worker: RetentionWorker | None = None
    if auto_worker:
        worker = QueueWorker(ApiServerHandler.service)
        worker.start()
        retention_worker = RetentionWorker()
        retention_worker.start()

    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        logger.info("Encerrando servidor...")
        if worker:
            worker.stop()
        if retention_worker:
            retention_worker.stop()
        httpd.server_close()


if __name__ == "__main__":
    host = os.environ.get("HOST", "0.0.0.0")
    port = int(os.environ.get("PORT", "8000"))
    run_server(host=host, port=port)

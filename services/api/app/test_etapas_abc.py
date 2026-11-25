"""Testes automatizados das Etapas A (Auth Passwordless), B (Resiliência de Boot) e C (Cancelamento)."""

import io
import json
import socket
import sys
import tempfile
import threading
import time
import unittest
import uuid
import urllib.request
import zipfile
from http.server import HTTPServer
from pathlib import Path
from urllib.error import HTTPError
from unittest.mock import patch, MagicMock

APP_DIR = Path(__file__).resolve().parent
REPO_ROOT = APP_DIR.parents[2]
CONFIG_DIR = REPO_ROOT / "config"
QUEUE_DIR = REPO_ROOT / "services" / "job-manager" / "queue"
SCHEDULER_DIR = REPO_ROOT / "services" / "job-manager" / "scheduler"
EXECUTOR_DIR = REPO_ROOT / "services" / "job-manager" / "executor"

for p in [str(APP_DIR), str(CONFIG_DIR), str(QUEUE_DIR), str(SCHEDULER_DIR), str(EXECUTOR_DIR)]:
    if p not in sys.path:
        sys.path.insert(0, p)

from job_api import JobApiService
from job_store import JobStore
from queue_manager import JobQueue, JobRecord, JobStatus
from server import ApiServerHandler
from server_config import validate_email_domain


def get_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("", 0))
        return s.getsockname()[1]


def make_test_zip() -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("main.py", "print('hello abc')\n")
    return buf.getvalue()


class EtapaATests(unittest.TestCase):
    """Testes do Pilar 1 / Etapa A: Autenticação Passwordless institucional."""

    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmp_dir.name) / "test_auth.db"
        self.store = JobStore(self.db_path)

    def tearDown(self):
        self.tmp_dir.cleanup()

    def test_domain_validation_ufpb(self):
        """Apenas @academico.ufpb.br deve ser aceito."""
        ok, _ = validate_email_domain("aluno@academico.ufpb.br")
        self.assertTrue(ok)

        bad_emails = [
            "aluno@gmail.com",
            "aluno@hotmail.com",
            "professor@ufpb.br",
            "hacker@academico.ufpb.br.fake.com",
            "",
            "sem_arroba",
        ]
        for bad in bad_emails:
            ok, msg = validate_email_domain(bad)
            self.assertFalse(ok, f"Email {bad} não deveria ser aceito")

    def test_otp_lifecycle(self):
        """Fluxo completo de requisição e validação de OTP."""
        email = "maria@academico.ufpb.br"
        otp_code, expires_at = self.store.request_otp(email)
        self.assertEqual(len(otp_code), 6)
        self.assertTrue(otp_code.isdigit())

        # OTP incorreto falha
        bad_token = self.store.verify_otp(email, "000000")
        self.assertIsNone(bad_token)

        # OTP correto retorna token de sessão
        token = self.store.verify_otp(email, otp_code)
        self.assertIsNotNone(token)
        self.assertIsInstance(token, str)

        # O mesmo OTP não pode ser reutilizado
        second_use = self.store.verify_otp(email, otp_code)
        self.assertIsNone(second_use)

        # Token é consultável e traz dados do usuário
        user = self.store.get_user_by_token(token)
        self.assertIsNotNone(user)
        self.assertEqual(user["email"], email)
        self.assertEqual(user["role"], "student")

        # Revogação de token
        self.assertTrue(self.store.revoke_token(token))
        self.assertIsNone(self.store.get_user_by_token(token))


class EtapaBTests(unittest.TestCase):
    """Testes da Etapa B: Resiliência de fila e recuperação no boot."""

    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmp_dir.name) / "test_boot.db"
        self.store = JobStore(self.db_path)

    def tearDown(self):
        self.tmp_dir.cleanup()

    def test_recover_queued_jobs_on_startup(self):
        """Jobs queued no banco devem ser recolocados na fila em memória ao iniciar."""
        # 1. Simula jobs que ficaram na fila antes de uma parada
        self.store.create_job("job_q1", "user_1@academico.ufpb.br", status="queued", command="python main.py")
        self.store.create_job("job_q2", "user_2@academico.ufpb.br", status="queued", command="python train.py")

        # 2. Inicia um novo serviço do zero com a fila em memória vazia
        queue = JobQueue()
        self.assertEqual(len(queue.list_jobs()), 0)

        # 3. Inicializa JobApiService com auto_recover=True
        service = JobApiService(queue=queue, store=self.store, auto_recover=True)

        # 4. A fila em memória deve ter recuperado os 2 jobs na ordem correta
        jobs_in_mem = queue.list_jobs()
        self.assertEqual(len(jobs_in_mem), 2)
        self.assertEqual(jobs_in_mem[0].job_id, "job_q1")
        self.assertEqual(jobs_in_mem[1].job_id, "job_q2")

    @patch("job_api.inspect_job_container")
    def test_recover_running_job_that_finished_offline(self, mock_inspect):
        """Se o container finalizou enquanto o servidor estava fora, status deve atualizar."""
        mock_inspect.return_value = {"Running": False, "ExitCode": 0}

        self.store.create_job("job_was_running", "user@academico.ufpb.br", status="running")
        self.assertEqual(self.store.get_job("job_was_running")["status"], "running")

        service = JobApiService(queue=JobQueue(), store=self.store, auto_recover=True)

        job = self.store.get_job("job_was_running")
        self.assertEqual(job["status"], "completed")
        self.assertEqual(job["exit_code"], 0)


class EtapaCTests(unittest.TestCase):
    """Testes da Etapa C: Cancelamento forçado de job com docker kill."""

    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmp_dir.name) / "test_cancel.db"
        self.store = JobStore(self.db_path)
        self.queue = JobQueue()
        self.service = JobApiService(queue=self.queue, store=self.store, auto_recover=False)

    def tearDown(self):
        self.tmp_dir.cleanup()

    @patch("job_api.kill_job_container")
    def test_cancel_running_job(self, mock_kill):
        mock_kill.return_value = True

        self.service.create_job("job_to_cancel", "user_a@academico.ufpb.br", "python:3.12-slim", ["python", "loop.py"])
        self.queue.update_status("job_to_cancel", JobStatus.RUNNING)
        self.store.update_status("job_to_cancel", "running")

        ok, msg = self.service.cancel_job("job_to_cancel", user_id="user_a@academico.ufpb.br")
        self.assertTrue(ok)
        self.assertIn("cancelado", msg)
        mock_kill.assert_called_with("job_to_cancel")

        # Status deve ser cancelled
        stored = self.store.get_job("job_to_cancel")
        self.assertEqual(stored["status"], "cancelled")

    def test_cancel_permission_denied_for_other_user(self):
        """Usuário B não pode cancelar job de Usuário A."""
        self.service.create_job("job_user_a", "user_a@academico.ufpb.br", "python:3.12-slim", ["python", "main.py"])

        ok, msg = self.service.cancel_job("job_user_a", user_id="user_b@academico.ufpb.br")
        self.assertFalse(ok)
        self.assertIn("Permissão negada", msg)


class HttpApiIntegrationTests(unittest.TestCase):
    """Testes de ponta a ponta na API HTTP cobrindo login OTP e cancelamento."""

    @classmethod
    def setUpClass(cls):
        cls.port = get_free_port()
        cls.server = HTTPServer(("127.0.0.1", cls.port), ApiServerHandler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.base_url = f"http://127.0.0.1:{cls.port}"
        time.sleep(0.1)

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def test_http_auth_otp_flow(self):
        # 1. Solicita OTP com e-mail inválido -> 400
        req_bad = urllib.request.Request(
            f"{self.base_url}/api/auth/request-otp",
            data=json.dumps({"email": "aluno@gmail.com"}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with self.assertRaises(HTTPError) as ctx:
            urllib.request.urlopen(req_bad)
        self.assertEqual(ctx.exception.code, 400)

        # 2. Solicita OTP com e-mail institucional válido -> 200
        email = f"aluno_ci_{uuid.uuid4().hex[:8]}@academico.ufpb.br"
        req_ok = urllib.request.Request(
            f"{self.base_url}/api/auth/request-otp",
            data=json.dumps({"email": email}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req_ok) as resp:
            self.assertEqual(resp.status, 200)
            data = json.loads(resp.read().decode("utf-8"))
            with ApiServerHandler.store._connect() as conn:
                otp = conn.execute(
                    "SELECT otp_code FROM auth_tokens WHERE email = ? ORDER BY id DESC LIMIT 1",
                    (email,),
                ).fetchone()["otp_code"]

        # 3. Valida OTP -> 200 com token
        req_verify = urllib.request.Request(
            f"{self.base_url}/api/auth/verify-otp",
            data=json.dumps({"email": email, "otp": otp}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req_verify) as resp_v:
            self.assertEqual(resp_v.status, 200)
            token_data = json.loads(resp_v.read().decode("utf-8"))
            token = token_data["token"]
            self.assertIsNotNone(token)

        # 4. Consulta usuário logado (/api/auth/me) com Bearer token
        req_me = urllib.request.Request(
            f"{self.base_url}/api/auth/me",
            headers={"Authorization": f"Bearer {token}"},
        )
        with urllib.request.urlopen(req_me) as resp_me:
            self.assertEqual(resp_me.status, 200)
            me_data = json.loads(resp_me.read().decode("utf-8"))
            self.assertEqual(me_data["user"]["email"], email)


if __name__ == "__main__":
    unittest.main()

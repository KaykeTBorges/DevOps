"""Testes de integração do servidor HTTP — inclui validações dos Pilares 2 e 3."""

import io
import json
import socket
import sys
import tempfile
import threading
import time
import unittest
import urllib.request
import zipfile
import uuid
from http.server import HTTPServer
from pathlib import Path
from urllib.error import HTTPError

APP_DIR = Path(__file__).resolve().parent
REPO_ROOT = APP_DIR.parents[2]
sys.path.insert(0, str(APP_DIR))

from server import ApiServerHandler


def get_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("", 0))
        return s.getsockname()[1]


def build_multipart(fields: dict, file_name: str, file_bytes: bytes, boundary: str) -> bytes:
    """Helper para montar multipart/form-data com campos e um arquivo."""
    parts = []
    for name, value in fields.items():
        parts.append(
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="{name}"\r\n\r\n'
            f"{value}\r\n"
        )
    # Arquivo
    parts_bytes = "".join(parts).encode("utf-8")
    file_header = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="file"; filename="{file_name}"\r\n'
        f"Content-Type: application/zip\r\n\r\n"
    ).encode("utf-8")
    file_footer = f"\r\n--{boundary}--\r\n".encode("utf-8")
    return parts_bytes + file_header + file_bytes + file_footer


def make_valid_zip() -> bytes:
    """Cria um ZIP válido com main.py."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("main.py", "print('hello from uploaded model')\n")
    return buf.getvalue()


class ApiServerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.port = get_free_port()
        cls.server = HTTPServer(("127.0.0.1", cls.port), ApiServerHandler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.base_url = f"http://127.0.0.1:{cls.port}"
        email = f"server_test_{uuid.uuid4().hex[:8]}@academico.ufpb.br"
        otp, _ = ApiServerHandler.store.request_otp(email, request_interval_seconds=0)
        cls.auth_token = ApiServerHandler.store.verify_otp(email, otp)
        cls._real_urlopen = urllib.request.urlopen

        def authenticated_urlopen(request, *args, **kwargs):
            if isinstance(request, str):
                request = urllib.request.Request(request)
            if request.headers.get("Authorization"):
                return cls._real_urlopen(request, *args, **kwargs)
            headers = dict(request.headers)
            headers["Authorization"] = f"Bearer {cls.auth_token}"
            authenticated = urllib.request.Request(
                request.full_url,
                data=request.data,
                headers=headers,
                method=request.get_method(),
            )
            return cls._real_urlopen(authenticated, *args, **kwargs)

        urllib.request.urlopen = authenticated_urlopen
        time.sleep(0.1)

    @classmethod
    def tearDownClass(cls):
        urllib.request.urlopen = cls._real_urlopen
        cls.server.shutdown()
        cls.server.server_close()

    # ----------------------------------------------------------------
    # Testes básicos existentes
    # ----------------------------------------------------------------

    def test_get_frontend_index(self):
        req = urllib.request.Request(f"{self.base_url}/")
        with urllib.request.urlopen(req) as resp:
            self.assertEqual(resp.status, 200)
            content = resp.read().decode("utf-8")
            self.assertIn("AI Compute Server", content)

    def test_get_jobs_list(self):
        req = urllib.request.Request(f"{self.base_url}/api/jobs")
        with urllib.request.urlopen(req) as resp:
            self.assertEqual(resp.status, 200)
            data = json.loads(resp.read().decode("utf-8"))
            self.assertIn("jobs", data)

    def test_create_and_delete_job_json(self):
        payload = json.dumps({
            "job_id": "test_server_job_001",
            "image_id": "python312",
            "command": ["python", "-c", "print('server test')"],
        }).encode("utf-8")

        req = urllib.request.Request(
            f"{self.base_url}/api/jobs",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req) as resp:
            self.assertEqual(resp.status, 201)
            data = json.loads(resp.read().decode("utf-8"))
            self.assertEqual(data["job_id"], "test_server_job_001")

        # Verifica consulta do job
        req_get = urllib.request.Request(f"{self.base_url}/api/jobs/test_server_job_001")
        with urllib.request.urlopen(req_get) as resp_get:
            self.assertEqual(resp_get.status, 200)

        # Deleta job
        req_del = urllib.request.Request(f"{self.base_url}/api/jobs/test_server_job_001", method="DELETE")
        with urllib.request.urlopen(req_del) as resp_del:
            self.assertEqual(resp_del.status, 200)

    def test_user_isolation_filtering_via_api(self):
        # Cria jobs pertencentes ao usuário autenticado.
        for uid, jid in [("alice", "test_iso_alice_01"), ("bob", "test_iso_bob_01")]:
            payload = json.dumps({
                "job_id": jid,
                "image_id": "python312",
                "command": ["python", "-c", f"print('{uid}')"],
            }).encode("utf-8")
            req = urllib.request.Request(
                f"{self.base_url}/api/jobs", data=payload,
                headers={"Content-Type": "application/json"}, method="POST",
            )
            urllib.request.urlopen(req)

        # Usuário comum só recebe seus próprios jobs, mesmo solicitando outro filtro.
        with urllib.request.urlopen(f"{self.base_url}/api/jobs?user_id=alice") as resp:
            jobs = json.loads(resp.read().decode("utf-8"))["jobs"]
            job_ids = [job["job_id"] for job in jobs]
            self.assertIn("test_iso_alice_01", job_ids)
            self.assertIn("test_iso_bob_01", job_ids)

        # Limpeza
        for jid in ["test_iso_alice_01", "test_iso_bob_01"]:
            urllib.request.urlopen(urllib.request.Request(f"{self.base_url}/api/jobs/{jid}", method="DELETE"))

    # ----------------------------------------------------------------
    # PILAR 2: Testes do catálogo de imagens (Allowlist)
    # ----------------------------------------------------------------

    def test_get_catalog_images_returns_active_list(self):
        """GET /api/catalog/images deve retornar catálogo com imagens ativas."""
        req = urllib.request.Request(f"{self.base_url}/api/catalog/images")
        with urllib.request.urlopen(req) as resp:
            self.assertEqual(resp.status, 200)
            data = json.loads(resp.read().decode("utf-8"))
            self.assertIn("images", data)
            self.assertGreater(len(data["images"]), 0)
            # Deve ter admin_config
            self.assertIn("admin_config", data)
            self.assertIn("hard_cap_timeout", data["admin_config"])
            # Cada imagem deve ter os campos públicos
            for img in data["images"]:
                self.assertIn("id", img)
                self.assertIn("display_name", img)
                self.assertIn("description", img)
                # NÃO deve expor image_tag ao frontend
                self.assertNotIn("image_tag", img)

    def test_upload_with_valid_image_id_succeeds(self):
        """Upload com image_id válido do catálogo deve criar o job com sucesso."""
        zip_bytes = make_valid_zip()
        boundary = "----TestBoundaryPilar2Valid"
        body = build_multipart(
            {"user_id": "pilar2_user", "entrypoint": "main.py", "image_id": "python312", "timeout_seconds": "120"},
            "model.zip", zip_bytes, boundary,
        )

        req = urllib.request.Request(
            f"{self.base_url}/api/jobs/upload", data=body,
            headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
            method="POST",
        )
        with urllib.request.urlopen(req) as resp:
            self.assertEqual(resp.status, 201)
            data = json.loads(resp.read().decode("utf-8"))
            self.assertIn("job_id", data)
            self.assertEqual(data["status"], "queued")
            self.assertEqual(data["image_id"], "python312")
            self.assertEqual(data["image_tag"], "python:3.12-slim")
            self.assertGreater(data["files_extracted"], 0)
            # Limpa
            urllib.request.urlopen(urllib.request.Request(f"{self.base_url}/api/jobs/{data['job_id']}", method="DELETE"))

    def test_upload_with_invalid_image_id_rejected(self):
        """Upload com image_id que não existe no catálogo deve retornar 400."""
        zip_bytes = make_valid_zip()
        boundary = "----TestBoundaryPilar2Invalid"
        body = build_multipart(
            {"user_id": "hacker", "entrypoint": "main.py", "image_id": "ubuntu:22.04"},
            "model.zip", zip_bytes, boundary,
        )

        req = urllib.request.Request(
            f"{self.base_url}/api/jobs/upload", data=body,
            headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
            method="POST",
        )
        with self.assertRaises(HTTPError) as ctx:
            urllib.request.urlopen(req)
        self.assertEqual(ctx.exception.code, 400)
        error_data = json.loads(ctx.exception.read().decode("utf-8"))
        self.assertIn("não pertence ao catálogo", error_data["error"])

    def test_upload_with_arbitrary_image_field_rejected(self):
        """Upload usando campo 'image' direto (antigo) deve ser bloqueado."""
        zip_bytes = make_valid_zip()
        boundary = "----TestBoundaryOldImage"
        body = build_multipart(
            {"user_id": "hacker", "entrypoint": "main.py", "image": "malicious/backdoor:latest"},
            "evil.zip", zip_bytes, boundary,
        )

        req = urllib.request.Request(
            f"{self.base_url}/api/jobs/upload", data=body,
            headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
            method="POST",
        )
        with self.assertRaises(HTTPError) as ctx:
            urllib.request.urlopen(req)
        self.assertEqual(ctx.exception.code, 400)
        error_data = json.loads(ctx.exception.read().decode("utf-8"))
        self.assertIn("não é mais aceito", error_data["error"])

    def test_upload_without_image_id_rejected(self):
        """Upload sem image_id nem image deve retornar 400."""
        zip_bytes = make_valid_zip()
        boundary = "----TestBoundaryNoImage"
        body = build_multipart(
            {"user_id": "user1", "entrypoint": "main.py"},
            "model.zip", zip_bytes, boundary,
        )

        req = urllib.request.Request(
            f"{self.base_url}/api/jobs/upload", data=body,
            headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
            method="POST",
        )
        with self.assertRaises(HTTPError) as ctx:
            urllib.request.urlopen(req)
        self.assertEqual(ctx.exception.code, 400)
        error_data = json.loads(ctx.exception.read().decode("utf-8"))
        self.assertIn("image_id", error_data["error"])

    # ----------------------------------------------------------------
    # PILAR 3: Testes de Time-Boxing e Anti-Starvation
    # ----------------------------------------------------------------

    def test_upload_timeout_capped_to_hard_limit(self):
        """Timeout acima do hard cap deve ser ajustado (capped)."""
        zip_bytes = make_valid_zip()
        boundary = "----TestBoundaryTimeout"
        body = build_multipart(
            {"user_id": "timeout_user", "entrypoint": "main.py", "image_id": "python312",
             "timeout_seconds": "999999"},
            "model.zip", zip_bytes, boundary,
        )

        req = urllib.request.Request(
            f"{self.base_url}/api/jobs/upload", data=body,
            headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
            method="POST",
        )
        with urllib.request.urlopen(req) as resp:
            self.assertEqual(resp.status, 201)
            data = json.loads(resp.read().decode("utf-8"))
            # Timeout deve ter sido capado para 14400 (4h)
            self.assertEqual(data["applied_timeout"], 14400)
            self.assertIn("limite máximo", data["timeout_msg"])
            # Limpa
            urllib.request.urlopen(urllib.request.Request(f"{self.base_url}/api/jobs/{data['job_id']}", method="DELETE"))

    def test_upload_timeout_below_minimum_raised(self):
        """Timeout abaixo do mínimo deve ser ajustado para o mínimo."""
        zip_bytes = make_valid_zip()
        boundary = "----TestBoundaryTimeoutMin"
        body = build_multipart(
            {"user_id": "timeout_min_user", "entrypoint": "main.py", "image_id": "python312",
             "timeout_seconds": "5"},
            "model.zip", zip_bytes, boundary,
        )

        req = urllib.request.Request(
            f"{self.base_url}/api/jobs/upload", data=body,
            headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
            method="POST",
        )
        with urllib.request.urlopen(req) as resp:
            self.assertEqual(resp.status, 201)
            data = json.loads(resp.read().decode("utf-8"))
            self.assertEqual(data["applied_timeout"], 60)  # MIN_TIMEOUT
            self.assertIn("mínimo", data["timeout_msg"])
            # Limpa
            urllib.request.urlopen(urllib.request.Request(f"{self.base_url}/api/jobs/{data['job_id']}", method="DELETE"))

    def test_upload_quota_exceeded_returns_429(self):
        """Usuário com cota de fila excedida deve receber HTTP 429."""
        zip_bytes = make_valid_zip()
        boundary = "----TestBoundaryQuota"
        quota_user = "quota_test_user"

        created_ids = []
        # Cria MAX_QUEUED_JOBS_PER_USER jobs (padrão: 2)
        for i in range(2):
            body = build_multipart(
                {"user_id": quota_user, "entrypoint": "main.py", "image_id": "python312"},
                "model.zip", zip_bytes, boundary,
            )
            req = urllib.request.Request(
                f"{self.base_url}/api/jobs/upload", data=body,
                headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
                method="POST",
            )
            with urllib.request.urlopen(req) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                created_ids.append(data["job_id"])

        # Terceiro job deve ser bloqueado (429)
        body = build_multipart(
            {"user_id": quota_user, "entrypoint": "main.py", "image_id": "python312"},
            "model.zip", zip_bytes, boundary,
        )
        req = urllib.request.Request(
            f"{self.base_url}/api/jobs/upload", data=body,
            headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
            method="POST",
        )
        with self.assertRaises(HTTPError) as ctx:
            urllib.request.urlopen(req)
        self.assertEqual(ctx.exception.code, 429)
        error_data = json.loads(ctx.exception.read().decode("utf-8"))
        self.assertIn("Cota de fila excedida", error_data["error"])

        # Limpeza
        for jid in created_ids:
            urllib.request.urlopen(urllib.request.Request(f"{self.base_url}/api/jobs/{jid}", method="DELETE"))


if __name__ == "__main__":
    unittest.main()

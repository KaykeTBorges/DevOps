import json
import socket
import sys
import threading
import unittest
import urllib.request
import uuid
from http.server import HTTPServer
from pathlib import Path
from urllib.error import HTTPError

APP_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(APP_DIR))

from server import ApiServerHandler


def get_free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


class ApiSecurityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.port = get_free_port()
        cls.server = HTTPServer(("127.0.0.1", cls.port), ApiServerHandler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.base_url = f"http://127.0.0.1:{cls.port}"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def assert_unauthorized(self, request):
        with self.assertRaises(HTTPError) as context:
            urllib.request.urlopen(request)
        self.assertEqual(context.exception.code, 401)

    def test_jobs_list_requires_authentication(self):
        self.assert_unauthorized(urllib.request.Request(f"{self.base_url}/api/jobs"))

    def test_health_is_public_and_reports_status(self):
        with urllib.request.urlopen(f"{self.base_url}/api/health") as response:
            data = json.loads(response.read().decode())
        self.assertEqual(data["status"], "ok")
        self.assertIn("jobs", data)
        self.assertIn("system", data)

    def test_json_job_creation_requires_authentication(self):
        request = urllib.request.Request(
            f"{self.base_url}/api/jobs",
            data=json.dumps({"image_id": "python312", "command": ["python", "main.py"]}).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        self.assert_unauthorized(request)

    def test_metrics_require_authentication(self):
        self.assert_unauthorized(urllib.request.Request(f"{self.base_url}/api/metrics"))

    def test_authenticated_metrics_return_system_and_job_data(self):
        email = f"metrics_{uuid.uuid4().hex[:8]}@academico.ufpb.br"
        otp, _ = ApiServerHandler.store.request_otp(email, request_interval_seconds=0)
        token = ApiServerHandler.store.verify_otp(email, otp)
        request = urllib.request.Request(
            f"{self.base_url}/api/metrics",
            headers={"Authorization": f"Bearer {token}"},
        )
        with urllib.request.urlopen(request) as response:
            data = json.loads(response.read().decode())
        self.assertIn("jobs", data)
        self.assertIn("system", data)
        self.assertIn("disk", data["system"])


if __name__ == "__main__":
    unittest.main()

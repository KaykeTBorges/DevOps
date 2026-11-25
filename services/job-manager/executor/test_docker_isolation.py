import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

EXECUTOR = Path(__file__).resolve().parent / "job_executor.py"
DOCKER_IMAGE = "python:3.12-slim"


@unittest.skipUnless(shutil.which("docker"), "Docker não está disponível")
class DockerIsolationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        image_check = subprocess.run(
            ["docker", "image", "inspect", DOCKER_IMAGE],
            capture_output=True,
            check=False,
        )
        if image_check.returncode != 0:
            raise unittest.SkipTest(f"Imagem local ausente: {DOCKER_IMAGE}")

    def run_executor(self, job_id: str, code: str, timeout: int = 30):
        temp_dir = tempfile.TemporaryDirectory()
        job_root = Path(temp_dir.name) / job_id
        result = subprocess.run(
            [
                sys.executable,
                str(EXECUTOR),
                "--job-id", job_id,
                "--job-root", str(job_root),
                "--image", DOCKER_IMAGE,
                "--timeout-seconds", str(timeout),
                "--command", "python", "-c", code,
            ],
            capture_output=True,
            text=True,
            timeout=timeout + 20,
        )
        return temp_dir, job_root, result

    def test_writes_output_without_host_mounts(self):
        temp_dir, job_root, result = self.run_executor(
            "docker_output_test",
            "from pathlib import Path; assert not Path('/var/run/docker.sock').exists(); Path('/job/output/result.txt').write_text('ok')",
        )
        try:
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual((job_root / "output" / "result.txt").read_text(), "ok")
        finally:
            temp_dir.cleanup()

    def test_network_is_disabled(self):
        temp_dir, job_root, result = self.run_executor(
            "docker_network_test",
            "import socket; s=socket.socket(); s.settimeout(2);\ntry: s.connect(('1.1.1.1', 80)); raise SystemExit(1)\nexcept OSError: pass",
        )
        try:
            self.assertEqual(result.returncode, 0, result.stderr)
        finally:
            temp_dir.cleanup()

    def test_timeout_ends_execution(self):
        temp_dir, job_root, result = self.run_executor(
            "docker_timeout_test",
            "import time; time.sleep(10)",
            timeout=2,
        )
        try:
            self.assertEqual(result.returncode, 124, result.stderr)
            container = subprocess.run(
                ["docker", "ps", "-a", "--filter", "name=ai_job_docker_timeout_test", "-q"],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(container.stdout.strip(), "")
        finally:
            temp_dir.cleanup()


if __name__ == "__main__":
    unittest.main()

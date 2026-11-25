import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from job_executor import JobSpec, build_job_layout, build_docker_command


class JobExecutorTests(unittest.TestCase):
    def test_build_job_layout_creates_expected_directories(self):
        with tempfile.TemporaryDirectory() as tmp:
            job_dir = Path(tmp) / "job_001"
            build_job_layout(job_dir)

            expected = [
                job_dir / "input",
                job_dir / "workspace",
                job_dir / "output",
                job_dir / "logs",
                job_dir / "metadata",
            ]

            for path in expected:
                self.assertTrue(path.exists())
                self.assertTrue(path.is_dir())

    def test_build_docker_command_includes_isolation_flags(self):
        spec = JobSpec(
            job_id="job_001",
            image="python:3.12-slim",
            command=["python", "-c", "print('ok')"],
            cpu_limit="1.0",
            memory_limit="512m",
            timeout_seconds=60,
            network_mode="none",
            gpu_count=0,
        )

        docker_cmd = build_docker_command(spec, "/tmp/job_root")

        self.assertIn("--network", docker_cmd)
        self.assertIn("none", docker_cmd)
        self.assertIn("--cpus=1.0", docker_cmd)
        self.assertIn("--memory=512m", docker_cmd)
        self.assertIn("python:3.12-slim", docker_cmd)
        self.assertIn("OUTPUT_DIR=/job/output", docker_cmd)
        self.assertIn("WORKSPACE_DIR=/job/workspace", docker_cmd)
        self.assertIn("INPUT_DIR=/job/input", docker_cmd)
        self.assertIn("JOB_ID=job_001", docker_cmd)


if __name__ == "__main__":
    unittest.main()

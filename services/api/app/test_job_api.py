import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))

from job_api import JobApiService
from job_store import JobStore


class JobApiTests(unittest.TestCase):
    def test_create_and_list_jobs(self):
        service = JobApiService()
        with tempfile.TemporaryDirectory() as tmp:
            job = service.create_job(
                job_id="job_api_001",
                user_id="user_a",
                image="python:3.12-slim",
                command=["python", "-c", "print('api-job')"],
                job_root=str(Path(tmp) / "job_api_001"),
            )

            self.assertEqual(job["job_id"], "job_api_001")
            self.assertEqual(job["status"], "queued")
            self.assertEqual(len(service.list_jobs()), 1)

    @patch("scheduler.subprocess.run")
    def test_run_next_job_updates_status(self, mock_subprocess_run):
        mock_subprocess_run.return_value = subprocess.CompletedProcess(
            args=["python", "job_executor.py"],
            returncode=0,
            stdout="api runner ok",
            stderr="",
        )
        service = JobApiService()
        with tempfile.TemporaryDirectory() as tmp:
            service.create_job(
                job_id="job_api_002",
                user_id="user_b",
                image="python:3.12-slim",
                command=["python", "-c", "print('api runner ok')"],
                job_root=str(Path(tmp) / "job_api_002"),
            )

            result = service.run_next_job()
            self.assertIsNotNone(result)
            self.assertEqual(result["status"], "completed")
            self.assertEqual(result["exit_code"], 0)

    @patch("scheduler.subprocess.run")
    def test_integration_with_job_store(self, mock_subprocess_run):
        mock_subprocess_run.return_value = subprocess.CompletedProcess(
            args=["python", "job_executor.py"],
            returncode=0,
            stdout="store ok",
            stderr="",
        )
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "jobs.db"
            store = JobStore(db_path)
            service = JobApiService(store=store)

            job = service.create_job(
                job_id="job_stored_001",
                user_id="user_store",
                image="python:3.12-slim",
                command=["python", "-c", "print('stored')"],
                job_root=str(Path(tmp) / "job_root"),
                original_filename="model.zip",
            )
            self.assertEqual(job["status"], "queued")
            stored = store.get_job("job_stored_001")
            self.assertIsNotNone(stored)
            self.assertEqual(stored["status"], "queued")

            result = service.run_next_job()
            self.assertEqual(result["status"], "completed")

            stored_after = store.get_job("job_stored_001")
            self.assertEqual(stored_after["status"], "completed")
            self.assertEqual(stored_after["exit_code"], 0)

            # Test deletion also cleans store
            self.assertTrue(service.delete_job("job_stored_001"))
            self.assertIsNone(store.get_job("job_stored_001"))

    def test_list_jobs_user_filtering(self):
        service = JobApiService()
        service.create_job("job_u1", "user_1", "python:3.12-slim", ["python", "-c", "print('1')"])
        service.create_job("job_u2", "user_2", "python:3.12-slim", ["python", "-c", "print('2')"])
        service.create_job("job_u3", "user_1", "python:3.12-slim", ["python", "-c", "print('3')"])

        u1_jobs = service.list_jobs(user_id="user_1")
        u2_jobs = service.list_jobs(user_id="user_2")

        self.assertEqual(len(u1_jobs), 2)
        self.assertEqual({j["job_id"] for j in u1_jobs}, {"job_u1", "job_u3"})
        self.assertEqual(len(u2_jobs), 1)
        self.assertEqual(u2_jobs[0]["job_id"], "job_u2")


if __name__ == "__main__":
    unittest.main()

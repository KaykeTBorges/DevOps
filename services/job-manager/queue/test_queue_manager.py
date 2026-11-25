import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

queue_dir = Path(__file__).resolve().parent
scheduler_dir = queue_dir.parent / "scheduler"

sys.path.insert(0, str(queue_dir))
sys.path.insert(0, str(scheduler_dir))

from queue_manager import JobQueue, JobRecord, JobStatus
from scheduler import JobScheduler


class QueueManagerTests(unittest.TestCase):
    def test_enqueue_keeps_fifo_order(self):
        queue = JobQueue()
        first = queue.enqueue("job_001", "user_a", "python:3.12-slim", ["python", "-c", "print('1')"])
        second = queue.enqueue("job_002", "user_b", "python:3.12-slim", ["python", "-c", "print('2')"])

        self.assertEqual(queue.peek_next().job_id, first.job_id)
        self.assertEqual(queue.peek_next().job_id, first.job_id)
        self.assertEqual(queue.list_jobs()[0].job_id, first.job_id)
        self.assertEqual(queue.list_jobs()[1].job_id, second.job_id)

    @patch("scheduler.subprocess.run")
    def test_scheduler_executes_next_job(self, mock_subprocess_run):
        mock_subprocess_run.return_value = subprocess.CompletedProcess(
            args=["python", "job_executor.py"],
            returncode=0,
            stdout="hello from queue",
            stderr="",
        )
        queue = JobQueue()
        with tempfile.TemporaryDirectory() as tmp:
            queue.enqueue(
                "job_003",
                "user_c",
                "python:3.12-slim",
                ["python", "-c", "print('hello from queue')"],
                job_root=str(Path(tmp) / "job_003"),
                status=JobStatus.QUEUED,
            )
            queue.get_by_id("job_003").timeout_seconds = 42

            scheduler = JobScheduler(
                queue,
                executor_path=str(Path(__file__).resolve().parents[2] / "job-manager" / "executor" / "job_executor.py"),
            )
            job = scheduler.run_next()

            self.assertIsNotNone(job)
            self.assertEqual(job.status, JobStatus.COMPLETED)
            self.assertEqual(job.exit_code, 0)
            mock_subprocess_run.assert_called_once()
            self.assertIn("42", mock_subprocess_run.call_args.args[0])

    @patch("scheduler.subprocess.run")
    def test_scheduler_handles_timeout(self, mock_subprocess_run):
        mock_subprocess_run.return_value = subprocess.CompletedProcess(
            args=["python", "job_executor.py"],
            returncode=124,
            stdout="",
            stderr="Timeout exceeded",
        )
        queue = JobQueue()
        with tempfile.TemporaryDirectory() as tmp:
            queue.enqueue(
                "job_timeout",
                "user_d",
                "python:3.12-slim",
                ["sleep", "100"],
                job_root=str(Path(tmp) / "job_timeout"),
            )
            scheduler = JobScheduler(queue)
            job = scheduler.run_next()

            self.assertIsNotNone(job)
            self.assertEqual(job.status, JobStatus.TIMEOUT)
            self.assertEqual(job.exit_code, 124)


if __name__ == "__main__":
    unittest.main()

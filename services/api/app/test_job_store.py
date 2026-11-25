import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from job_store import JobStore


class JobStoreTests(unittest.TestCase):
    def test_create_and_list_jobs(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "jobs.db"
            store = JobStore(db_path)
            job = store.create_job(
                "job_store_001",
                "user_a",
                original_filename="demo.zip",
                status="queued",
                entrypoint="main.py",
                command="python",
                arguments="--epochs 10",
                image="python:3.12-slim",
                output_path="/tmp/job_store_001/output",
                cpu_limit="1.0",
                memory_limit="512m",
                gpu_limit=0,
                timeout_seconds=300,
            )

            self.assertEqual(job["job_id"], "job_store_001")
            self.assertEqual(len(store.list_jobs()), 1)
            self.assertEqual(store.get_job("job_store_001")["status"], "queued")
            self.assertGreater(job["expires_at"], job["created_at"])

    def test_update_status_and_delete(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "jobs.db"
            store = JobStore(db_path)
            store.create_job("job_store_002", "user_b")
            updated = store.update_status("job_store_002", "completed", exit_code=0, finished_at="2026-01-01T00:00:00Z")
            self.assertEqual(updated["status"], "completed")
            self.assertEqual(updated["exit_code"], 0)
            self.assertTrue(store.delete_job("job_store_002"))
            self.assertIsNone(store.get_job("job_store_002"))

    def test_claim_job_is_atomic(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = JobStore(Path(tmp) / "jobs.db")
            store.create_job("job_claim_001", "user_a", status="queued")

            self.assertTrue(store.claim_job("job_claim_001"))
            self.assertFalse(store.claim_job("job_claim_001"))
            self.assertEqual(store.get_job("job_claim_001")["status"], "running")

    def test_list_jobs_filtered_by_user_id(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "jobs.db"
            store = JobStore(db_path)
            store.create_job("job_alice_1", "alice")
            store.create_job("job_bob_1", "bob")
            store.create_job("job_alice_2", "alice")

            alice_jobs = store.list_jobs(user_id="alice")
            bob_jobs = store.list_jobs(user_id="bob")
            all_jobs = store.list_jobs()

            self.assertEqual(len(alice_jobs), 2)
            self.assertEqual({j["job_id"] for j in alice_jobs}, {"job_alice_1", "job_alice_2"})

            self.assertEqual(len(bob_jobs), 1)
            self.assertEqual(bob_jobs[0]["job_id"], "job_bob_1")

            self.assertEqual(len(all_jobs), 3)


if __name__ == "__main__":
    unittest.main()

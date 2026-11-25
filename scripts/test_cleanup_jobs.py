import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))
sys.path.insert(0, str(REPO_ROOT / "services" / "api" / "app"))

from cleanup_jobs import cleanup_expired_jobs
from job_store import JobStore


class CleanupJobsTests(unittest.TestCase):
    def test_cleanup_expired_jobs_removes_directory_and_updates_status(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            db_path = tmp_path / "jobs.db"
            storage_root = tmp_path / "storage" / "jobs"
            storage_root.mkdir(parents=True)

            store = JobStore(db_path)

            # Job 1: Expirado no passado (-1 dias)
            store.create_job(
                "job_old",
                "user_old",
                ttl_days=-1,
                status="completed",
            )
            old_job_dir = storage_root / "job_old"
            old_job_dir.mkdir()
            (old_job_dir / "output.txt").write_text("dummy output")

            # Job 2: Válido no futuro (+7 dias)
            store.create_job(
                "job_fresh",
                "user_fresh",
                ttl_days=7,
                status="completed",
            )
            fresh_job_dir = storage_root / "job_fresh"
            fresh_job_dir.mkdir()
            (fresh_job_dir / "output.txt").write_text("fresh output")

            # Executa limpeza
            cleaned = cleanup_expired_jobs(db_path=db_path, storage_root=storage_root, dry_run=False)

            self.assertIn("job_old", cleaned)
            self.assertNotIn("job_fresh", cleaned)

            # Verifica se diretório expirado foi apagado e o ativo preservado
            self.assertFalse(old_job_dir.exists())
            self.assertTrue(fresh_job_dir.exists())

            # Verifica se status virou 'expired'
            record = store.get_job("job_old")
            self.assertEqual(record["status"], "expired")


if __name__ == "__main__":
    unittest.main()

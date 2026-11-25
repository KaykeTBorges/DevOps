#!/usr/bin/env python3
"""Script de limpeza automática de arquivos de jobs expirados (TTL 7 dias).

Regras da política de retenção:
- Os dados do job permanecem armazenados por 7 dias;
- Após esse período, os arquivos temporários (input, workspace, output, logs)
  são removidos do storage para liberar espaço no disco;
- Opcionalmente, o registro no banco pode ser mantido como 'expired' ou expurgado.
"""

from __future__ import annotations

import argparse
import logging
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

# Adiciona services/api/app ao sys.path para importar JobStore
REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "services" / "api" / "app"))

from job_store import JobStore

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("cleanup-jobs")


def cleanup_expired_jobs(
    db_path: str | Path = REPO_ROOT / "db" / "jobs.db",
    storage_root: str | Path = REPO_ROOT / "storage" / "jobs",
    dry_run: bool = False,
    delete_db_record: bool = False,
) -> list[str]:
    store = JobStore(db_path)
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    expired_jobs = store.get_expired_jobs(reference_time=now)

    cleaned_ids: list[str] = []
    logger.info("Encontrados %d jobs expirados (referência: %s)", len(expired_jobs), now)

    for job in expired_jobs:
        job_id = job["job_id"]
        job_dir = Path(storage_root) / job_id

        logger.info("Processando job expirado: %s", job_id)

        if job_dir.exists():
            if dry_run:
                logger.info("[DRY-RUN] Seria removido diretório: %s", job_dir)
            else:
                shutil.rmtree(job_dir, ignore_errors=True)
                logger.info("Diretório removido: %s", job_dir)

        if not dry_run:
            if delete_db_record:
                store.delete_job(job_id)
                logger.info("Registro de %s excluído do banco", job_id)
            else:
                store.update_status(job_id, status="expired")
                logger.info("Status de %s atualizado para 'expired'", job_id)

        cleaned_ids.append(job_id)

    return cleaned_ids


def main():
    parser = argparse.ArgumentParser(description="Limpeza automática de arquivos de jobs expirados (TTL 7 dias).")
    parser.add_argument("--db-path", default=str(REPO_ROOT / "db" / "jobs.db"), help="Caminho para o banco SQLite")
    parser.add_argument("--storage-root", default=str(REPO_ROOT / "storage" / "jobs"), help="Caminho raiz de armazenamento de jobs")
    parser.add_argument("--dry-run", action="store_true", help="Apenas simula a limpeza sem apagar arquivos")
    parser.add_argument("--delete-db-record", action="store_true", help="Remove o registro do banco em vez de marcar como 'expired'")
    args = parser.parse_args()

    cleaned = cleanup_expired_jobs(
        db_path=args.db_path,
        storage_root=args.storage_root,
        dry_run=args.dry_run,
        delete_db_record=args.delete_db_record,
    )
    logger.info("Limpeza concluída. Total de jobs processados: %d", len(cleaned))


if __name__ == "__main__":
    main()

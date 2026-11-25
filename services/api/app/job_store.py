from __future__ import annotations

import json
import hashlib
import secrets
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


class OtpRateLimitError(ValueError):
    """Indica que o e-mail solicitou OTP fora da janela permitida."""


class JobStore:
    def __init__(self, db_path: str | Path = "db/jobs.db"):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS jobs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    job_id TEXT UNIQUE NOT NULL,
                    user_id TEXT NOT NULL,
                    original_filename TEXT,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    started_at TEXT,
                    finished_at TEXT,
                    expires_at TEXT,
                    entrypoint TEXT,
                    command TEXT,
                    arguments TEXT,
                    image TEXT,
                    container_id TEXT,
                    slurm_job_id TEXT,
                    exit_code INTEGER,
                    error_message TEXT,
                    output_path TEXT,
                    cpu_limit TEXT,
                    memory_limit TEXT,
                    gpu_limit INTEGER,
                    timeout_seconds INTEGER,
                    metadata_json TEXT
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    email TEXT UNIQUE NOT NULL,
                    role TEXT NOT NULL DEFAULT 'student',
                    created_at TEXT NOT NULL,
                    last_login_at TEXT
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS auth_tokens (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    email TEXT NOT NULL,
                    otp_code TEXT,
                    token TEXT UNIQUE,
                    token_hash TEXT,
                    otp_expires_at TEXT,
                    token_expires_at TEXT,
                    created_at TEXT NOT NULL,
                    used_at TEXT
                )
                """
            )
            columns = {row[1] for row in conn.execute("PRAGMA table_info(auth_tokens)").fetchall()}
            if "otp_attempts" not in columns:
                conn.execute("ALTER TABLE auth_tokens ADD COLUMN otp_attempts INTEGER NOT NULL DEFAULT 0")
            if "token_hash" not in columns:
                conn.execute("ALTER TABLE auth_tokens ADD COLUMN token_hash TEXT")
            legacy_tokens = conn.execute(
                "SELECT id, token FROM auth_tokens WHERE token IS NOT NULL AND token_hash IS NULL"
            ).fetchall()
            for legacy in legacy_tokens:
                token_hash = hashlib.sha256(legacy["token"].encode("utf-8")).hexdigest()
                conn.execute(
                    "UPDATE auth_tokens SET token_hash = ?, token = NULL WHERE id = ?",
                    (token_hash, legacy["id"]),
                )
            conn.commit()

    def _utc_now(self) -> str:
        return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    def _utc_future(self, days: int = 7) -> str:
        return (datetime.now(timezone.utc) + timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")

    def create_job(
        self,
        job_id: str,
        user_id: str,
        *,
        original_filename: str | None = None,
        status: str = "queued",
        entrypoint: str | None = None,
        command: str | None = None,
        arguments: str | None = None,
        image: str | None = None,
        output_path: str | None = None,
        cpu_limit: str | None = None,
        memory_limit: str | None = None,
        gpu_limit: int | None = None,
        timeout_seconds: int | None = None,
        metadata: dict[str, Any] | None = None,
        ttl_days: int = 7,
    ) -> dict[str, Any]:
        now = self._utc_now()
        expires_at = self._utc_future(ttl_days)
        payload = metadata or {}
        with self._connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO jobs (
                    job_id, user_id, original_filename, status, created_at, expires_at,
                    entrypoint, command, arguments, image, output_path,
                    cpu_limit, memory_limit, gpu_limit, timeout_seconds, metadata_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    job_id,
                    user_id,
                    original_filename,
                    status,
                    now,
                    expires_at,
                    entrypoint,
                    command,
                    arguments,
                    image,
                    output_path,
                    cpu_limit,
                    memory_limit,
                    gpu_limit,
                    timeout_seconds,
                    json.dumps(payload),
                ),
            )
            conn.commit()
            row = conn.execute("SELECT * FROM jobs WHERE id = ?", (cursor.lastrowid,)).fetchone()
            return dict(row)

    def get_job(self, job_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM jobs WHERE job_id = ?", (job_id,)).fetchone()
            if row is None:
                return None
            return dict(row)

    def list_jobs(self, user_id: str | None = None) -> list[dict[str, Any]]:
        with self._connect() as conn:
            if user_id:
                rows = conn.execute("SELECT * FROM jobs WHERE user_id = ? ORDER BY created_at ASC", (user_id,)).fetchall()
            else:
                rows = conn.execute("SELECT * FROM jobs ORDER BY created_at ASC").fetchall()
            return [dict(row) for row in rows]

    def get_expired_jobs(self, reference_time: str | None = None) -> list[dict[str, Any]]:
        ref = reference_time or self._utc_now()
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM jobs WHERE expires_at IS NOT NULL AND expires_at <= ?",
                (ref,),
            ).fetchall()
            return [dict(row) for row in rows]

    def update_status(self, job_id: str, status: str, **fields: Any) -> dict[str, Any] | None:
        if not fields and not status:
            return self.get_job(job_id)

        assignments = ["status = ?"]
        values: list[Any] = [status]

        for field_name in (
            "started_at", "finished_at", "exit_code", "error_message",
            "output_path", "expires_at",
            "timeout_seconds", "cpu_limit", "memory_limit", "gpu_limit",
        ):
            if field_name in fields:
                assignments.append(f"{field_name} = ?")
                values.append(fields[field_name])

        if "metadata_json" in fields:
            assignments.append("metadata_json = ?")
            values.append(json.dumps(fields["metadata_json"]))

        values.append(job_id)

        with self._connect() as conn:
            conn.execute(
                f"UPDATE jobs SET {', '.join(assignments)} WHERE job_id = ?",
                tuple(values),
            )
            conn.commit()

        return self.get_job(job_id)

    def count_active_jobs_by_user(self, user_id: str) -> int:
        """Conta jobs ativos (pending, queued, running) de um usuário para controle de cota."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT COUNT(*) as cnt FROM jobs WHERE user_id = ? AND status IN ('pending', 'queued', 'running')",
                (user_id,),
            ).fetchone()
            return row["cnt"] if row else 0

    def get_running_jobs(self) -> list[dict[str, Any]]:
        """Retorna todos os jobs atualmente com status 'running'."""
        with self._connect() as conn:
            rows = conn.execute("SELECT * FROM jobs WHERE status = 'running' ORDER BY started_at ASC").fetchall()
            return [dict(r) for r in rows]

    def get_queued_jobs(self) -> list[dict[str, Any]]:
        """Retorna todos os jobs pendentes/enfileirados em ordem de criação."""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM jobs WHERE status IN ('queued', 'pending') ORDER BY created_at ASC"
            ).fetchall()
            return [dict(r) for r in rows]

    def get_status_counts(self) -> dict[str, int]:
        with self._connect() as conn:
            rows = conn.execute("SELECT status, COUNT(*) AS total FROM jobs GROUP BY status").fetchall()
            return {row["status"]: row["total"] for row in rows}

    def claim_job(self, job_id: str) -> bool:
        """Reserva atomicamente um job queued/pending para um worker."""
        now = self._utc_now()
        with self._connect() as conn:
            cursor = conn.execute(
                """
                UPDATE jobs
                SET status = 'running', started_at = ?
                WHERE job_id = ? AND status IN ('queued', 'pending')
                """,
                (now, job_id),
            )
            conn.commit()
            return cursor.rowcount == 1

    # -----------------------------------------------------------------------
    # Pilar 1: Métodos de Autenticação Passwordless / OTP
    # -----------------------------------------------------------------------

    def request_otp(
        self,
        email: str,
        expiration_seconds: int = 900,
        request_interval_seconds: int = 60,
    ) -> tuple[str, str]:
        """Gera um código OTP de 6 dígitos para o e-mail informado e salva no banco.
        
        Retorna (otp_code, expires_at).
        """
        email = email.strip().lower()
        otp_code = f"{secrets.randbelow(900000) + 100000:06d}"
        now = self._utc_now()
        expires_at = (datetime.now(timezone.utc) + timedelta(seconds=expiration_seconds)).strftime("%Y-%m-%dT%H:%M:%SZ")
        earliest_allowed = (datetime.now(timezone.utc) - timedelta(seconds=request_interval_seconds)).strftime("%Y-%m-%dT%H:%M:%SZ")

        with self._connect() as conn:
            recent = conn.execute(
                "SELECT 1 FROM auth_tokens WHERE email = ? AND created_at >= ? ORDER BY id DESC LIMIT 1",
                (email, earliest_allowed),
            ).fetchone()
            if recent:
                raise OtpRateLimitError("Aguarde antes de solicitar um novo código OTP.")
            conn.execute(
                """
                INSERT INTO auth_tokens (email, otp_code, otp_expires_at, created_at, otp_attempts)
                VALUES (?, ?, ?, ?, 0)
                """,
                (email, otp_code, expires_at, now),
            )
            conn.commit()

        return otp_code, expires_at

    def verify_otp(self, email: str, otp_code: str, token_days: int = 7, max_attempts: int = 5) -> str | None:
        """Verifica o código OTP. Se válido, gera e retorna um token de sessão de 7 dias."""
        email = email.strip().lower()
        now = self._utc_now()

        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT id, otp_code, otp_attempts FROM auth_tokens
                WHERE email = ? AND used_at IS NULL AND otp_expires_at >= ?
                ORDER BY id DESC LIMIT 1
                """,
                (email, now),
            ).fetchone()

            if not row:
                return None

            if row["otp_attempts"] >= max_attempts:
                conn.execute("UPDATE auth_tokens SET used_at = ? WHERE id = ?", (now, row["id"]))
                conn.commit()
                return None

            if row["otp_code"] != otp_code:
                attempts = row["otp_attempts"] + 1
                conn.execute(
                    "UPDATE auth_tokens SET otp_attempts = ?, used_at = CASE WHEN ? >= ? THEN ? ELSE used_at END WHERE id = ?",
                    (attempts, attempts, max_attempts, now, row["id"]),
                )
                conn.commit()
                return None

            token_id = row["id"]
            session_token = secrets.token_hex(32)
            token_expires_at = self._utc_future(days=token_days)

            # Marca token usado e grava o session_token
            conn.execute(
                """
                UPDATE auth_tokens
                SET token = NULL, token_hash = ?, token_expires_at = ?, used_at = ?
                WHERE id = ?
                """,
                (hashlib.sha256(session_token.encode("utf-8")).hexdigest(), token_expires_at, now, token_id),
            )

            # Cria ou atualiza usuário
            user_row = conn.execute("SELECT id FROM users WHERE email = ?", (email,)).fetchone()
            if user_row:
                conn.execute("UPDATE users SET last_login_at = ? WHERE email = ?", (now, email))
            else:
                conn.execute(
                    "INSERT INTO users (email, role, created_at, last_login_at) VALUES (?, 'student', ?, ?)",
                    (email, now, now),
                )

            conn.commit()
            return session_token

    def get_user_by_token(self, token: str) -> dict[str, Any] | None:
        """Valida o session token e retorna as informações do usuário."""
        if not token:
            return None
        now = self._utc_now()
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT t.email, u.role, u.created_at, u.last_login_at
                FROM auth_tokens t
                JOIN users u ON u.email = t.email
                WHERE t.token_hash = ? AND t.token_expires_at >= ?
                LIMIT 1
                """,
                (hashlib.sha256(token.encode("utf-8")).hexdigest(), now),
            ).fetchone()

            if not row:
                return None

            return dict(row)

    def revoke_token(self, token: str) -> bool:
        """Revoga um token de sessão."""
        if not token:
            return False
        with self._connect() as conn:
            cursor = conn.execute(
                "UPDATE auth_tokens SET token_expires_at = '1970-01-01T00:00:00Z' WHERE token_hash = ?",
                (hashlib.sha256(token.encode("utf-8")).hexdigest(),),
            )
            conn.commit()
            return cursor.rowcount > 0

    def delete_job(self, job_id: str) -> bool:
        with self._connect() as conn:
            cursor = conn.execute("DELETE FROM jobs WHERE job_id = ?", (job_id,))
            conn.commit()
            return cursor.rowcount > 0

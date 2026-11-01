"""Persistent UI state and grading records backed by Neon PostgreSQL.

SQLite is retained only for local development and tests. Production refuses to use
a local file and requires Neon through NEON_DATABASE_URL or DATABASE_URL.
"""

import hmac
import json
import os
import sqlite3
import time
from pathlib import Path


class UIStorageError(RuntimeError):
    """Raised when persistent UI storage is missing or unavailable."""


def _neon_database_url() -> str | None:
    value = os.getenv("NEON_DATABASE_URL", "").strip() or os.getenv("DATABASE_URL", "").strip()
    return value or None


def grading_snapshot_backend() -> str:
    if _neon_database_url():
        return "neon_postgresql"
    if os.getenv("APP_ENV", "").strip().lower() != "production":
        return "sqlite_local"
    return "unconfigured"


def _database_path() -> str:
    configured = os.getenv("AUTOGRADER_STATE_DB", "").strip()
    if not configured:
        configured = str(
            Path.home() / ".local" / "share" / "autograder" / "ui-state.sqlite3"
        )
    path = Path(configured).expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    return str(path)


class _Connection:
    """Small SQL compatibility wrapper for PostgreSQL and explicit local SQLite."""

    def __init__(self, raw, *, postgres: bool):
        self.raw = raw
        self.postgres = postgres

    def execute(self, statement: str, parameters=()):
        if self.postgres:
            statement = statement.replace("?", "%s")
        return self.raw.execute(statement, parameters)

    def commit(self):
        self.raw.commit()

    def rollback(self):
        self.raw.rollback()

    def close(self):
        self.raw.close()

    def begin_write(self):
        self.execute("BEGIN" if self.postgres else "BEGIN IMMEDIATE")


def _connect() -> _Connection:
    database_url = _neon_database_url()
    try:
        if database_url:
            import psycopg
            return _Connection(psycopg.connect(database_url, connect_timeout=10), postgres=True)
        if os.getenv("APP_ENV", "").strip().lower() == "production":
            raise UIStorageError(
                "NEON_DATABASE_URL is required for persistent production storage."
            )
        raw = sqlite3.connect(_database_path(), timeout=10, isolation_level=None)
        raw.execute("PRAGMA busy_timeout = 10000")
        raw.execute("PRAGMA foreign_keys = ON")
        return _Connection(raw, postgres=False)
    except UIStorageError:
        raise
    except Exception as exc:
        raise UIStorageError("Persistent Postgres storage is unavailable.") from exc


def verify_storage() -> None:
    """Connect to the configured store and verify its schema/query path."""
    connection = _connect()
    try:
        _initialize(connection)
        row = connection.execute("SELECT 1").fetchone()
        if not row or row[0] != 1:
            raise UIStorageError("Persistent storage returned an invalid health response.")
        connection.commit()
    except Exception as exc:
        if isinstance(exc, UIStorageError):
            raise
        raise UIStorageError("Persistent storage health check failed.") from exc
    finally:
        connection.close()


def _initialize(connection: _Connection) -> None:
    connection.execute("""
        CREATE TABLE IF NOT EXISTS ui_submissions (
            submission_id TEXT PRIMARY KEY,
            session_id TEXT NOT NULL,
            record_json TEXT NOT NULL,
            created_at DOUBLE PRECISION NOT NULL,
            expires_at DOUBLE PRECISION NOT NULL
        )
    """)
    connection.execute("""
        CREATE INDEX IF NOT EXISTS idx_ui_submissions_session
        ON ui_submissions(session_id)
    """)
    connection.execute("""
        CREATE INDEX IF NOT EXISTS idx_ui_submissions_expiry
        ON ui_submissions(expires_at)
    """)
    connection.execute("""
        CREATE TABLE IF NOT EXISTS revoked_ui_sessions (
            token_digest TEXT PRIMARY KEY,
            expires_at DOUBLE PRECISION NOT NULL
        )
    """)
    connection.execute("""
        CREATE INDEX IF NOT EXISTS idx_revoked_ui_sessions_expiry
        ON revoked_ui_sessions(expires_at)
    """)
    scores_type = "JSONB" if connection.postgres else "TEXT"
    snapshot_created_at = "TIMESTAMPTZ NOT NULL DEFAULT now()" if connection.postgres else "DOUBLE PRECISION NOT NULL"
    connection.execute(f"""
        CREATE TABLE IF NOT EXISTS grading_metric_snapshots (
            snapshot_key TEXT PRIMARY KEY,
            scores_json {scores_type} NOT NULL,
            created_at {snapshot_created_at}
        )
    """)
    connection.execute("""
        CREATE TABLE IF NOT EXISTS ai_request_usage (
            usage_date TEXT PRIMARY KEY,
            reserved_credits INTEGER NOT NULL,
            prompt_tokens INTEGER NOT NULL DEFAULT 0,
            completion_tokens INTEGER NOT NULL DEFAULT 0,
            total_tokens INTEGER NOT NULL DEFAULT 0
        )
    """)
    # Persist schema initialization before starting an operation transaction.
    connection.commit()


def revoke_session(token_digest: str, ttl_seconds: int = 1800) -> None:
    now = time.time()
    connection = _connect()
    try:
        _initialize(connection)
        connection.begin_write()
        connection.execute("DELETE FROM revoked_ui_sessions WHERE expires_at <= ?", (now,))
        connection.execute("""
            INSERT INTO revoked_ui_sessions(token_digest, expires_at)
            VALUES (?, ?)
            ON CONFLICT(token_digest) DO UPDATE SET expires_at = excluded.expires_at
        """, (token_digest, now + ttl_seconds))
        connection.commit()
    except Exception as exc:
        connection.rollback()
        if isinstance(exc, UIStorageError):
            raise
        raise UIStorageError("Could not persist session revocation.") from exc
    finally:
        connection.close()


def is_session_revoked(token_digest: str) -> bool:
    connection = _connect()
    try:
        _initialize(connection)
        row = connection.execute(
            "SELECT expires_at FROM revoked_ui_sessions WHERE token_digest = ?",
            (token_digest,),
        ).fetchone()
        if row is None:
            return False
        if row[0] <= time.time():
            connection.execute(
                "DELETE FROM revoked_ui_sessions WHERE token_digest = ?",
                (token_digest,),
            )
            connection.commit()
            return False
        return True
    except Exception as exc:
        if isinstance(exc, UIStorageError):
            raise
        raise UIStorageError("Could not read session revocation state.") from exc
    finally:
        connection.close()


def save_submission(
    submission_id: str,
    session_id: str,
    record: dict,
    ttl_seconds: int = 1800,
    max_records: int = 100,
) -> None:
    now = time.time()
    stored = {
        **record,
        "session_id": session_id,
        "created_at": now,
        "expires_at": now + ttl_seconds,
    }
    try:
        encoded = json.dumps(stored, ensure_ascii=False, allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise UIStorageError("Could not persist non-JSON submission state.") from exc
    connection = _connect()
    try:
        _initialize(connection)
        connection.begin_write()
        connection.execute("DELETE FROM ui_submissions WHERE expires_at <= ?", (now,))
        connection.execute("""
            INSERT INTO ui_submissions
                (submission_id, session_id, record_json, created_at, expires_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(submission_id) DO UPDATE SET
                session_id = excluded.session_id,
                record_json = excluded.record_json,
                created_at = excluded.created_at,
                expires_at = excluded.expires_at
        """, (submission_id, session_id, encoded, now, now + ttl_seconds))
        excess = connection.execute("SELECT COUNT(*) FROM ui_submissions").fetchone()[0] - max_records
        if excess > 0:
            connection.execute("""
                DELETE FROM ui_submissions WHERE submission_id IN (
                    SELECT submission_id FROM ui_submissions
                    ORDER BY created_at ASC LIMIT ?
                )
            """, (excess,))
        connection.commit()
    except Exception as exc:
        connection.rollback()
        if isinstance(exc, UIStorageError):
            raise
        raise UIStorageError("Could not persist submission state.") from exc
    finally:
        connection.close()


def clear_submissions(session_id: str) -> None:
    connection = _connect()
    try:
        _initialize(connection)
        connection.execute("DELETE FROM ui_submissions WHERE session_id = ?", (session_id,))
        connection.commit()
    except Exception as exc:
        connection.rollback()
        if isinstance(exc, UIStorageError):
            raise
        raise UIStorageError("Could not clear submission state.") from exc
    finally:
        connection.close()


def get_submission(session_id: str, submission_id: str) -> dict | None:
    now = time.time()
    connection = _connect()
    try:
        _initialize(connection)
        row = connection.execute("""
            SELECT session_id, record_json, expires_at
            FROM ui_submissions WHERE submission_id = ?
        """, (submission_id,)).fetchone()
        if row is None:
            return None
        owner, encoded, expires_at = row
        if expires_at <= now:
            connection.execute("DELETE FROM ui_submissions WHERE submission_id = ?", (submission_id,))
            connection.commit()
            return None
        if not hmac.compare_digest(owner, session_id):
            return None
        return json.loads(encoded)
    except Exception as exc:
        if isinstance(exc, UIStorageError):
            raise
        raise UIStorageError("Could not read submission state.") from exc
    finally:
        connection.close()


def get_grading_metric_snapshot(snapshot_key: str) -> dict | None:
    """Return the immutable complete metric snapshot for a stable evaluation key."""
    connection = _connect()
    try:
        _initialize(connection)
        row = connection.execute(
            "SELECT scores_json FROM grading_metric_snapshots WHERE snapshot_key = ?",
            (snapshot_key,),
        ).fetchone()
        if row is None:
            return None
        return row[0] if isinstance(row[0], dict) else json.loads(row[0])
    except Exception as exc:
        if isinstance(exc, UIStorageError):
            raise
        raise UIStorageError("Could not read grading metric snapshot.") from exc
    finally:
        connection.close()


def save_grading_metric_snapshot(snapshot_key: str, scores: dict) -> dict:
    """Persist the first complete metric snapshot; concurrent first writer wins."""
    try:
        encoded = json.dumps(scores, sort_keys=True, separators=(",", ":"), allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise UIStorageError("Could not serialize grading metric snapshot.") from exc
    connection = _connect()
    try:
        _initialize(connection)
        connection.begin_write()
        stored_scores = json.loads(encoded)
        if connection.postgres:
            import psycopg
            stored_scores = psycopg.types.json.Jsonb(stored_scores)
        if connection.postgres:
            connection.execute("""
                INSERT INTO grading_metric_snapshots(snapshot_key, scores_json)
                VALUES (?, ?)
                ON CONFLICT(snapshot_key) DO NOTHING
            """, (snapshot_key, stored_scores))
        else:
            connection.execute("""
                INSERT INTO grading_metric_snapshots(snapshot_key, scores_json, created_at)
                VALUES (?, ?, ?)
                ON CONFLICT(snapshot_key) DO NOTHING
            """, (snapshot_key, encoded, time.time()))
        row = connection.execute(
            "SELECT scores_json FROM grading_metric_snapshots WHERE snapshot_key = ?",
            (snapshot_key,),
        ).fetchone()
        connection.commit()
        return row[0] if isinstance(row[0], dict) else json.loads(row[0])
    except Exception as exc:
        connection.rollback()
        if isinstance(exc, UIStorageError):
            raise
        raise UIStorageError("Could not persist grading metric snapshot.") from exc
    finally:
        connection.close()


def reserve_ai_request_credits(credits: int, daily_limit: int) -> int | None:
    """Atomically reserve shared daily AI credits; None means the cap is reached."""
    for name, value in (("credits", credits), ("daily_limit", daily_limit)):
        if isinstance(value, bool) or not isinstance(value, int) or value < 1:
            raise ValueError(f"{name} must be a positive integer.")
    from datetime import datetime, timezone

    today = datetime.now(timezone.utc).date().isoformat()
    connection = _connect()
    try:
        _initialize(connection)
        connection.begin_write()
        connection.execute("""
            INSERT INTO ai_request_usage(usage_date, reserved_credits)
            VALUES (?, 0)
            ON CONFLICT(usage_date) DO NOTHING
        """, (today,))
        cursor = connection.execute("""
            UPDATE ai_request_usage
            SET reserved_credits = reserved_credits + ?
            WHERE usage_date = ? AND reserved_credits + ? <= ?
        """, (credits, today, credits, daily_limit))
        if cursor.rowcount != 1:
            connection.rollback()
            return None
        row = connection.execute(
            "SELECT reserved_credits FROM ai_request_usage WHERE usage_date = ?",
            (today,),
        ).fetchone()
        connection.commit()
        return int(row[0])
    except Exception as exc:
        connection.rollback()
        if isinstance(exc, UIStorageError):
            raise
        raise UIStorageError("Could not reserve the shared AI request budget.") from exc
    finally:
        connection.close()


def record_ai_token_usage(
    prompt_tokens: int,
    completion_tokens: int,
    total_tokens: int,
) -> None:
    """Add provider-reported token totals to today's shared usage row."""
    values = (prompt_tokens, completion_tokens, total_tokens)
    if any(isinstance(value, bool) or not isinstance(value, int) or value < 0 for value in values):
        raise ValueError("Provider token usage must contain non-negative integers.")
    from datetime import datetime, timezone

    today = datetime.now(timezone.utc).date().isoformat()
    connection = _connect()
    try:
        _initialize(connection)
        connection.execute("""
            UPDATE ai_request_usage
            SET prompt_tokens = prompt_tokens + ?,
                completion_tokens = completion_tokens + ?,
                total_tokens = total_tokens + ?
            WHERE usage_date = ?
        """, (*values, today))
        connection.commit()
    except Exception as exc:
        connection.rollback()
        if isinstance(exc, UIStorageError):
            raise
        raise UIStorageError("Could not record provider token usage.") from exc
    finally:
        connection.close()


def get_ai_request_usage(usage_date: str | None = None) -> dict | None:
    """Read aggregate AI request and token usage for a UTC date (today by default)."""
    from datetime import datetime, timezone

    date = usage_date or datetime.now(timezone.utc).date().isoformat()
    connection = _connect()
    try:
        _initialize(connection)
        row = connection.execute("""
            SELECT reserved_credits, prompt_tokens, completion_tokens, total_tokens
            FROM ai_request_usage WHERE usage_date = ?
        """, (date,)).fetchone()
        if row is None:
            return None
        return {
            "reserved_credits": int(row[0]),
            "prompt_tokens": int(row[1]),
            "completion_tokens": int(row[2]),
            "total_tokens": int(row[3]),
        }
    except Exception as exc:
        if isinstance(exc, UIStorageError):
            raise
        raise UIStorageError("Could not read AI request usage.") from exc
    finally:
        connection.close()

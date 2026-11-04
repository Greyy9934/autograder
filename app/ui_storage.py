"""Persistent UI state and grading records backed by Neon PostgreSQL.

SQLite is retained only for local development and tests. Production refuses to use
a local file and requires Neon through NEON_DATABASE_URL or DATABASE_URL.
"""
# It saves submissions and grade records in the shared production database or local development storage.

import hmac
import json
import os
import sqlite3
import time
from pathlib import Path


class UIStorageError(RuntimeError):
    """Raised when persistent UI storage is missing or unavailable."""


def _neon_database_url() -> str | None:
    # Finds the database address from the app settings, if one has been set.
    # This function takes no named inputs.
    # What it gives back: It returns text or nothing if unavailable.
    value = os.getenv("NEON_DATABASE_URL", "").strip() or os.getenv("DATABASE_URL", "").strip()
    return value or None


def grading_snapshot_backend() -> str:
    # Handles neon database url as a supporting part of ui storage .
    # This function takes no named inputs.
    # What it gives back: It returns text.
    if _neon_database_url():
        return "neon_postgresql"
    if (
        os.getenv("APP_ENV", "").strip().lower() != "production"
        or os.getenv("ALLOW_SQLITE_IN_PROD", "").lower() in {"1", "true", "yes"}
        or os.getenv("AUTOGRADER_ALLOW_SQLITE_IN_PROD", "").lower() in {"1", "true", "yes"}
    ):
        return "sqlite_local"
    return "unconfigured"


def _database_path() -> str:
    # Handles grading snapshot backend as a supporting part of ui storage .
    # This function takes no named inputs.
    # What it gives back: It returns text.
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
        # Helps with init inside init.
        # What the inputs mean:
        # - raw: the raw used for this step.
        # - postgres: the postgres used for this step.
        # - self/cls: the current object this function belongs to.
        # What it gives back: It returns the result that the next step needs.
        self.raw = raw
        self.postgres = postgres

    def execute(self, statement: str, parameters=()):
        # Handles init as a supporting part of ui storage .
        # What the inputs mean:
        # - statement: the statement used for this step.
        # - parameters: the named number values used in a formula.
        # - self/cls: the current object this function belongs to.
        # What it gives back: It returns the result that the next step needs.
        if self.postgres:
            statement = statement.replace("?", "%s")
        return self.raw.execute(statement, parameters)

    def commit(self):
        # Handles execute as a supporting part of ui storage .
        # This function takes no named inputs.
        # - self/cls: the current object this function belongs to.
        # What it gives back: It returns the result that the next step needs.
        self.raw.commit()

    def rollback(self):
        # Saves the database changes.
        # This function takes no named inputs.
        # - self/cls: the current object this function belongs to.
        # What it gives back: It returns the result that the next step needs.
        self.raw.rollback()

    def close(self):
        # Cancels the unfinished database changes.
        # This function takes no named inputs.
        # - self/cls: the current object this function belongs to.
        # What it gives back: It returns the result that the next step needs.
        self.raw.close()

    def begin_write(self):
        # Closes the resource when this work is finished.
        # This function takes no named inputs.
        # - self/cls: the current object this function belongs to.
        # What it gives back: It returns the result that the next step needs.
        self.execute("BEGIN" if self.postgres else "BEGIN IMMEDIATE")


def _connect() -> _Connection:
    # Handles begin write as a supporting part of ui storage .
    # This function takes no named inputs.
    # What it gives back: It returns the Connection result.
    database_url = _neon_database_url()
    try:
        if database_url:
            import psycopg
            return _Connection(psycopg.connect(database_url, connect_timeout=10), postgres=True)
        if (
            os.getenv("APP_ENV", "").strip().lower() == "production"
            and os.getenv("ALLOW_SQLITE_IN_PROD", "").lower() not in {"1", "true", "yes"}
            and os.getenv("AUTOGRADER_ALLOW_SQLITE_IN_PROD", "").lower() not in {"1", "true", "yes"}
        ):
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
    # Checks storage.
    # This function takes no named inputs.
    # What it gives back: It does its work and does not return a value.
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
    # Checks that the database can be reached and has the tables the app needs.
    # What the inputs mean:
    # - connection: the connection used for this step.
    # What it gives back: It does its work and does not return a value.
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
    # Marks a login session as no longer valid.
    # What the inputs mean:
    # - token_digest: the token digest used for this step.
    # - ttl_seconds: the ttl seconds used for this step.
    # What it gives back: It does its work and does not return a value.
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
    # Checks whether a login session was previously signed out or disabled.
    # What the inputs mean:
    # - token_digest: the token digest used for this step.
    # What it gives back: It returns yes or no.
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
    # Stores a submission with the session that owns it.
    # What the inputs mean:
    # - submission_id: the identifier for this submission.
    # - session_id: the instructor session that owns this submission.
    # - record: the record used for this step.
    # - ttl_seconds: the ttl seconds used for this step.
    # - max_records: the max records used for this step.
    # What it gives back: It does its work and does not return a value.
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
    # Removes saved submissions belonging to a session.
    # What the inputs mean:
    # - session_id: the instructor session that owns this submission.
    # What it gives back: It does its work and does not return a value.
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
    # Loads a submission only for the session that owns it.
    # What the inputs mean:
    # - session_id: the instructor session that owns this submission.
    # - submission_id: the identifier for this submission.
    # What it gives back: It returns the dict | None result.
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
    # Looks up the saved score set for an evaluation that has already been graded.
    # What the inputs mean:
    # - snapshot_key: the identity used to find a saved grade.
    # What it gives back: It returns the dict | None result.
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
    # Saves the first complete score set for an evaluation so later repeats can reuse it.
    # What the inputs mean:
    # - snapshot_key: the identity used to find a saved grade.
    # - scores: the complete set of scores to save.
    # What it gives back: It returns the dict result.
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
    # Reserves request slots before paid AI work so concurrent requests cannot quietly exceed the daily limit.
    # What the inputs mean:
    # - credits: the credits used for this step.
    # - daily_limit: the daily limit used for this step.
    # What it gives back: It returns the int | None result.
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
    # Records ai token usage.
    # What the inputs mean:
    # - prompt_tokens: the prompt tokens used for this step.
    # - completion_tokens: the completion tokens used for this step.
    # - total_tokens: the total tokens used for this step.
    # What it gives back: It does its work and does not return a value.
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
    # Gets ai request usage.
    # What the inputs mean:
    # - usage_date: the usage date used for this step.
    # What it gives back: It returns the dict | None result.
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

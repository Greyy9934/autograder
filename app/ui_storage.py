"""Persistent UI state and grading records backed by Neon PostgreSQL.

SQLite is retained only for local development and tests. Production refuses to use
a local file and requires Neon through NEON_DATABASE_URL or DATABASE_URL.
"""
# Module role: Persists transient UI state, session revocations, AI usage, and immutable grading snapshots in Neon PostgreSQL (SQLite for local development).
# Core concept: Neon PostgreSQL is production persistence; SQLite is intentionally a local-development fallback. Grade snapshots use insert-on-conflict-do-nothing so concurrent first writers cannot silently replace a grade.

import hmac
import json
import os
import sqlite3
import time
from pathlib import Path


class UIStorageError(RuntimeError):
    """Raised when persistent UI storage is missing or unavailable."""


# Function role: Implements the internal neon database url helper for ui storage.
# Same-file callers: grading_snapshot_backend, _connect.
def _neon_database_url() -> str | None:
    # In-function documentation:
    # Parameters: none.
    # Returns: a value of declared type str | None.
    # Flow: derive or store intermediate values; return the stage result.
    value = os.getenv("NEON_DATABASE_URL", "").strip() or os.getenv("DATABASE_URL", "").strip()
    return value or None


# Function role: Implements grading snapshot backend for ui storage using this module's input and result contracts.
# Direct call references (conditional/branch-dependent): _neon_database_url.
def grading_snapshot_backend() -> str:
    # In-function documentation:
    # Parameters: none.
    # Returns: a value of declared type str.
    # Flow: branch on validation or workflow conditions; return the stage result.
    if _neon_database_url():
        return "neon_postgresql"
    if os.getenv("APP_ENV", "").strip().lower() != "production":
        return "sqlite_local"
    return "unconfigured"


# Function role: Implements the internal database path helper for ui storage.
# Same-file callers: _connect.
def _database_path() -> str:
    # In-function documentation:
    # Parameters: none.
    # Returns: a value of declared type str.
    # Flow: derive or store intermediate values; branch on validation or workflow conditions; delegate work to a helper or external boundary.
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

    # Function role: Initializes the object and its validated dependencies.
    # Context: method/helper owned by _Connection; it is reached through that object's workflow.
    def __init__(self, raw, *, postgres: bool):
        # In-function documentation:
        # Parameters:
        #   - raw: the raw value used by this operation.
        #   - postgres: the postgres value used by this operation (type annotation: bool).
        #   - self/cls: receiver carrying the current object or class state.
        # Returns: the operation result consumed by its caller.
        # Flow: derive or store intermediate values.
        self.raw = raw
        self.postgres = postgres

    # Function role: Implements execute for ui storage using this module's input and result contracts.
    # Context: method/helper owned by _Connection; it is reached through that object's workflow.
    # Same-file callers: _connect, verify_storage, _initialize, revoke_session, is_session_revoked and other helpers.
    # Direct call references (conditional/branch-dependent): execute.
    def execute(self, statement: str, parameters=()):
        # In-function documentation:
        # Parameters:
        #   - statement: the statement value used by this operation (type annotation: str).
        #   - parameters: the parameters value used by this operation; defaults to () when omitted.
        #   - self/cls: receiver carrying the current object or class state.
        # Returns: the result produced by the delegated helper.
        # Flow: branch on validation or workflow conditions; return the stage result.
        if self.postgres:
            statement = statement.replace("?", "%s")
        return self.raw.execute(statement, parameters)

    # Function role: Implements commit for ui storage using this module's input and result contracts.
    # Context: method/helper owned by _Connection; it is reached through that object's workflow.
    # Same-file callers: verify_storage, _initialize, revoke_session, is_session_revoked, save_submission and other helpers.
    # Direct call references (conditional/branch-dependent): commit.
    def commit(self):
        # In-function documentation:
        # Parameters: none.
        #   - self/cls: receiver carrying the current object or class state.
        # Returns: the operation result consumed by its caller.
        # Flow: delegate work to a helper or external boundary.
        self.raw.commit()

    # Function role: Implements rollback for ui storage using this module's input and result contracts.
    # Context: method/helper owned by _Connection; it is reached through that object's workflow.
    # Same-file callers: revoke_session, save_submission, clear_submissions, save_grading_metric_snapshot, reserve_ai_request_credits and other helpers.
    # Direct call references (conditional/branch-dependent): rollback.
    def rollback(self):
        # In-function documentation:
        # Parameters: none.
        #   - self/cls: receiver carrying the current object or class state.
        # Returns: the operation result consumed by its caller.
        # Flow: delegate work to a helper or external boundary.
        self.raw.rollback()

    # Function role: Implements close for ui storage using this module's input and result contracts.
    # Context: method/helper owned by _Connection; it is reached through that object's workflow.
    # Same-file callers: verify_storage, revoke_session, is_session_revoked, save_submission, clear_submissions and other helpers.
    # Direct call references (conditional/branch-dependent): close.
    def close(self):
        # In-function documentation:
        # Parameters: none.
        #   - self/cls: receiver carrying the current object or class state.
        # Returns: the operation result consumed by its caller.
        # Flow: delegate work to a helper or external boundary.
        self.raw.close()

    # Function role: Implements begin write for ui storage using this module's input and result contracts.
    # Context: method/helper owned by _Connection; it is reached through that object's workflow.
    # Same-file callers: revoke_session, save_submission, save_grading_metric_snapshot, reserve_ai_request_credits.
    # Direct call references (conditional/branch-dependent): execute.
    def begin_write(self):
        # In-function documentation:
        # Parameters: none.
        #   - self/cls: receiver carrying the current object or class state.
        # Returns: the operation result consumed by its caller.
        # Flow: delegate work to a helper or external boundary.
        self.execute("BEGIN" if self.postgres else "BEGIN IMMEDIATE")


# Function role: Uses psycopg for Neon/PostgreSQL when a database URL is configured; local SQLite is allowed only outside production. Production fails closed rather than silently writing to ephemeral disk.
# Same-file callers: verify_storage, revoke_session, is_session_revoked, save_submission, clear_submissions and other helpers.
# Direct call references (conditional/branch-dependent): _neon_database_url, _database_path, execute.
def _connect() -> _Connection:
    # In-function documentation:
    # Parameters: none.
    # Returns: a value of declared type _Connection.
    # Flow: derive or store intermediate values; convert expected failures into controlled results.
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


# Function role: Connect to the configured store and verify its schema/query path.
# Direct call references (conditional/branch-dependent): _connect, _initialize, execute, commit, close.
def verify_storage() -> None:
    """Connect to the configured store and verify its schema/query path."""
    # In-function documentation:
    # Parameters: none.
    # Returns: no value (None); work is performed through side effects or validation.
    # Flow: derive or store intermediate values; convert expected failures into controlled results.
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


# Function role: Creates required tables and indexes idempotently before storage operations.
# Same-file callers: verify_storage, revoke_session, is_session_revoked, save_submission, clear_submissions and other helpers.
# Direct call references (conditional/branch-dependent): execute, commit.
def _initialize(connection: _Connection) -> None:
    # In-function documentation:
    # Parameters:
    #   - connection: the connection value used by this operation (type annotation: _Connection).
    # Returns: no value (None); work is performed through side effects or validation.
    # Flow: delegate work to a helper or external boundary.
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


# Function role: Implements revoke session for ui storage using this module's input and result contracts.
# Direct call references (conditional/branch-dependent): _connect, _initialize, begin_write, execute, commit, rollback, close.
def revoke_session(token_digest: str, ttl_seconds: int = 1800) -> None:
    # In-function documentation:
    # Parameters:
    #   - token_digest: the token digest value used by this operation (type annotation: str).
    #   - ttl_seconds: the ttl seconds value used by this operation (type annotation: int); defaults to 1800 when omitted.
    # Returns: no value (None); work is performed through side effects or validation.
    # Flow: derive or store intermediate values; convert expected failures into controlled results.
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


# Function role: Returns whether session revoked holds under this module's rules.
# Direct call references (conditional/branch-dependent): _connect, _initialize, execute, commit, close.
def is_session_revoked(token_digest: str) -> bool:
    # In-function documentation:
    # Parameters:
    #   - token_digest: the token digest value used by this operation (type annotation: str).
    # Returns: a value of declared type bool.
    # Flow: derive or store intermediate values; convert expected failures into controlled results.
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


# Function role: Persists submission through the module's storage boundary.
# Direct call references (conditional/branch-dependent): _connect, _initialize, begin_write, execute, commit, rollback, close.
def save_submission(
    submission_id: str,
    session_id: str,
    record: dict,
    ttl_seconds: int = 1800,
    max_records: int = 100,
) -> None:
    # In-function documentation:
    # Parameters:
    #   - submission_id: stable identifier for this submission/evaluation record (type annotation: str).
    #   - session_id: authenticated session identifier that owns this workflow state (type annotation: str).
    #   - record: the record value used by this operation (type annotation: dict).
    #   - ttl_seconds: the ttl seconds value used by this operation (type annotation: int); defaults to 1800 when omitted.
    #   - max_records: the max records value used by this operation (type annotation: int); defaults to 100 when omitted.
    # Returns: no value (None); work is performed through side effects or validation.
    # Flow: derive or store intermediate values; convert expected failures into controlled results.
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


# Function role: Clears submissions from the relevant state container.
# Direct call references (conditional/branch-dependent): _connect, _initialize, execute, commit, rollback, close.
def clear_submissions(session_id: str) -> None:
    # In-function documentation:
    # Parameters:
    #   - session_id: authenticated session identifier that owns this workflow state (type annotation: str).
    # Returns: no value (None); work is performed through side effects or validation.
    # Flow: derive or store intermediate values; convert expected failures into controlled results.
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


# Function role: Retrieves submission from the validated workflow or configured storage.
# Direct call references (conditional/branch-dependent): _connect, _initialize, execute, commit, close.
def get_submission(session_id: str, submission_id: str) -> dict | None:
    # In-function documentation:
    # Parameters:
    #   - session_id: authenticated session identifier that owns this workflow state (type annotation: str).
    #   - submission_id: stable identifier for this submission/evaluation record (type annotation: str).
    # Returns: a value of declared type dict | None.
    # Flow: derive or store intermediate values; convert expected failures into controlled results.
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


# Function role: Return the immutable complete metric snapshot for a stable evaluation key.
# Direct call references (conditional/branch-dependent): _connect, _initialize, execute, close.
def get_grading_metric_snapshot(snapshot_key: str) -> dict | None:
    """Return the immutable complete metric snapshot for a stable evaluation key."""
    # In-function documentation:
    # Parameters:
    #   - snapshot_key: the snapshot key value used by this operation (type annotation: str).
    # Returns: a value of declared type dict | None.
    # Flow: derive or store intermediate values; convert expected failures into controlled results.
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


# Function role: Uses insert-on-conflict-do-nothing so concurrent workers preserve the first complete grade vector; that first-writer-wins rule is the reproducibility anchor.
# Numbered workflow order: 07.3 - persist the first complete metric vector for the stable evaluation identity.
# Direct call references (conditional/branch-dependent): _connect, _initialize, begin_write, execute, commit, rollback, close.
def save_grading_metric_snapshot(snapshot_key: str, scores: dict) -> dict:
    """Persist the first complete metric snapshot; concurrent first writer wins."""
    # In-function documentation:
    # Parameters:
    #   - snapshot_key: the snapshot key value used by this operation (type annotation: str).
    #   - scores: mapping of grading dimensions to normalized scores (type annotation: dict).
    # Returns: a value of declared type dict.
    # Flow: convert expected failures into controlled results; derive or store intermediate values.
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


# Function role: Atomically reserve shared daily AI credits; None means the cap is reached.
# Direct call references (conditional/branch-dependent): _connect, _initialize, begin_write, execute, rollback, commit, close.
def reserve_ai_request_credits(credits: int, daily_limit: int) -> int | None:
    """Atomically reserve shared daily AI credits; None means the cap is reached."""
    # In-function documentation:
    # Parameters:
    #   - credits: the credits value used by this operation (type annotation: int).
    #   - daily_limit: the daily limit value used by this operation (type annotation: int).
    # Returns: a value of declared type int | None.
    # Flow: iterate through input or evidence items; derive or store intermediate values; convert expected failures into controlled results.
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


# Function role: Add provider-reported token totals to today's shared usage row.
# Direct call references (conditional/branch-dependent): _connect, _initialize, execute, commit, rollback, close.
def record_ai_token_usage(
    prompt_tokens: int,
    completion_tokens: int,
    total_tokens: int,
) -> None:
    """Add provider-reported token totals to today's shared usage row."""
    # In-function documentation:
    # Parameters:
    #   - prompt_tokens: the prompt tokens value used by this operation (type annotation: int).
    #   - completion_tokens: the completion tokens value used by this operation (type annotation: int).
    #   - total_tokens: the total tokens value used by this operation (type annotation: int).
    # Returns: no value (None); work is performed through side effects or validation.
    # Flow: derive or store intermediate values; branch on validation or workflow conditions.
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


# Function role: Read aggregate AI request and token usage for a UTC date (today by default).
# Direct call references (conditional/branch-dependent): _connect, _initialize, execute, close.
def get_ai_request_usage(usage_date: str | None = None) -> dict | None:
    """Read aggregate AI request and token usage for a UTC date (today by default)."""
    # In-function documentation:
    # Parameters:
    #   - usage_date: the usage date value used by this operation (type annotation: str | None); defaults to None when omitted.
    # Returns: a value of declared type dict | None.
    # Flow: derive or store intermediate values; convert expected failures into controlled results.
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

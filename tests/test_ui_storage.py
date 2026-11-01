import importlib
import json
import pytest


def test_submission_survives_storage_module_reload(tmp_path, monkeypatch):
    monkeypatch.setenv("AUTOGRADER_STATE_DB", str(tmp_path / "state.sqlite3"))
    import app.ui_storage as storage

    storage.save_submission("submission-123", "session-a", {"source": "int main(){}"})
    importlib.reload(storage)

    record = storage.get_submission("session-a", "submission-123")
    assert record is not None
    assert record["source"] == "int main(){}"
    assert record["session_id"] == "session-a"


def test_submission_is_not_visible_to_another_session(tmp_path, monkeypatch):
    monkeypatch.setenv("AUTOGRADER_STATE_DB", str(tmp_path / "state.sqlite3"))
    import app.ui_storage as storage

    storage.save_submission("submission-456", "session-a", {"result": {"grade": 80}})
    assert storage.get_submission("session-b", "submission-456") is None
    assert storage.get_submission("session-a", "submission-456")["result"]["grade"] == 80


def test_session_revocation_survives_module_reload(tmp_path, monkeypatch):
    monkeypatch.setenv("AUTOGRADER_STATE_DB", str(tmp_path / "state.sqlite3"))
    import app.ui_storage as storage

    storage.revoke_session("token-digest")
    importlib.reload(storage)
    assert storage.is_session_revoked("token-digest") is True


def test_clear_submissions_only_clears_owning_session(tmp_path, monkeypatch):
    monkeypatch.setenv("AUTOGRADER_STATE_DB", str(tmp_path / "state.sqlite3"))
    import app.ui_storage as storage

    storage.save_submission("one", "session-a", {"n": 1})
    storage.save_submission("two", "session-b", {"n": 2})
    storage.clear_submissions("session-a")

    assert storage.get_submission("session-a", "one") is None
    assert storage.get_submission("session-b", "two")["n"] == 2


def test_non_json_submission_is_rejected(tmp_path, monkeypatch):
    monkeypatch.setenv("AUTOGRADER_STATE_DB", str(tmp_path / "state.sqlite3"))
    import app.ui_storage as storage

    with pytest.raises(storage.UIStorageError):
        storage.save_submission("bad", "session-a", {"bad": object()})


def test_grading_metric_snapshot_is_persistent_and_first_complete_vector_wins(tmp_path, monkeypatch):
    monkeypatch.setenv("AUTOGRADER_STATE_DB", str(tmp_path / "state.sqlite3"))
    import app.ui_storage as storage

    first = storage.save_grading_metric_snapshot("same-evaluation", {"complexity": None, "readability": 75})
    assert first == {"complexity": None, "readability": 75}
    importlib.reload(storage)
    second = storage.save_grading_metric_snapshot("same-evaluation", {"complexity": 50, "readability": 25})
    assert second == {"complexity": None, "readability": 75}
    assert storage.get_grading_metric_snapshot("same-evaluation") == second


def test_neon_backend_handles_all_persistent_ui_records(tmp_path, monkeypatch):
    import sqlite3
    import sys
    import types

    database_path = tmp_path / "fake-neon-server.sqlite3"
    calls = []

    class FakePostgresConnection:
        def __init__(self):
            self.raw = sqlite3.connect(database_path, timeout=10, isolation_level=None)

        def execute(self, statement, parameters=()):
            statement = statement.replace("%s", "?")
            statement = statement.replace(
                "created_at TIMESTAMPTZ NOT NULL DEFAULT now()",
                "created_at DOUBLE PRECISION NOT NULL DEFAULT 0",
            )
            normalized = tuple(
                json.dumps(value.obj, sort_keys=True) if hasattr(value, "obj") else value
                for value in parameters
            )
            return self.raw.execute(statement, normalized)

        def commit(self):
            return self.raw.commit()

        def rollback(self):
            return self.raw.rollback()

        def close(self):
            return self.raw.close()

    class Jsonb:
        def __init__(self, obj):
            self.obj = obj

    fake_psycopg = types.SimpleNamespace(
        connect=lambda *args, **kwargs: (calls.append((args, kwargs)) or FakePostgresConnection()),
        types=types.SimpleNamespace(json=types.SimpleNamespace(Jsonb=Jsonb)),
    )
    monkeypatch.setitem(sys.modules, "psycopg", fake_psycopg)
    monkeypatch.setenv("NEON_DATABASE_URL", "postgresql://fake-neon/test?sslmode=require")
    monkeypatch.setenv("AUTOGRADER_STATE_DB", str(tmp_path / "must-not-be-used.sqlite3"))

    import app.ui_storage as storage

    assert storage.grading_snapshot_backend() == "neon_postgresql"
    storage.verify_storage()
    assert storage.reserve_ai_request_credits(2, 3) == 2
    assert storage.reserve_ai_request_credits(2, 3) is None
    storage.record_ai_token_usage(11, 7, 18)
    assert storage.get_ai_request_usage()["total_tokens"] == 18
    storage.save_submission("submission", "owner", {"source": "int main() {}"})
    assert storage.get_submission("owner", "submission")["source"] == "int main() {}"
    assert storage.get_submission("other", "submission") is None
    storage.revoke_session("token-digest")
    assert storage.is_session_revoked("token-digest") is True
    storage.save_grading_metric_snapshot("grade-key", {"correctness": 90, "complexity": None})
    assert storage.get_grading_metric_snapshot("grade-key") == {
        "correctness": 90,
        "complexity": None,
    }
    assert storage.save_grading_metric_snapshot(
        "grade-key", {"correctness": 1}
    ) == {"correctness": 90, "complexity": None}
    storage.clear_submissions("owner")
    assert storage.get_submission("owner", "submission") is None
    assert len(calls) >= 8
    assert not (tmp_path / "must-not-be-used.sqlite3").exists()


def test_production_requires_neon_database(monkeypatch):
    import app.ui_storage as storage

    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.delenv("NEON_DATABASE_URL", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("AUTOGRADER_STATE_DB", raising=False)

    with pytest.raises(storage.UIStorageError, match="NEON_DATABASE_URL is required"):
        storage.verify_storage()


def test_local_ai_request_ledger_enforces_limit_and_records_tokens(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("AUTOGRADER_STATE_DB", str(tmp_path / "state.sqlite3"))
    import app.ui_storage as storage

    assert storage.reserve_ai_request_credits(1, 2) == 1
    assert storage.reserve_ai_request_credits(1, 2) == 2
    assert storage.reserve_ai_request_credits(1, 2) is None
    storage.record_ai_token_usage(13, 9, 22)
    assert storage.get_ai_request_usage() == {
        "reserved_credits": 2,
        "prompt_tokens": 13,
        "completion_tokens": 9,
        "total_tokens": 22,
    }

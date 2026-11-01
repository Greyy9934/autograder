"""Keep ordinary tests away from a developer's configured database."""

import os

import pytest


@pytest.fixture(autouse=True)
def isolate_tests_from_external_databases(monkeypatch):
    """Tests use isolated storage unless explicitly pointed at a disposable Neon branch."""
    if os.getenv("AUTOGRADER_TEST_ALLOW_EXTERNAL_DATABASE", "").strip() != "1":
        monkeypatch.delenv("NEON_DATABASE_URL", raising=False)
        monkeypatch.delenv("DATABASE_URL", raising=False)

"""Persistent, concurrency-safe AI request budget."""

import os
import sqlite3
from contextlib import closing
from pathlib import Path

from app.ai.base import AIProviderError


class RequestBudget:
    def __init__(
        self,
        database_path: str | Path,
        daily_limit: int,
    ) -> None:
        if isinstance(daily_limit, bool) or not isinstance(daily_limit, int) or daily_limit < 1:
            raise ValueError("daily_limit must be a positive integer.")

        self.database_path = str(database_path)
        self.daily_limit = daily_limit
        Path(self.database_path).parent.mkdir(parents=True, exist_ok=True)

        with closing(self._connect()) as connection:
            connection.execute("""
                CREATE TABLE IF NOT EXISTS ai_usage (
                    usage_date TEXT PRIMARY KEY,
                    reserved_credits INTEGER NOT NULL
                )
            """)

    def _connect(self):
        connection = sqlite3.connect(
            self.database_path,
            timeout=10,
            isolation_level=None,
        )
        connection.execute("PRAGMA busy_timeout = 10000")
        return connection

    def reserve(self, credits: int = 1) -> int:
        """Atomically reserve credits before an AI operation."""
        from datetime import datetime, timezone

        if isinstance(credits, bool) or not isinstance(credits, int) or credits < 1:
            raise ValueError("credits must be a positive integer.")

        today = datetime.now(timezone.utc).date().isoformat()

        try:
            with closing(self._connect()) as connection:
                connection.execute("BEGIN IMMEDIATE")
                connection.execute(
                    """
                    INSERT OR IGNORE INTO ai_usage (usage_date, reserved_credits)
                    VALUES (?, 0)
                    """,
                    (today,),
                )
                row = connection.execute(
                    "SELECT reserved_credits FROM ai_usage WHERE usage_date = ?",
                    (today,),
                ).fetchone()

                used = row[0]
                if used + credits > self.daily_limit:
                    connection.rollback()
                    raise AIProviderError(
                        "Daily AI request budget exhausted.",
                        category="budget_exhausted",
                    )

                new_total = used + credits
                connection.execute(
                    """
                    UPDATE ai_usage
                    SET reserved_credits = ?
                    WHERE usage_date = ?
                    """,
                    (new_total, today),
                )
                connection.commit()
                return new_total

        except AIProviderError:
            raise
        except (sqlite3.Error, OSError) as exc:
            raise AIProviderError(
                "AI budget storage is unavailable; request blocked.",
                category="budget_storage_error",
            ) from exc


class BudgetedProvider:
    """Reserve budget credits before delegating to an AI provider."""

    def __init__(self, provider, budget: RequestBudget, credits_per_call: int = 1):
        if (
            isinstance(credits_per_call, bool)
            or not isinstance(credits_per_call, int)
            or credits_per_call < 1
        ):
            raise ValueError("credits_per_call must be a positive integer.")

        self.provider = provider
        self.budget = budget
        self.credits_per_call = credits_per_call

    def generate_json(self, task, payload, schema):
        self.budget.reserve(self.credits_per_call)
        return self.provider.generate_json(task, payload, schema)


def create_request_budget() -> RequestBudget:
    default_path = Path.home() / ".local" / "share" / "autograder" / "ai-budget.sqlite3"
    path = os.getenv("AI_BUDGET_DB", str(default_path))
    limit = int(os.getenv("AI_DAILY_REQUEST_CREDITS", "60"))
    return RequestBudget(path, limit)

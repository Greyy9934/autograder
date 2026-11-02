"""Persistent, concurrency-safe AI request budget."""

import logging
import os
import sqlite3
import time
from contextlib import closing
from pathlib import Path

from app.ai.base import AIProviderError
from app.ai.diagnostics import request_id_var
from app.ai.output_budget import (
    MAX_PROVIDER_INPUT_JSON_BYTES,
    output_token_cap_for_task,
    reasoning_effort_for_task,
)


class RequestBudget:
    def __init__(
        self,
        database_path: str | Path,
        daily_limit: int,
    ) -> None:
        if isinstance(daily_limit, bool) or not isinstance(daily_limit, int) or daily_limit < 1:
            raise ValueError("daily_limit must be a positive integer.")

        self.database_path = str(database_path).strip()
        self.daily_limit = daily_limit
        self.shared_storage = bool(
            os.getenv("NEON_DATABASE_URL", "").strip()
            or os.getenv("DATABASE_URL", "").strip()
            or os.getenv("APP_ENV", "").strip().lower() in {"production", "prod"}
        )

        if not self.database_path and not self.shared_storage:
            raise AIProviderError(
                "AI budget database path is empty; request blocked.",
                category="budget_configuration_error",
            )

        if self.shared_storage:
            return

        try:
            Path(self.database_path).parent.mkdir(parents=True, exist_ok=True)
            with closing(self._connect()) as connection:
                connection.execute("""
                    CREATE TABLE IF NOT EXISTS ai_usage (
                        usage_date TEXT PRIMARY KEY,
                        reserved_credits INTEGER NOT NULL
                    )
                """)
                connection.execute("""
                    CREATE TABLE IF NOT EXISTS ai_usage_tokens (
                        usage_date TEXT PRIMARY KEY,
                        prompt_tokens INTEGER NOT NULL DEFAULT 0,
                        completion_tokens INTEGER NOT NULL DEFAULT 0,
                        total_tokens INTEGER NOT NULL DEFAULT 0
                    )
                """)
        except (sqlite3.Error, OSError) as exc:
            raise AIProviderError(
                "AI budget storage could not be initialized; request blocked.",
                category="budget_storage_error",
            ) from exc

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

        if self.shared_storage:
            try:
                from app.ui_storage import reserve_ai_request_credits

                reserved = reserve_ai_request_credits(credits, self.daily_limit)
            except Exception as exc:
                raise AIProviderError(
                    "Shared AI budget storage is unavailable; request blocked.",
                    category="budget_storage_error",
                ) from exc
            if reserved is None:
                raise AIProviderError(
                    "Daily AI request budget exhausted.",
                    category="budget_exhausted",
                )
            return reserved

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

    def record_usage(self, usage: dict) -> None:
        """Persist provider-reported token counts without storing prompts or code."""
        values = (
            usage.get("prompt_tokens"),
            usage.get("completion_tokens"),
            usage.get("total_tokens"),
        )
        if any(
            isinstance(value, bool) or not isinstance(value, int) or value < 0
            for value in values
        ):
            return
        if self.shared_storage:
            from app.ui_storage import record_ai_token_usage

            record_ai_token_usage(*values)
            return

        from datetime import datetime, timezone

        today = datetime.now(timezone.utc).date().isoformat()
        try:
            with closing(self._connect()) as connection:
                connection.execute(
                    """
                    INSERT OR IGNORE INTO ai_usage_tokens
                        (usage_date, prompt_tokens, completion_tokens, total_tokens)
                    VALUES (?, 0, 0, 0)
                    """,
                    (today,),
                )
                connection.execute(
                    """
                    UPDATE ai_usage_tokens
                    SET prompt_tokens = prompt_tokens + ?,
                        completion_tokens = completion_tokens + ?,
                        total_tokens = total_tokens + ?
                    WHERE usage_date = ?
                    """,
                    (*values, today),
                )
                connection.commit()
        except (sqlite3.Error, OSError) as exc:
            raise AIProviderError(
                "Could not record provider token usage.",
                category="budget_usage_storage_error",
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
        # Keep the concrete provider object intact for existing integrations.
        # Enforce the same request/response contract at the shared call boundary.
        from app.ai.guardrails import GuardedProvider

        logger = logging.getLogger(__name__)
        provider_name = type(self.provider).__name__
        model = getattr(self.provider, "model", "unknown")
        request_cap = output_token_cap_for_task(task)
        reasoning_effort = reasoning_effort_for_task(task)
        if provider_name == "DeepSeekProvider":
            import json
            input_json_bytes = len(json.dumps(
                {"payload": payload, "schema": schema},
                ensure_ascii=False,
                separators=(",", ":"),
            ).encode("utf-8"))
            if input_json_bytes > MAX_PROVIDER_INPUT_JSON_BYTES:
                exc = AIProviderError(
                    "AI input exceeds the per-request size safety limit; reduce the problem or source size.",
                    category="input_too_large",
                )
                logger.warning(
                    "ai_request_blocked request_id=%s provider=%s model=%s task=%s category=input_too_large input_json_bytes=%d limit_bytes=%d",
                    request_id_var.get(), provider_name, model, task,
                    input_json_bytes, MAX_PROVIDER_INPUT_JSON_BYTES,
                )
                raise exc
        try:
            reserved_total = self.budget.reserve(self.credits_per_call)
        except Exception as exc:
            logger.warning(
                "ai_request_blocked request_id=%s provider=%s model=%s task=%s error_type=%s category=%s status_code=%s",
                request_id_var.get(),
                provider_name,
                model,
                task,
                type(exc).__name__,
                getattr(exc, "category", "unknown"),
                getattr(exc, "status_code", None),
            )
            raise

        started = time.perf_counter()
        logger.info(
            "ai_request_started request_id=%s provider=%s model=%s task=%s max_output_tokens=%s reasoning_effort=%s daily_reserved=%s daily_limit=%s",
            request_id_var.get(),
            provider_name,
            model,
            task,
            min(request_cap, getattr(self.provider, "max_tokens", request_cap)),
            reasoning_effort,
            reserved_total,
            getattr(self.budget, "daily_limit", "unknown"),
        )
        try:
            result = GuardedProvider(self.provider).generate_json(
                task, payload, schema
            )
        except Exception as exc:
            self._record_provider_usage()
            usage = getattr(self.provider, "last_usage", None) or {}
            logger.warning(
                "ai_request_failed request_id=%s provider=%s model=%s task=%s elapsed_ms=%.1f error_type=%s category=%s status_code=%s retryable=%s finish_reason=%s prompt_tokens=%s completion_tokens=%s reasoning_tokens=%s total_tokens=%s",
                request_id_var.get(),
                provider_name,
                model,
                task,
                (time.perf_counter() - started) * 1000,
                type(exc).__name__,
                getattr(exc, "category", "unknown"),
                getattr(exc, "status_code", None),
                getattr(exc, "retryable", None),
                getattr(self.provider, "last_finish_reason", None),
                usage.get("prompt_tokens", "unknown"),
                usage.get("completion_tokens", "unknown"),
                usage.get("reasoning_tokens", "unknown"),
                usage.get("total_tokens", "unknown"),
            )
            raise
        self._record_provider_usage()
        usage = getattr(self.provider, "last_usage", None) or {}
        logger.info(
            "ai_request_completed request_id=%s provider=%s model=%s task=%s elapsed_ms=%.1f finish_reason=%s prompt_tokens=%s completion_tokens=%s reasoning_tokens=%s total_tokens=%s",
            request_id_var.get(),
            provider_name,
            model,
            task,
            (time.perf_counter() - started) * 1000,
            getattr(self.provider, "last_finish_reason", None),
            usage.get("prompt_tokens", "unknown"),
            usage.get("completion_tokens", "unknown"),
            usage.get("reasoning_tokens", "unknown"),
            usage.get("total_tokens", "unknown"),
        )
        return result

    def _record_provider_usage(self) -> None:
        usage = getattr(self.provider, "last_usage", None)
        if not isinstance(usage, dict):
            return
        try:
            self.budget.record_usage(usage)
        except Exception as exc:
            # A successful paid response must not be discarded and repeated
            # just because post-response token telemetry could not be written.
            import logging

            logging.getLogger(__name__).error(
                "Could not persist provider token usage (%s).", type(exc).__name__
            )


def create_request_budget() -> RequestBudget:
    default_path = Path.home() / ".local" / "share" / "autograder" / "ai-budget.sqlite3"
    path = os.getenv("AI_BUDGET_DB", str(default_path)).strip()
    raw_limit = os.getenv("AI_DAILY_REQUEST_CREDITS", "350").strip()

    try:
        limit = int(raw_limit)
    except (TypeError, ValueError) as exc:
        raise AIProviderError(
            "AI_DAILY_REQUEST_CREDITS must be a positive integer.",
            category="budget_configuration_error",
        ) from exc

    if limit < 1:
        raise AIProviderError(
            "AI_DAILY_REQUEST_CREDITS must be a positive integer.",
            category="budget_configuration_error",
        )

    return RequestBudget(path, limit)

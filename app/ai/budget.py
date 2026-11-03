"""Persistent, concurrency-safe AI request budget."""
# Module role: Reserves one shared daily request credit before a provider call and records provider-reported token usage afterwards.
# Core concept: A request credit is reserved before each provider call. Token ceilings only cap possible output; actual billing follows provider usage, and hidden automatic retries are avoided for paid calls.

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
    # Function role: Initializes the object and its validated dependencies.
    # Context: method/helper owned by RequestBudget; it is reached through that object's workflow.
    # Direct call references (conditional/branch-dependent): _connect.
    def __init__(
        self,
        database_path: str | Path,
        daily_limit: int,
    ) -> None:
        # In-function documentation:
        # Parameters:
        #   - database_path: the database path value used by this operation (type annotation: str | Path).
        #   - daily_limit: the daily limit value used by this operation (type annotation: int).
        #   - self/cls: receiver carrying the current object or class state.
        # Returns: no value (None); work is performed through side effects or validation.
        # Flow: branch on validation or workflow conditions; derive or store intermediate values.
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

    # Function role: Opens the configured persistent or local-development database connection.
    # Context: method/helper owned by RequestBudget; it is reached through that object's workflow.
    # Same-file callers: __init__, reserve, record_usage.
    def _connect(self):
        # In-function documentation:
        # Parameters: none.
        #   - self/cls: receiver carrying the current object or class state.
        # Returns: the computed connection value.
        # Flow: derive or store intermediate values; delegate work to a helper or external boundary; return the stage result.
        connection = sqlite3.connect(
            self.database_path,
            timeout=10,
            isolation_level=None,
        )
        connection.execute("PRAGMA busy_timeout = 10000")
        return connection

    # Function role: Atomically reserve credits before an AI operation.
    # Context: method/helper owned by RequestBudget; it is reached through that object's workflow.
    # Same-file callers: generate_json.
    # Direct call references (conditional/branch-dependent): _connect.
    def reserve(self, credits: int = 1) -> int:
        """Atomically reserve credits before an AI operation."""
        # In-function documentation:
        # Parameters:
        #   - credits: the credits value used by this operation (type annotation: int); defaults to 1 when omitted.
        #   - self/cls: receiver carrying the current object or class state.
        # Returns: a value of declared type int; alternate return paths may produce the computed new_total value.
        # Flow: branch on validation or workflow conditions; derive or store intermediate values; convert expected failures into controlled results.
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

    # Function role: Persist provider-reported token counts without storing prompts or code.
    # Context: method/helper owned by RequestBudget; it is reached through that object's workflow.
    # Same-file callers: _record_provider_usage.
    # Direct call references (conditional/branch-dependent): _connect.
    def record_usage(self, usage: dict) -> None:
        """Persist provider-reported token counts without storing prompts or code."""
        # In-function documentation:
        # Parameters:
        #   - usage: the usage value used by this operation (type annotation: dict).
        #   - self/cls: receiver carrying the current object or class state.
        # Returns: no value (None); work is performed through side effects or validation.
        # Flow: derive or store intermediate values; branch on validation or workflow conditions.
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

    # Function role: Initializes the object and its validated dependencies.
    # Context: method/helper owned by BudgetedProvider; it is reached through that object's workflow.
    def __init__(self, provider, budget: RequestBudget, credits_per_call: int = 1):
        # In-function documentation:
        # Parameters:
        #   - provider: the configured AI provider implementation used for one request.
        #   - budget: the budget value used by this operation (type annotation: RequestBudget).
        #   - credits_per_call: the credits per call value used by this operation (type annotation: int); defaults to 1 when omitted.
        #   - self/cls: receiver carrying the current object or class state.
        # Returns: the operation result consumed by its caller.
        # Flow: branch on validation or workflow conditions; derive or store intermediate values.
        if (
            isinstance(credits_per_call, bool)
            or not isinstance(credits_per_call, int)
            or credits_per_call < 1
        ):
            raise ValueError("credits_per_call must be a positive integer.")

        self.provider = provider
        self.budget = budget
        self.credits_per_call = credits_per_call

    # Function role: Requests one structured JSON response from the configured provider or deterministic fixture.
    # Context: method/helper owned by BudgetedProvider; it is reached through that object's workflow.
    # Same-file callers: generate_json.
    # Direct call references (conditional/branch-dependent): reserve, generate_json, _record_provider_usage.
    def generate_json(self, task, payload, schema):
        # Keep the concrete provider object intact for existing integrations.
        # Enforce the same request/response contract at the shared call boundary.
        # In-function documentation:
        # Parameters:
        #   - task: the task value used by this operation.
        #   - payload: the request data being sent across an API/provider boundary.
        #   - schema: declared data contract inputs or results must satisfy.
        #   - self/cls: receiver carrying the current object or class state.
        # Returns: the computed result value.
        # Flow: derive or store intermediate values.
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

    # Function role: Implements the internal record provider usage helper for budget.
    # Context: method/helper owned by BudgetedProvider; it is reached through that object's workflow.
    # Same-file callers: generate_json.
    # Direct call references (conditional/branch-dependent): record_usage.
    def _record_provider_usage(self) -> None:
        # In-function documentation:
        # Parameters: none.
        #   - self/cls: receiver carrying the current object or class state.
        # Returns: no value (None); work is performed through side effects or validation.
        # Flow: derive or store intermediate values; branch on validation or workflow conditions; convert expected failures into controlled results.
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


# Function role: Constructs request budget with the module's required invariants.
def create_request_budget() -> RequestBudget:
    # In-function documentation:
    # Parameters: none.
    # Returns: a value of declared type RequestBudget.
    # Flow: derive or store intermediate values; convert expected failures into controlled results.
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

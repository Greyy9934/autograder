"""Request-scoped diagnostic context shared by workflow and provider logs."""
# This file handles diagnostics as one part of the app.

from contextvars import ContextVar

request_id_var: ContextVar[str] = ContextVar("autograder_request_id", default="-")

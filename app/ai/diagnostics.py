"""Request-scoped diagnostic context shared by workflow and provider logs."""
# In plain terms: This file handles diagnostics, one part of the AutoGrader’s workflow.

from contextvars import ContextVar

request_id_var: ContextVar[str] = ContextVar("autograder_request_id", default="-")

"""Request-scoped diagnostic context shared by workflow and provider logs."""
# Module role: Implements the diagnostics subsystem used by the AutoGrader workflow.

from contextvars import ContextVar

request_id_var: ContextVar[str] = ContextVar("autograder_request_id", default="-")

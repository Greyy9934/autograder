import time
from collections import defaultdict, deque
import threading
import hashlib
import hmac
from pathlib import Path
import os
import secrets

from fastapi import FastAPI, HTTPException, Header
from pydantic import BaseModel, Field

from analyzers.source_risks import analyze_source_risks
from analyzers.complexity_estimator import estimate_complexity
from app.orchestrator import evaluate_submission
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.requests import Request

BASE_DIR = Path(__file__).resolve().parent

app = FastAPI(
    title="AutoGrader API",
    description="Rule-driven evaluator for C programs",
    version="0.2.0",
)

app.mount(
    "/static",
    StaticFiles(directory=BASE_DIR / "static"),
    name="static",
)

templates = Jinja2Templates(directory=BASE_DIR / "templates")


def _approval_signing_key() -> bytes:
    key = os.getenv("INSTRUCTOR_TOKEN_SIGNING_KEY", "").strip()
    if len(key) < 32:
        raise HTTPException(
            status_code=503,
            detail="Instructor token signing is not configured securely.",
        )
    return key.encode("utf-8")


def _create_approval_token(fingerprint: str) -> str:
    issued_at = str(int(time.time()))
    message = f"{fingerprint}:{issued_at}".encode("utf-8")
    signature = hmac.new(
        _approval_signing_key(), message, hashlib.sha256
    ).hexdigest()
    return f"{issued_at}.{signature}"


def _create_draft_token(fingerprint: str) -> str:
    issued_at = str(int(time.time()))
    message = f"draft:{fingerprint}:{issued_at}".encode("utf-8")
    signature = hmac.new(
        _approval_signing_key(), message, hashlib.sha256
    ).hexdigest()
    return f"{issued_at}.{signature}"


def _verify_draft_token(fingerprint: str, token: str) -> bool:
    try:
        issued_text, supplied_signature = token.split(".", 1)
        issued_at = int(issued_text)
    except (ValueError, AttributeError):
        return False

    now = int(time.time())
    if issued_at > now or now - issued_at > 900:
        return False

    message = f"draft:{fingerprint}:{issued_text}".encode("utf-8")
    expected = hmac.new(
        _approval_signing_key(), message, hashlib.sha256
    ).hexdigest()
    return secrets.compare_digest(expected, supplied_signature)


def _verify_approval_token(fingerprint: str, token: str) -> bool:
    try:
        issued_text, supplied_signature = token.split(".", 1)
        issued_at = int(issued_text)
    except (ValueError, AttributeError):
        return False

    now = int(time.time())
    if issued_at > now or now - issued_at > 900:
        return False

    message = f"{fingerprint}:{issued_text}".encode("utf-8")
    expected = hmac.new(
        _approval_signing_key(), message, hashlib.sha256
    ).hexdigest()
    return secrets.compare_digest(expected, supplied_signature)


@app.get("/", response_class=HTMLResponse, include_in_schema=False)
def home(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={"app_version": app.version},
    )


@app.get("/health")
def health():
    return {
        "status": "ok",
        "service": "autograder",
        "code_execution_enabled": False,
        "ui_enabled": True,
    }


@app.get("/api/status")
def api_status():
    return {
        "service": "AutoGrader",
        "status": "online",
        "evaluation_enabled": False,
        "message": (
            "The interface is available. Grading remains disabled until "
            "the evaluation API and secure execution environment are connected."
        ),
    }



class AnalysisRequest(BaseModel):
    source: str = Field(min_length=1, max_length=262144)


class PreparationRequest(BaseModel):
    source: str = Field(min_length=1, max_length=262144)
    problem_statement: str | None = Field(default=None, max_length=20000)


class ConfirmAssignmentRequest(BaseModel):
    assignment_spec: dict
    expected_fingerprint: str = Field(min_length=64, max_length=64)
    draft_token: str = Field(min_length=1, max_length=256)
    instructor_approved: bool



@app.post("/api/confirm-assignment")
def confirm_assignment(
    request: ConfirmAssignmentRequest,
    x_instructor_key: str | None = Header(default=None),
):
    configured_key = os.getenv("INSTRUCTOR_CONFIRMATION_KEY", "").strip()
    if not configured_key:
        raise HTTPException(
            status_code=503,
            detail="Instructor confirmation is not configured.",
        )
    if (
        not x_instructor_key
        or not secrets.compare_digest(x_instructor_key, configured_key)
    ):
        raise HTTPException(status_code=401, detail="Invalid instructor key.")

    if request.instructor_approved is not True:
        raise HTTPException(
            status_code=403,
            detail="Explicit instructor approval is required.",
        )

    from analyzers.assignment_spec import AssignmentSpec

    try:
        values = dict(request.assignment_spec)
        values["constraints"] = tuple(values.get("constraints", ()))
        draft = AssignmentSpec(**values)
        if draft.confirmed:
            raise ValueError("The submitted specification must be an unconfirmed draft.")
        fingerprint = draft.fingerprint()
        if not secrets.compare_digest(
            fingerprint, request.expected_fingerprint
        ):
            raise ValueError("Assignment specification fingerprint mismatch.")
        if not _verify_draft_token(fingerprint, request.draft_token):
            raise ValueError("Invalid or expired server-issued draft token.")

        confirmed = draft.confirm(instructor_approved=True)
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    fingerprint = confirmed.fingerprint()
    return {
        "status": "confirmed",
        "assignment_spec": confirmed.to_dict(),
        "assignment_spec_fingerprint": fingerprint,
        "approval_token": _create_approval_token(fingerprint),
        "approval_token_expires_in_seconds": 900,
        "confirmation": "instructor_approved",
    }


# Per-process rate limiter for authenticated preparation requests.
_PREPARATION_REQUESTS = defaultdict(deque)
_PREPARATION_RATE_LOCK = threading.Lock()


def _check_preparation_rate_limit(api_key: str) -> None:
    limit = int(os.getenv("PREPARATION_RATE_LIMIT", "10"))
    window = int(os.getenv("PREPARATION_RATE_WINDOW_SECONDS", "60"))

    if limit < 1 or window < 1:
        raise HTTPException(status_code=503, detail="Rate limiter is misconfigured.")

    key_fingerprint = hashlib.sha256(api_key.encode("utf-8")).hexdigest()
    now = time.monotonic()
    cutoff = now - window

    with _PREPARATION_RATE_LOCK:
        requests = _PREPARATION_REQUESTS[key_fingerprint]

        while requests and requests[0] <= cutoff:
            requests.popleft()

        if len(requests) >= limit:
            retry_after = max(1, int(window - (now - requests[0])))
            raise HTTPException(
                status_code=429,
                detail="Preparation request rate limit exceeded. Try again shortly.",
                headers={"Retry-After": str(retry_after)},
            )

        requests.append(now)


@app.post("/api/prepare")
def prepare_submission(
    request: PreparationRequest,
    x_preparation_key: str | None = Header(default=None),
):
    configured_key = os.getenv("PREPARATION_API_KEY", "").strip()
    if not configured_key:
        raise HTTPException(
            status_code=503,
            detail="Preparation API is not configured.",
        )
    if (
        not x_preparation_key
        or not secrets.compare_digest(x_preparation_key, configured_key)
    ):
        raise HTTPException(status_code=401, detail="Invalid preparation API key.")

    _check_preparation_rate_limit(x_preparation_key)

    if not request.source.strip():
        raise HTTPException(status_code=422, detail="Source must not be blank.")

    if request.problem_statement is not None and not request.problem_statement.strip():
        raise HTTPException(
            status_code=422,
            detail="Problem statement must not be blank when supplied.",
        )

    result = evaluate_submission(
        source=request.source,
        problem_statement=request.problem_statement,
    )
    fingerprint = result.get("assignment_spec_fingerprint")
    if (
        result.get("assignment_spec_status")
        == "draft_requires_instructor_confirmation"
        and isinstance(result.get("assignment_spec"), dict)
        and isinstance(fingerprint, str)
    ):
        result["assignment_spec_draft_token"] = _create_draft_token(
            fingerprint
        )
    return result


@app.post("/api/analyze")
def analyze_source(request: AnalysisRequest):
    source_bytes = request.source.encode("utf-8")
    if len(source_bytes) > 262144:
        raise HTTPException(status_code=413, detail="Source exceeds 256 KiB.")
    if not request.source.strip():
        raise HTTPException(status_code=422, detail="Source must not be blank.")

    return {
        "status": "completed",
        "analysis_only": True,
        "code_executed": False,
        "source_risks": analyze_source_risks(request.source),
        "complexity": estimate_complexity(request.source),
        "limitations": [
            "This endpoint does not compile or execute submitted C code.",
            "Findings are heuristic and do not establish correctness.",
            "No grade or correctness verdict is produced.",
        ],
    }


class ReferenceGenerationRequest(BaseModel):
    assignment_spec: dict
    expected_fingerprint: str = Field(min_length=64, max_length=64)
    approval_token: str = Field(min_length=1, max_length=256)


@app.post("/api/generate-references")
def generate_references(
    request: ReferenceGenerationRequest,
    x_instructor_key: str | None = Header(default=None),
):
    configured_key = os.getenv("INSTRUCTOR_CONFIRMATION_KEY", "").strip()
    if not configured_key:
        raise HTTPException(status_code=503, detail="Instructor confirmation is not configured.")

    if not x_instructor_key or not secrets.compare_digest(
        x_instructor_key, configured_key
    ):
        raise HTTPException(status_code=401, detail="Invalid instructor key.")

    from analyzers.assignment_spec import AssignmentSpec
    from app.orchestrator import generate_reference_solutions_for_confirmed_spec

    try:
        values = dict(request.assignment_spec)
        values["constraints"] = tuple(values.get("constraints", ()))
        spec = AssignmentSpec(**values)

        if not spec.confirmed:
            raise ValueError("Instructor-confirmed specification required.")

        if not secrets.compare_digest(
            spec.fingerprint(), request.expected_fingerprint
        ):
            raise ValueError("Assignment specification fingerprint mismatch.")

        if not _verify_approval_token(
            spec.fingerprint(), request.approval_token
        ):
            raise ValueError("Invalid or expired instructor approval token.")

    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    return generate_reference_solutions_for_confirmed_spec(spec)


@app.get("/workflow", include_in_schema=False)
async def evaluation_workflow_page():
    """Serve the standalone evaluation workflow page."""
    return FileResponse(
        Path(__file__).resolve().parent / "templates" / "workflow.html",
        media_type="text/html"
    )


@app.get("/rubric", include_in_schema=False)
async def grading_rubric_page():
    """Serve the standalone grading rubric page."""
    return FileResponse(
        Path(__file__).resolve().parent / "templates" / "rubric.html",
        media_type="text/html"
    )


@app.get("/principles", include_in_schema=False)
async def design_principles_page():
    """Serve the standalone design principles page."""
    return FileResponse(
        Path(__file__).resolve().parent / "templates" / "principles.html",
        media_type="text/html"
    )

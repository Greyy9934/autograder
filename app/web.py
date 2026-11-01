from typing import Any
import time
from collections import defaultdict, deque
import threading
import hashlib
import hmac
from pathlib import Path
import os
import secrets
import tempfile
import io
import json
import zipfile

from fastapi import FastAPI, HTTPException, Header, Response
from pydantic import BaseModel, Field
from dotenv import load_dotenv

from analyzers.source_risks import analyze_source_risks
from analyzers.complexity_estimator import estimate_complexity
from analyzers.preflight import preflight
from analyzers.complexity_benchmark import benchmark_complexity
from analyzers.code_quality import analyze_code_quality, review_code_quality
from analyzers.assignment_spec import AssignmentSpec
from analyzers.input_schema import IntegerInputSchema
from analyzers.test_generation import generate_test_plans
from analyzers.agent3_ai import (
    generate_agent3a_program,
    execute_agent3a_program,
    analyze_agent3b_edges,
    validate_agent3b_edges,
)
from analyzers.batch_execution import run_c_batch
from analyzers.batch_execution import benchmark_three_programs_parallel
from app.ai.config import create_ai_provider, mock_mode_enabled
from app.ai.base import AIProviderError
from app.orchestrator import evaluate_submission, evaluate_execution_evidence
from app.runner import compile_c_source
from app.grading import grade_submission, DEFAULT_GRADING_RULES
from app.metric_scoring import derive_metric_scores
from app.ui_storage import (
    get_grading_metric_snapshot as _persistent_get_grade_metrics,
    save_grading_metric_snapshot as _persistent_save_grade_metrics,
    grading_snapshot_backend as _grade_snapshot_backend,
    verify_storage as _verify_persistent_storage,
)
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.requests import Request
from starlette.background import BackgroundTask
from app.pdf_report import generate_pdf_report
from app.ai.demo_runner import build_real_demo_payload

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR.parent / '.env', override=False)

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
    try:
        _verify_persistent_storage()
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Persistent database unavailable.") from exc
    return {
        "status": "ok",
        "service": "autograder",
        "storage": _grade_snapshot_backend(),
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
    source: str = Field(default="", max_length=262144)
    problem_statement: str | None = Field(default=None, max_length=20000)
    demo_mode: bool = False
    demo_scenario_id: str | None = Field(default=None, max_length=64)


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
    if mock_mode_enabled():
        result["provider_mode"] = "offline_mock"
        result["mock_mode_notice"] = (
            "AI agent responses are simulated. Preflight, compilation, schema "
            "validation, generated-input execution, benchmarking and C execution "
            "remain real."
        )
        if isinstance(result.get("reconstruction"), dict):
            result["reconstruction"]["analysis_mode"] = "simulated"
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
        "preflight": preflight(request.source),
        "source_risks": analyze_source_risks(request.source),
        "complexity": estimate_complexity(request.source),
        "code_quality": analyze_code_quality(request.source),
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
    *,
    provider: Any = None,
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
        if not secrets.compare_digest(spec.fingerprint(), request.expected_fingerprint):
            raise ValueError("Assignment specification fingerprint mismatch.")
        if not _verify_approval_token(spec.fingerprint(), request.approval_token):
            raise ValueError("Invalid or expired instructor approval token.")
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    result = generate_reference_solutions_for_confirmed_spec(spec, provider=provider)
    if provider is not None and isinstance(result, dict):
        result["analysis_mode"] = "simulated"
        result["provider_mode"] = "demo_scenario"
    elif mock_mode_enabled() and isinstance(result, dict):
        result["analysis_mode"] = "simulated"
        result["provider_mode"] = "offline_mock"
    return result


class InstructorLoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=128)
    password: str = Field(min_length=1, max_length=256)


_LOGIN_ATTEMPTS = defaultdict(deque)
_LOGIN_ATTEMPTS_LOCK = threading.Lock()


def _check_login_rate_limit(client_ip: str) -> None:
    now = time.monotonic()
    with _LOGIN_ATTEMPTS_LOCK:
        attempts = _LOGIN_ATTEMPTS[client_ip]
        while attempts and attempts[0] <= now - 300:
            attempts.popleft()
        if len(attempts) >= 5:
            raise HTTPException(
                status_code=429,
                detail="Too many login attempts. Try again in five minutes.",
            )


def _record_login_failure(client_ip: str) -> None:
    with _LOGIN_ATTEMPTS_LOCK:
        _LOGIN_ATTEMPTS[client_ip].append(time.monotonic())


def _clear_login_failures(client_ip: str) -> None:
    with _LOGIN_ATTEMPTS_LOCK:
        _LOGIN_ATTEMPTS.pop(client_ip, None)


def _verify_instructor_password(password: str) -> bool:
    encoded = os.getenv("AUTOGRADER_PASSWORD_HASH", "").strip()
    try:
        algorithm, iterations_text, salt_hex, expected_hex = encoded.split("$")
        iterations = int(iterations_text)
        salt = bytes.fromhex(salt_hex)
        expected = bytes.fromhex(expected_hex)
        if algorithm != "pbkdf2_sha256" or iterations < 600000:
            return False
        if len(salt) < 16 or len(expected) != 32:
            return False
        actual = hashlib.pbkdf2_hmac(
            "sha256", password.encode("utf-8"), salt, iterations
        )
        return secrets.compare_digest(actual, expected)
    except (ValueError, TypeError):
        return False


def _create_ui_session_token() -> str:
    issued = str(int(time.time()))
    nonce = secrets.token_urlsafe(24)
    payload = f"{issued}.{nonce}"
    message = f"ui-session:{payload}".encode()
    signature = hmac.new(
        _approval_signing_key(), message, hashlib.sha256
    ).hexdigest()
    return f"{payload}.{signature}"


def _verify_ui_session_token(token: str | None) -> bool:
    if not token:
        return False
    try:
        issued, nonce, supplied = token.split(".", 2)
        timestamp = int(issued)
        if not nonce or len(nonce) > 128:
            return False
    except (ValueError, AttributeError):
        return False

    now = int(time.time())
    if timestamp > now or now - timestamp > 1800:
        return False

    payload = f"{issued}.{nonce}"
    message = f"ui-session:{payload}".encode()
    expected = hmac.new(
        _approval_signing_key(), message, hashlib.sha256
    ).hexdigest()
    if not secrets.compare_digest(expected, supplied):
        return False
    return not _is_ui_session_revoked(token)


def _require_ui_session(request: Request) -> str:
    token = request.cookies.get("autograder_instructor_session")
    if not _verify_ui_session_token(token):
        raise HTTPException(status_code=401, detail="Instructor login required.")
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


# Durable shared state: Neon PostgreSQL is authoritative in production.
from app.ui_storage import (
    UIStorageError,
    clear_submissions as _persistent_clear_submissions,
    get_submission as _persistent_get_submission,
    is_session_revoked as _persistent_is_session_revoked,
    revoke_session as _persistent_revoke_session,
    save_submission as _persistent_save_submission,
)

_UI_SUBMISSION_TTL_SECONDS = 1800
_UI_SUBMISSION_MAX_RECORDS = 100

# Process cache for workflow code and tests that mutate records directly.
# Neon PostgreSQL remains the persistent source of truth.
_UI_SUBMISSIONS: dict[str, dict[str, Any]] = {}
_UI_SUBMISSIONS_LOCK = threading.RLock()


def _revoke_ui_session_token(token: str) -> None:
    digest = hashlib.sha256(token.encode("utf-8")).hexdigest()
    try:
        _persistent_revoke_session(digest, 1800)
    except UIStorageError as exc:
        raise HTTPException(
            status_code=503, detail="Session security storage unavailable."
        ) from exc


def _is_ui_session_revoked(token: str) -> bool:
    digest = hashlib.sha256(token.encode("utf-8")).hexdigest()
    try:
        return _persistent_is_session_revoked(digest)
    except UIStorageError as exc:
        raise HTTPException(
            status_code=503, detail="Session security storage unavailable."
        ) from exc


def _save_ui_submission(session_id: str, record: dict[str, Any]) -> str:
    now = time.time()
    submission_id = secrets.token_urlsafe(32)
    stored = {
        **record,
        "session_id": session_id,
        "created_at": now,
        "expires_at": now + _UI_SUBMISSION_TTL_SECONDS,
    }
    try:
        _persistent_save_submission(
            submission_id, session_id, stored,
            _UI_SUBMISSION_TTL_SECONDS, _UI_SUBMISSION_MAX_RECORDS,
        )
    except UIStorageError as exc:
        raise HTTPException(
            status_code=503, detail="Submission storage unavailable."
        ) from exc
    with _UI_SUBMISSIONS_LOCK:
        _UI_SUBMISSIONS[submission_id] = stored
    return submission_id


def _clear_ui_submissions(session_id: str) -> None:
    try:
        _persistent_clear_submissions(session_id)
    except UIStorageError as exc:
        raise HTTPException(
            status_code=503, detail="Submission storage unavailable."
        ) from exc
    with _UI_SUBMISSIONS_LOCK:
        owned = [
            key for key, record in _UI_SUBMISSIONS.items()
            if secrets.compare_digest(record.get("session_id", ""), session_id)
        ]
        for key in owned:
            _UI_SUBMISSIONS.pop(key, None)


def _get_ui_submission(session_id: str, submission_id: str) -> dict[str, Any]:
    now = time.time()
    with _UI_SUBMISSIONS_LOCK:
        record = _UI_SUBMISSIONS.get(submission_id)

        if record is not None:
            if (
                record.get("expires_at", 0) <= now
                or not secrets.compare_digest(
                    record.get("session_id", ""), session_id
                )
            ):
                _UI_SUBMISSIONS.pop(submission_id, None)
                raise HTTPException(
                    status_code=404,
                    detail="Submission not found, expired, or not owned by this session.",
                )

            # Persist mutations made by existing workflow code between requests.
            remaining = max(1, int(record["expires_at"] - now))
            try:
                _persistent_save_submission(
                    submission_id, session_id, record,
                    remaining, _UI_SUBMISSION_MAX_RECORDS,
                )
            except UIStorageError as exc:
                raise HTTPException(
                    status_code=503, detail="Submission storage unavailable."
                ) from exc
            return record

        try:
            record = _persistent_get_submission(session_id, submission_id)
        except UIStorageError as exc:
            raise HTTPException(
                status_code=503, detail="Submission storage unavailable."
            ) from exc

        if record is None:
            raise HTTPException(
                status_code=404,
                detail="Submission not found, expired, or not owned by this session.",
            )
        _UI_SUBMISSIONS[submission_id] = record
        return record


class UIConfirmRequest(BaseModel):
    submission_id: str = Field(min_length=20, max_length=128)
    instructor_approved: bool


class UIGenerateReferencesRequest(BaseModel):
    submission_id: str = Field(min_length=20, max_length=128)


class UIGenerateTestsRequest(BaseModel):
    submission_id: str = Field(min_length=20, max_length=128)
    token_count: int | None = Field(default=None, ge=1, le=1000)
    minimum: int | None = Field(default=None, ge=-(2**31), le=2**31 - 1)
    maximum: int | None = Field(default=None, ge=-(2**31), le=2**31 - 1)
    random_seed: int = Field(default=42, ge=0, le=2**31 - 1)
    random_count: int = Field(default=100, ge=1, le=1000)
    random_distribution: str = "uniform"
    adversarial_seed: int = Field(default=43, ge=0, le=2**31 - 1)
    adversarial_count: int = Field(default=30, ge=1, le=100)


class UIDemoRequest(BaseModel):
    demo_mode: bool = False


class UIExpectedTestCase(BaseModel):
    input: str = Field(max_length=262144)
    expected_output: str = Field(max_length=262144)


class UIExecuteTestsRequest(BaseModel):
    submission_id: str = Field(min_length=20, max_length=128)
    # These cases must be authored/approved by the instructor.
    test_cases: list[UIExpectedTestCase] | None = Field(
        default=None, max_length=200
    )


class UIComplexityBenchmarkCase(BaseModel):
    input_size: int = Field(gt=0)
    input: str = Field(max_length=262144)


class UIComplexityBenchmarkRequest(BaseModel):
    submission_id: str = Field(min_length=20, max_length=128)
    benchmark_cases: list[UIComplexityBenchmarkCase] = Field(
        min_length=1, max_length=100
    )
    repetitions: int = Field(default=3, ge=1, le=10)


class UIPDFReportRequest(BaseModel):
    submission_id: str = Field(min_length=20, max_length=128)


@app.post("/api/ui/demo")
def instructor_ui_demo(
    http_request: Request,
    request: UIDemoRequest = UIDemoRequest(),
):
    """Run the isolated built-in demo only for an authenticated instructor."""
    _require_ui_session(http_request)
    if request.demo_mode is not True:
        raise HTTPException(status_code=403, detail="Explicit instructor demo mode is required.")
    return build_real_demo_payload()


@app.post("/api/ui/login")
def instructor_ui_login(
    request: InstructorLoginRequest,
    response: Response,
    http_request: Request,
):
    client_ip = http_request.client.host if http_request.client else "unknown"
    _check_login_rate_limit(client_ip)

    configured_username = os.getenv("AUTOGRADER_USERNAME", "").strip()
    if not configured_username or not os.getenv("AUTOGRADER_PASSWORD_HASH", "").strip():
        raise HTTPException(
            status_code=503,
            detail="Instructor username/password are not configured.",
        )

    username_ok = secrets.compare_digest(
        request.username.encode("utf-8"),
        configured_username.encode("utf-8"),
    )
    password_ok = _verify_instructor_password(request.password)

    if not (username_ok and password_ok):
        _record_login_failure(client_ip)
        raise HTTPException(status_code=401, detail="Invalid instructor credentials.")

    secure_cookie = os.getenv("COOKIE_SECURE", "").lower() in {"1", "true", "yes"}
    response.set_cookie(
        "autograder_instructor_session",
        _create_ui_session_token(),
        max_age=1800,
        httponly=True,
        secure=secure_cookie,
        samesite="strict",
        path="/",
    )
    _clear_login_failures(client_ip)
    return {"status": "authenticated", "expires_in_seconds": 1800}


@app.post("/api/ui/logout")
def instructor_ui_logout(http_request: Request, response: Response):
    token = http_request.cookies.get("autograder_instructor_session")
    if _verify_ui_session_token(token):
        session_id = hashlib.sha256(token.encode("utf-8")).hexdigest()
        _clear_ui_submissions(session_id)
        _revoke_ui_session_token(token)

    secure_cookie = os.getenv("COOKIE_SECURE", "").lower() in {"1", "true", "yes"}
    response.delete_cookie(
        "autograder_instructor_session",
        httponly=True,
        secure=secure_cookie,
        samesite="strict",
        path="/",
    )
    return {"status": "logged_out"}


@app.post("/api/ui/preflight")
def instructor_ui_preflight(request: PreparationRequest, http_request: Request):
    """Run source-size and sandboxed compiler checks before Agent 1 is called."""
    _require_ui_session(http_request)
    source = request.source
    if request.demo_mode is True:
        from app.ai.demo_scenarios import select_demo_scenario

        try:
            scenario = (
                select_demo_scenario(request.demo_scenario_id)
                if request.demo_scenario_id
                else select_demo_scenario()
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail="Unknown Demo scenario.") from exc
        source = scenario["student"]

    preflight_result = preflight(source)
    compilation = (
        compile_c_source(source)
        if preflight_result.get("decision") == "continue"
        else {"status": "skipped", "message": "Source validation did not pass."}
    )
    return {
        "status": "completed",
        "preflight": preflight_result,
        "compilation": compilation,
        "agent1_started": False,
    }

@app.post("/api/ui/prepare")
def instructor_ui_prepare(request: PreparationRequest, http_request: Request):
    session_id = _require_ui_session(http_request)
    scenario = None
    if request.demo_mode is True:
        from app.ai.demo_scenarios import DemoScenarioProvider, select_demo_scenario

        try:
            scenario = (
                select_demo_scenario(request.demo_scenario_id)
                if request.demo_scenario_id
                else select_demo_scenario()
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail="Unknown Demo scenario.") from exc
        source = scenario["student"]
        problem_statement = scenario["statement"]
        provider = DemoScenarioProvider(scenario["scenario_id"])
        result = evaluate_submission(
            source=source,
            problem_statement=problem_statement,
            provider=provider,
        )
        result["demo_mode"] = True
        result["provider_mode"] = "demo_scenario"
        result["analysis_mode"] = "simulated"
        result["demo_simulation_notice"] = (
            "Agent responses are predefined and simulated. Compilation, input "
            "validation, C execution, generator execution, and benchmark timings are real."
        )
        if isinstance(result.get("reconstruction"), dict):
            result["reconstruction"]["analysis_mode"] = "simulated"
        fingerprint = result.get("assignment_spec_fingerprint")
        if (
            result.get("assignment_spec_status")
            == "draft_requires_instructor_confirmation"
            and isinstance(result.get("assignment_spec"), dict)
            and isinstance(fingerprint, str)
        ):
            result["assignment_spec_draft_token"] = _create_draft_token(fingerprint)
    else:
        if not request.source.strip():
            raise HTTPException(status_code=422, detail="Source must not be blank.")
        source = request.source
        problem_statement = request.problem_statement
        result = prepare_submission(
            request,
            x_preparation_key=os.getenv("PREPARATION_API_KEY", "").strip(),
        )

    if scenario is not None:
        result["demo_scenario_id"] = scenario["scenario_id"]
        result["demo_scenario_name"] = scenario["name"]

    if (
        result.get("assignment_spec_status")
        == "draft_requires_instructor_confirmation"
        and isinstance(result.get("assignment_spec"), dict)
        and isinstance(result.get("assignment_spec_draft_token"), str)
        and isinstance(result.get("assignment_spec_fingerprint"), str)
        and result.get("source_sha256")
        == hashlib.sha256(source.encode("utf-8")).hexdigest()
    ):
        record = {
            "source": source,
            "problem_statement": problem_statement,
            "demo_mode": scenario is not None,
            "scenario_id": scenario["scenario_id"] if scenario is not None else None,
            "demo_scenario_name": scenario["name"] if scenario is not None else None,
            "prepared_result": dict(result),
            "draft_spec": dict(result["assignment_spec"]),
            "draft_fingerprint": result["assignment_spec_fingerprint"],
            "draft_token": result["assignment_spec_draft_token"],
            "confirmed_spec": None,
            "approval_token": None,
            "references": None,
        }
        result["submission_id"] = _save_ui_submission(session_id, record)
    return result

@app.post("/api/ui/confirm-assignment")
def instructor_ui_confirm(request: UIConfirmRequest, http_request: Request):
    session_id = _require_ui_session(http_request)
    record = _get_ui_submission(session_id, request.submission_id)

    if request.instructor_approved is not True:
        raise HTTPException(status_code=403, detail="Explicit instructor approval is required.")
    if record.get("confirmed_spec") is not None:
        raise HTTPException(status_code=409, detail="This submission has already been approved.")

    confirmation = confirm_assignment(
        ConfirmAssignmentRequest(
            assignment_spec=record["draft_spec"],
            expected_fingerprint=record["draft_fingerprint"],
            draft_token=record["draft_token"],
            instructor_approved=True,
        ),
        x_instructor_key=os.getenv("INSTRUCTOR_CONFIRMATION_KEY", "").strip(),
    )
    record["confirmed_spec"] = confirmation["assignment_spec"]
    record["confirmed_fingerprint"] = confirmation["assignment_spec_fingerprint"]
    record["approval_token"] = confirmation["approval_token"]
    return {
        "status": confirmation["status"],
        "assignment_spec": confirmation["assignment_spec"],
        "assignment_spec_fingerprint": confirmation["assignment_spec_fingerprint"],
        "confirmation": confirmation["confirmation"],
    }


@app.post("/api/ui/generate-references")
def instructor_ui_generate_references(
    request: UIGenerateReferencesRequest,
    http_request: Request,
):
    session_id = _require_ui_session(http_request)
    record = _get_ui_submission(session_id, request.submission_id)
    if not record.get("confirmed_spec") or not record.get("approval_token"):
        raise HTTPException(status_code=403, detail="Instructor approval is required first.")
    if record.get("references") is not None:
        return record["references"]

    params = ReferenceGenerationRequest(
        assignment_spec=record["confirmed_spec"],
        expected_fingerprint=record["confirmed_fingerprint"],
        approval_token=record["approval_token"],
    )
    key = os.getenv("INSTRUCTOR_CONFIRMATION_KEY", "").strip()
    if record.get("demo_mode") is True:
        from app.ai.demo_scenarios import DemoScenarioProvider
        scenario_id = record.get("scenario_id")
        try:
            provider = DemoScenarioProvider(scenario_id)
        except (TypeError, ValueError, AIProviderError) as exc:
            raise HTTPException(status_code=409, detail="Pinned Demo scenario is unavailable.") from exc
        references = generate_references(
            params, x_instructor_key=key, provider=provider
        )
    else:
        references = generate_references(params, x_instructor_key=key)
    if record.get("demo_mode") is True:
        references["analysis_mode"] = "simulated"
        references["demo_scenario_id"] = record["scenario_id"]
        references["demo_scenario_name"] = record.get("demo_scenario_name")
    record["references"] = references
    return references

@app.post("/api/ui/generate-tests")
def instructor_ui_generate_tests(
    request: UIGenerateTestsRequest,
    http_request: Request,
):
    session_id = _require_ui_session(http_request)
    record = _get_ui_submission(session_id, request.submission_id)

    confirmed = record.get("confirmed_spec")
    if not isinstance(confirmed, dict) or not record.get("approval_token"):
        raise HTTPException(
            status_code=403,
            detail="Instructor approval is required before test generation.",
        )

    try:
        spec_data = dict(confirmed)
        spec_data["constraints"] = tuple(spec_data.get("constraints", ()))
        spec = AssignmentSpec(**spec_data)
        approved_schema = spec.to_dict().get("input_schema")
        if approved_schema is not None:
            from analyzers.structured_input_schema import StructuredIntegerInputSchema
            schema = StructuredIntegerInputSchema.from_dict(approved_schema)
            schema_data = approved_schema
        else:
            if (
                request.token_count is None
                or request.minimum is None
                or request.maximum is None
            ):
                raise ValueError(
                    "Legacy assignments require token_count, minimum and maximum."
                )
            if request.minimum > request.maximum:
                raise ValueError("Minimum input value cannot exceed maximum input value.")
            schema = IntegerInputSchema(
                token_count=request.token_count,
                minimum=request.minimum,
                maximum=request.maximum,
            )
            schema_data = {
                "token_count": request.token_count,
                "minimum": request.minimum,
                "maximum": request.maximum,
            }
    except (TypeError, ValueError) as exc:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid confirmed assignment or input schema: {exc}",
        ) from exc

    if not spec.confirmed:
        raise HTTPException(
            status_code=403,
            detail="The assignment specification is not confirmed.",
        )

    prepared = record.get("prepared_result") or {}
    risk_data = prepared.get("source_risks") or {}
    references = record.get("references") or {}
    demo_mode = record.get("demo_mode") is True
    random_count = request.random_count
    adversarial_count = min(request.adversarial_count, 10) if demo_mode else request.adversarial_count
    generation_request = {
        "random_seed": request.random_seed,
        "random_count": random_count,
        "random_distribution": request.random_distribution,
        "adversarial_seed": request.adversarial_seed,
        "adversarial_count": adversarial_count,
        "input_schema": schema_data,
        "assignment_spec_fingerprint": record.get("confirmed_fingerprint"),
    }
    generation_request_key = hashlib.sha256(
        json.dumps(generation_request, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    if (
        record.get("test_generation_request_key") == generation_request_key
        and isinstance(record.get("test_plans"), dict)
    ):
        # A repeated click/retry with identical settings must not repeat the two
        # paid Agent 3 calls. Changing any test-plan setting creates a new run.
        return record["test_plans"]

    result = generate_test_plans(
        source=record["source"], spec=spec, schema=schema,
        random_seed=request.random_seed, random_count=random_count,
        random_distribution=request.random_distribution,
        adversarial_seed=request.adversarial_seed, adversarial_count=adversarial_count,
        static_findings=risk_data.get("findings", []), reference_metadata=references,
    )

    if result.get("status") == "generated":
        # Agent 3A and 3B use the same approved Agent 1 specification,
        # Agent 2 references, input schema and submitted source.
        references = record.get("references") or {}
        # This is the exact approved schema (structured or legacy) used
        # for test generation and passed unchanged to both AI agents.
        agent3a = {"status": "skipped", "reason": "Reference solutions unavailable."}
        agent3b = {"status": "skipped", "reason": "Reference solutions unavailable."}

        if (
            isinstance(references, dict)
            and isinstance(references.get("brute_force"), dict)
            and isinstance(references.get("efficient"), dict)
            and references["brute_force"].get("code")
            and references["efficient"].get("code")
        ):
            if demo_mode:
                from app.ai.demo_scenarios import DemoScenarioProvider
                scenario_id = record.get("scenario_id")
                try:
                    provider = DemoScenarioProvider(scenario_id)
                except (TypeError, ValueError, AIProviderError) as exc:
                    raise HTTPException(status_code=409, detail="Pinned Demo scenario is unavailable.") from exc
                provider_error = None
            else:
                try:
                    provider = create_ai_provider()
                except AIProviderError as exc:
                    provider, provider_error = None, str(exc)
                else:
                    provider_error = None

            if provider is not None:
                agent3a = generate_agent3a_program(
                    provider, problem=confirmed, schema=schema_data,
                    references=references, student_source=record["source"],
                    max_cases=min(random_count, 100),
                )
                if agent3a.get("status") == "program_generated_unexecuted":
                    generated = execute_agent3a_program(
                        agent3a, seed=request.random_seed, schema=schema,
                        max_cases=min(random_count, 100),
                    )
                    if demo_mode and generated.get("status") == "generated":
                        from app.ai.demo_scenarios import validate_demo_input
                        if any(not validate_demo_input(scenario_id, item["input"])
                               for item in generated.get("inputs", [])):
                            generated = {"status": "generator_semantic_validation_failed", "inputs": []}
                    agent3a["generation"] = generated
                    agent3a["status"] = ("generated" if generated.get("status") == "generated"
                                          else generated.get("status", "generation_failed"))

                agent3b = analyze_agent3b_edges(
                    provider, problem=confirmed, schema=schema_data,
                    references=references, student_source=record["source"],
                )
                if agent3b.get("status") == "proposed_unvalidated":
                    validated = validate_agent3b_edges(agent3b, schema=schema)
                    if demo_mode and validated.get("cases"):
                        from app.ai.demo_scenarios import validate_demo_input
                        valid_cases = [case for case in validated["cases"]
                                       if validate_demo_input(scenario_id, case["input"])]
                        if len(valid_cases) != len(validated["cases"]):
                            validated = {**validated, "status": "partially_validated", "cases": valid_cases}
                    agent3b["validation_result"] = validated
                    agent3b["cases"] = validated.get("cases", [])
                    agent3b["status"] = validated.get("status", "validation_failed")
                    agent3b["validation"] = validated.get("validation", {})
            else:
                agent3a = {"status": "provider_error", "message": provider_error}
                agent3b = {"status": "provider_error", "message": provider_error}

        if demo_mode:
            for item in (agent3a, agent3b):
                item["analysis_mode"] = "simulated"
                item["scenario_id"] = record["scenario_id"]
            result["provider_mode"] = "demo_scenario"
            result["analysis_mode"] = "simulated"
            result["demo_scenario_id"] = record["scenario_id"]
            result["demo_scenario_name"] = record.get("demo_scenario_name")
            result["demo_simulation_notice"] = (
                "Agent 3 responses are predefined and simulated; generated inputs, "
                "schema checks, C runs, and benchmark timings are real."
            )
            generated_inputs = (agent3a.get("generation") or {}).get("inputs", [])
            adversarial_cases = agent3b.get("cases", [])
            if agent3a.get("status") == "generated" and agent3b.get("status") == "validated" and generated_inputs and adversarial_cases:
                result["random_tests"]["inputs"] = [case["input"] for case in generated_inputs]
                result["random_tests"]["count"] = len(generated_inputs)
                plan = result["adversarial_tests"]
                plan["cases"] = [{
                    "input": case["input"], "reason": case["rationale"],
                    "priority": "high", "source_trigger": "scenario_edge_case",
                    "expected_output": case.get("expected_output"),
                } for case in adversarial_cases]
                plan["case_count"] = len(plan["cases"])
            else:
                result["status"] = "partial_or_failed"
                result["demo_failure"] = "Scenario Agent 3 responses or validated inputs are incomplete."
        if mock_mode_enabled() and not demo_mode:
            agent3a["analysis_mode"] = "simulated"
            agent3b["analysis_mode"] = "simulated"
            result["provider_mode"] = "offline_mock"
            result["mock_mode_notice"] = (
                "Agent 3 proposals are simulated; generator execution, schema "
                "validation, benchmarking and C execution are real."
            )
        result["agent3a"] = agent3a
        result["agent3b"] = agent3b
        record["agent3a"] = agent3a
        record["agent3b"] = agent3b

        # Benchmark the three implementations on exactly the same validated
        # Agent 3A inputs, under one shared wall-clock execution window.
        agent3a_generation = agent3a.get("generation") or {}
        generated_cases = agent3a_generation.get("inputs", [])
        if (
            agent3a.get("status") == "generated"
            and isinstance(generated_cases, list)
            and generated_cases
            and isinstance(references, dict)
        ):
            brute = references.get("brute_force") or {}
            efficient = references.get("efficient") or {}
            if brute.get("code") and efficient.get("code"):
                agent3a_benchmark = benchmark_three_programs_parallel(
                    record["source"],
                    brute["code"],
                    efficient["code"],
                    generated_cases,
                    time_budget_seconds=2.0,
                )
            else:
                agent3a_benchmark = {
                    "status": "missing_reference_implementation"
                }
        else:
            agent3a_benchmark = {
                "status": "skipped",
                "reason": "No validated Agent 3A generated inputs are available.",
            }

        record["agent3a_benchmark"] = agent3a_benchmark
        result["agent3a_benchmark"] = agent3a_benchmark
        record["test_plans"] = result
        record["input_schema"] = schema_data

    if result.get("status") == "generated":
        record["test_plans"] = result
        record["input_schema"] = schema_data
        record["test_generation_request_key"] = generation_request_key

    return result


def _agent4_benchmark_evidence(benchmark):
    """Adapt measured student observations to the legacy reconciler format."""
    if not isinstance(benchmark, dict):
        return None

    student = (benchmark.get("batches") or {}).get("student") or {}
    chart = [
        {
            "input_size": point.get("input_size"),
            "runtime_seconds": point.get("runtime_seconds"),
        }
        for point in benchmark.get("chart_data", [])
        if isinstance(point, dict)
        and point.get("program") == "student"
        and isinstance(point.get("input_size"), int)
        and isinstance(point.get("runtime_seconds"), (int, float))
    ]

    failed_runs = sum(
        1 for item in student.get("results", [])
        if isinstance(item, dict)
        and item.get("execution_class") != "program_success"
    )

    return {
        "status": (
            "completed_with_execution_issues"
            if benchmark.get("status") != "completed"
            or student.get("status") != "completed"
            else "completed"
        ),
        "results": [{"failed_runs": failed_runs}],
        "chart_data": chart,
        "growth_observations": [],
        "evidence_source": "agent3a_student_measurements",
        "raw_three_program_benchmark_preserved": True,
        "limitations": [
            "Single-run observations are not medians.",
            "No growth trend is inferred from these observations.",
            "Input size is the actual number of whitespace-separated input tokens.",
        ],
    }


def _attach_agent4_complexity_graphs(analysis):
    """Evaluate AI-reported complexity notation with the bounded math engine."""
    if not isinstance(analysis, dict):
        return analysis
    ai = analysis.get("ai_analysis")
    if not isinstance(ai, dict):
        return analysis
    from analyzers.complexity_graph import generate_complexity_graph

    time = ai.get("time_complexity") or {}
    space = ai.get("space_complexity") or {}
    curves = {}
    for label, notation in (
        ("time_best_case", time.get("best_case")),
        ("time_average_case", time.get("average_case")),
        ("time_worst_case", time.get("worst_case")),
        ("space_auxiliary", space.get("auxiliary")),
        ("space_total", space.get("total")),
    ):
        if isinstance(notation, str) and notation.strip():
            curves[label] = generate_complexity_graph(notation)
    analysis["complexity_graphs"] = curves
    return analysis


@app.post("/api/ui/download-test-cases")
def instructor_ui_download_test_cases(
    request: UIExecuteTestsRequest,
    http_request: Request,
):
    session_id = _require_ui_session(http_request)
    record = _get_ui_submission(session_id, request.submission_id)

    agent3a = record.get("agent3a") or {}
    generation = agent3a.get("generation") or {}
    cases = generation.get("inputs") or []
    if agent3a.get("status") != "generated" or not cases:
        raise HTTPException(
            status_code=409,
            detail="No validated Agent 3A generated inputs are available.",
        )

    benchmark = record.get("agent3a_benchmark") or {}
    comparisons = benchmark.get("differential_comparisons") or []
    by_case = {
        item.get("case"): item
        for item in comparisons
        if isinstance(item, dict) and isinstance(item.get("case"), int)
    }

    archive = io.BytesIO()
    manifest = {
        "source": "Validated Agent 3A generated inputs",
        "expected_output_source": (
            "stdout from the brute-force reference implementation"
        ),
        "expected_outputs_are_certified": False,
        "note": (
            "Expected outputs are included only when the brute-force "
            "reference completed successfully. They are reference outputs, "
            "not a formal correctness certificate."
        ),
        "cases": [],
    }

    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as zf:
        for index, case in enumerate(cases, 1):
            if not isinstance(case, dict) or not isinstance(case.get("input"), str):
                continue

            folder = f"case_{index:03d}"
            zf.writestr(f"{folder}/input.txt", case["input"])
            comparison = by_case.get(index, {})
            brute = (comparison.get("outcomes") or {}).get("brute_force") or {}
            expected_available = (
                brute.get("execution_class") == "program_success"
                and isinstance(brute.get("stdout"), str)
            )

            if expected_available:
                zf.writestr(
                    f"{folder}/expected_output.txt",
                    brute["stdout"],
                )
                expected_status = "available_from_brute_force_reference"
            else:
                expected_status = "unavailable_reference_did_not_complete"

            manifest["cases"].append({
                "case": index,
                "input_size": case.get("input_size"),
                "distribution": case.get("distribution"),
                "expected_output": expected_status,
            })

        zf.writestr(
            "manifest.json",
            json.dumps(manifest, indent=2),
        )
        zf.writestr(
            "README.txt",
            "Each case_NNN folder contains input.txt and, when the "
            "brute-force reference completed successfully, expected_output.txt. "
            "Expected outputs are reference observations, not formally "
            "certified answers. See manifest.json.\n",
        )

    return Response(
        content=archive.getvalue(),
        media_type="application/zip",
        headers={
            "Content-Disposition":
                'attachment; filename="autograder-generated-test-cases.zip"'
        },
    )


def _grade_metric_snapshot_eligible(result: dict[str, Any], provider: Any) -> bool:
    """Only freeze metrics after every AI stage needed by the rubric returned usable output."""
    if provider is None:
        return False
    accepted_statuses = {
        "agent3a": {"generated"},
        "agent3b": {"validated", "partially_validated"},
        "complexity_analysis": {"analyzed", "inconclusive"},
        "mathematical_verification": {
            "counterexample_found", "proof_sketch", "inconclusive"
        },
        "code_quality": {"completed"},
    }
    for name, accepted in accepted_statuses.items():
        item = result.get(name)
        if not isinstance(item, dict) or item.get("status") not in accepted:
            return False

    # A nominally completed response can still omit required evidence. Do not
    # freeze missing AI ratings into a grade snapshot.
    scores = derive_metric_scores(result)
    if result["complexity_analysis"].get("status") == "analyzed" and scores.get("complexity") is None:
        return False
    if any(
        scores.get(metric) is None
        for metric in ("readability", "modularity", "design_originality")
    ):
        return False
    return True


def _grade_snapshot_analysis_identity(provider: Any, result: dict[str, Any]) -> dict[str, Any]:
    """Fingerprint the provider/model and prompt/schema implementation that produced metrics."""
    actual = provider
    seen = set()
    while hasattr(actual, "provider") and id(actual) not in seen:
        seen.add(id(actual))
        actual = actual.provider
    provider_name = type(actual).__name__ if actual is not None else "unavailable"
    model = getattr(actual, "model", None) if actual is not None else None
    if result.get("demo_mode"):
        provider_name = "demo_scenario"
        model = result.get("demo_scenario_id")

    root = BASE_DIR.parent
    analysis_files = (
        "analyzers/problem_reconstruction.py",
        "analyzers/reference_solutions.py",
        "analyzers/agent3_ai.py",
        "analyzers/complexity_analysis.py",
        "analyzers/mathematical_verification.py",
        "analyzers/code_quality.py",
        "app/metric_scoring.py",
        "app/grading.py",
        "app/ai/guardrails.py",
        "app/ai/deepseek_provider.py",
        "app/ai/gemini_provider.py",
    )
    digest = hashlib.sha256()
    for relative_path in analysis_files:
        path = root / relative_path
        digest.update(relative_path.encode("utf-8"))
        digest.update(b"\\0")
        digest.update(path.read_bytes())
        digest.update(b"\\0")
    return {
        "provider": provider_name,
        "model": model,
        "analysis_code_sha256": digest.hexdigest(),
        "demo_scenario_id": result.get("demo_scenario_id"),
    }


@app.post("/api/ui/execute-tests")
def instructor_ui_execute_tests(
    request: UIExecuteTestsRequest,
    http_request: Request,
):
    if os.getenv("LOCAL_CODE_EXECUTION_ENABLED", "").lower() not in {"1", "true", "yes"}:
        raise HTTPException(
            status_code=503,
            detail="Local code execution is disabled. Enable it only in a controlled development environment.",
        )

    if os.getenv("APP_ENV", "development").strip().lower() in {
        "production", "prod"
    }:
        raise HTTPException(
            status_code=403,
            detail="Code execution is prohibited in the production environment.",
        )

    session_id = _require_ui_session(http_request)
    record = _get_ui_submission(session_id, request.submission_id)

    if not record.get("confirmed_spec") or not record.get("approval_token"):
        raise HTTPException(status_code=403, detail="Instructor approval is required.")

    plans = record.get("test_plans")
    if not isinstance(plans, dict) or plans.get("status") != "generated":
        raise HTTPException(
            status_code=409,
            detail="Generate Agent 3 test plans before executing them.",
        )

    if record.get("execution_result") is not None:
        return record["execution_result"]

    prepared = record.get("prepared_result")
    if not isinstance(prepared, dict):
        raise HTTPException(status_code=409, detail="Prepared submission data is unavailable.")

    # Use the scenario pinned at submission creation. Demo must never
    # construct or contact a real AI provider.
    provider_error = None
    demo_mode = record.get("demo_mode") is True
    demo_scenario = None
    if demo_mode:
        from app.ai.demo_scenarios import DemoScenarioProvider, get_demo_scenario
        scenario_id = record.get("scenario_id")
        try:
            demo_scenario = get_demo_scenario(scenario_id)
            provider = DemoScenarioProvider(scenario_id)
        except (TypeError, ValueError, AIProviderError) as exc:
            raise HTTPException(status_code=409, detail="The Demo scenario pinned to this submission is unavailable.") from exc
    else:
        try:
            provider = create_ai_provider()
        except AIProviderError as exc:
            provider = None
            provider_error = str(exc)

    # Agent 3B: execute validated edge cases and retain every outcome.
    agent3b = record.get("agent3b") or {}
    edge_cases = agent3b.get("cases", [])
    references = record.get("references") or {}

    if edge_cases:
        implementations = {
            "student": record.get("source", ""),
            "brute_force": (
                (references.get("brute_force") or {}).get("code", "")
                if isinstance(references, dict) else ""
            ),
            "efficient": (
                (references.get("efficient") or {}).get("code", "")
                if isinstance(references, dict) else ""
            ),
        }

        edge_inputs = [case["input"] for case in edge_cases]
        edge_runs = {}
        for implementation, c_source in implementations.items():
            if isinstance(c_source, str) and c_source.strip():
                try:
                    edge_runs[implementation] = run_c_batch(
                        c_source, edge_inputs
                    )
                except Exception as exc:
                    edge_runs[implementation] = {
                        "status": "worker_error",
                        "message": f"{type(exc).__name__}: {exc}",
                        "results": [],
                    }
            else:
                edge_runs[implementation] = {
                    "status": "missing_implementation",
                    "results": [],
                }

        edge_comparisons = []
        for index, case in enumerate(edge_cases):
            outcomes = {}
            for name in ("student", "brute_force", "efficient"):
                batch = edge_runs[name]
                case_results = batch.get("results", [])
                if index < len(case_results):
                    item = case_results[index]
                    outcomes[name] = {
                        "execution_class": item.get("execution_class"),
                        "exit_code": item.get("exit_code"),
                        "stdout": item.get("stdout", ""),
                        "stderr": item.get("stderr", ""),
                        "run_seconds": item.get("run_seconds"),
                    }
                else:
                    outcomes[name] = {
                        "execution_class": batch.get("status"),
                        "exit_code": None,
                        "stdout": "",
                        "stderr": batch.get("message", ""),
                        "run_seconds": None,
                    }

            all_successful = all(
                outcomes[name]["execution_class"] == "program_success"
                for name in outcomes
            )
            outputs = [
                outcomes[name]["stdout"].strip()
                for name in ("student", "brute_force", "efficient")
            ]
            edge_comparisons.append({
                "case": index + 1,
                "input": case["input"],
                "rationale": case.get("rationale"),
                "targeted_implementation": case.get(
                    "targeted_implementation", case.get("target", [])
                ),
                "failure_hypothesis": case.get("failure_hypothesis"),
                "outcomes": outcomes,
                "outputs_agree": (
                    len(set(outputs)) == 1 if all_successful else None
                ),
            })

        all_three_present = all(
            edge_runs[name].get("status") in (
                "completed", "completed_with_execution_issues"
            )
            for name in ("student", "brute_force", "efficient")
        )
        agent3b_execution = {
            "status": (
                "completed" if all_three_present else "incomplete"
            ),
            "validated_case_count": len(edge_inputs),
            "implementations": edge_runs,
            "differential_comparisons": edge_comparisons,
            "all_three_agreed_cases": sum(
                item["outputs_agree"] is True
                for item in edge_comparisons
            ),
            "ai_hypotheses_are_not_failures_until_execution": True,
        }


    test_cases = [case.model_dump() for case in request.test_cases] if request.test_cases is not None else None
    if demo_mode and test_cases is None:
        test_cases = [
            {"input": case["input"], "expected_output": case["expected_output"]}
            for case in demo_scenario["edge_cases"]
        ]
    prepared_for_execution = dict(prepared)
    if isinstance(references, dict):
        prepared_for_execution["reference_solutions"] = references

    diagnostic_cases = test_cases or edge_cases
    if not diagnostic_cases:
        random_inputs = ((plans.get("agent3a") or {}).get("generation") or {}).get("inputs", [])
        diagnostic_cases = random_inputs
    memory_diagnostic_stdin = (
        diagnostic_cases[0].get("input", "")
        if diagnostic_cases and isinstance(diagnostic_cases[0], dict)
        else ""
    )

    result = evaluate_execution_evidence(
        source=record["source"],
        prepared_result=prepared_for_execution,
        test_cases=test_cases,
        run_memory_diagnostics=True,
        memory_diagnostic_stdin=memory_diagnostic_stdin,
        generated_test_plans=plans,
        provider=provider,
        complexity_benchmark=(
            _agent4_benchmark_evidence(
                record.get("agent3a_benchmark")
            )
            if isinstance(record.get("agent3a_benchmark"), dict)
            else record.get("complexity_benchmark")
        ),
        agent3b_execution=agent3b_execution if edge_cases else None,
        run_complexity_analysis=(
            isinstance(record.get("agent3a_benchmark"), dict)
            or isinstance(record.get("complexity_benchmark"), dict)
        ),
    )

    result["complexity_analysis"] = _attach_agent4_complexity_graphs(
        result.get("complexity_analysis")
    )

    if edge_cases:
        result["agent3b_execution"] = agent3b_execution
        record["agent3b_execution"] = agent3b_execution

    # Agent 6: final AI-led code quality review, after Agent 5.
    if provider is not None:
        result["code_quality"] = review_code_quality(
            record["source"],
            provider,
            context={
                "prepared_result": prepared,
                "execution_evidence": {
                    "execution_evidence_summary": result.get("execution_evidence_summary"),
                    "random_test_execution": result.get("random_test_execution"),
                    "adversarial_execution": result.get("adversarial_execution"),
                    "mathematical_verification": result.get("mathematical_verification"),
                },
            },
        )
    else:
        result["code_quality"] = {
            "status": "provider_error" if provider_error else "skipped",
            "review_type": "ai_led",
            "summary": "Agent 6 AI review was not run.",
            "strengths": [],
            "findings": [],
            "limitations": [
                provider_error or "No AI provider is configured."
            ],
        }

    if provider is None:
        reconstruction = prepared.get("reconstruction") or {}
        candidates = reconstruction.get("candidates", [])
        if len(candidates) == 1:
            result["mathematical_verification"] = {
                "status": "provider_error" if provider_error else "skipped",
                "formally_verified": False,
                "message": (
                    provider_error
                    or "No AI provider is configured; mathematical proof was skipped."
                ),
            }

    for evidence_key in (
        "agent3a", "agent3b", "agent3a_benchmark", "agent3b_execution"
    ):
        if evidence_key in record:
            result[evidence_key] = record[evidence_key]

    if demo_mode:
        result["demo_mode"] = True
        result["demo_scenario_id"] = record["scenario_id"]
        result["demo_scenario_name"] = record.get("demo_scenario_name")
        result["provider_mode"] = "demo_scenario"
        result["demo_simulation_notice"] = (
            "AI agent responses are predefined and simulated. Compilation, "
            "test execution, reference checks, and benchmark timings are real."
        )
        result["analysis_mode"] = "simulated"
        result["reference_solutions"] = references
        result["references"] = references
        for key in ("reconstruction", "complexity_analysis", "mathematical_verification", "code_quality"):
            if isinstance(result.get(key), dict):
                result[key]["analysis_mode"] = "simulated"
                result[key]["scenario_id"] = record["scenario_id"]
    elif mock_mode_enabled():
        result["provider_mode"] = "offline_mock"
        result["mock_mode_notice"] = (
            "AI analyses are simulated. All reported compilation, validation "
            "and program execution evidence comes from the real local pipeline."
        )
        for key in ("complexity_analysis", "mathematical_verification", "code_quality"):
            if isinstance(result.get(key), dict):
                result[key]["analysis_mode"] = "simulated"
    # Recompute only after Agent 4/5/6 evidence is attached. AI-derived rubric
    # metrics are first-writer snapshots keyed to source, approved spec and rules.
    spec_fingerprint = (
        result.get("assignment_spec_fingerprint")
        or (record.get("confirmed_spec") or {}).get("fingerprint")
        or (record.get("prepared_result") or {}).get("assignment_spec_fingerprint")
        or "unfingerprinted-spec"
    )
    rules_digest = hashlib.sha256(DEFAULT_GRADING_RULES.read_bytes()).hexdigest()
    analysis_identity = _grade_snapshot_analysis_identity(provider, result)
    snapshot_key = hashlib.sha256(json.dumps({
        "snapshot_schema": "complete-grade-metrics-v2",
        "source_sha256": hashlib.sha256(record["source"].encode("utf-8")).hexdigest(),
        "assignment_spec_fingerprint": spec_fingerprint,
        "grading_rules_sha256": rules_digest,
        "analysis_identity": analysis_identity,
    }, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    current_metric_scores = derive_metric_scores(result)
    stored_metric_scores = _persistent_get_grade_metrics(snapshot_key)
    reused_grade_snapshot = isinstance(stored_metric_scores, dict)
    snapshot_eligible = _grade_metric_snapshot_eligible(result, provider)
    if reused_grade_snapshot:
        metric_scores = stored_metric_scores
        snapshot_persisted = True
        snapshot_status = "reused"
    elif snapshot_eligible:
        metric_scores = _persistent_save_grade_metrics(snapshot_key, current_metric_scores)
        snapshot_persisted = True
        snapshot_status = "saved"
    else:
        # A transient provider/schema error must not freeze missing AI scores.
        # Recheck once in case another worker stored a complete vector concurrently.
        stored_metric_scores = _persistent_get_grade_metrics(snapshot_key)
        if isinstance(stored_metric_scores, dict):
            metric_scores = stored_metric_scores
            reused_grade_snapshot = True
            snapshot_persisted = True
            snapshot_status = "reused"
        else:
            metric_scores = current_metric_scores
            snapshot_persisted = False
            snapshot_status = "not_saved_incomplete_evidence"
    result["metric_scores"] = metric_scores
    result["grading"] = grade_submission(result, metric_scores)
    provenance = result["grading"].setdefault("reproducibility", {})
    provenance["grade_snapshot_key"] = snapshot_key
    provenance["grade_snapshot_reused"] = reused_grade_snapshot
    provenance["grade_snapshot_persisted"] = snapshot_persisted
    provenance["grade_snapshot_status"] = snapshot_status
    provenance["grade_snapshot_backend"] = _grade_snapshot_backend()
    provenance["grade_snapshot_policy"] = (
        "Complete AI metric vectors are pinned by source, approved specification, grading rules, provider/model, and analysis implementation. Incomplete provider results are shown but are not frozen."
    )
    record["execution_result"] = result
    return result


@app.post("/api/ui/benchmark-complexity")
def instructor_ui_benchmark_complexity(
    request: UIComplexityBenchmarkRequest,
    http_request: Request,
):
    if os.getenv("LOCAL_CODE_EXECUTION_ENABLED", "").lower() not in {
        "1", "true", "yes"
    }:
        raise HTTPException(
            status_code=503,
            detail="Local code execution is disabled. Enable it only in a controlled development environment.",
        )

    if os.getenv("APP_ENV", "development").strip().lower() in {
        "production", "prod"
    }:
        raise HTTPException(
            status_code=403,
            detail="Code execution is prohibited in the production environment.",
        )

    session_id = _require_ui_session(http_request)
    record = _get_ui_submission(session_id, request.submission_id)

    if not record.get("confirmed_spec") or not record.get("approval_token"):
        raise HTTPException(status_code=403, detail="Instructor approval is required.")

    cases = [
        {"input_size": case.input_size, "input": case.input}
        for case in request.benchmark_cases
    ]

    result = benchmark_complexity(
        source=record["source"],
        benchmark_cases=cases,
        repetitions=request.repetitions,
    )

    if result.get("status") == "invalid_request":
        raise HTTPException(
            status_code=422,
            detail=result.get("message", "Invalid benchmark request."),
        )

    # Store separately from execution and grading evidence.
    record["complexity_benchmark"] = result
    return result


@app.post("/api/ui/generate-report")
def instructor_ui_generate_report(
    request: UIPDFReportRequest,
    http_request: Request,
):
    session_id = _require_ui_session(http_request)
    record = _get_ui_submission(session_id, request.submission_id)

    execution = record.get("execution_result")
    if not isinstance(execution, dict):
        raise HTTPException(
            status_code=409,
            detail="Run the evaluation workflow before generating the final PDF report.",
        )

    prepared = record.get("prepared_result") or {}
    evaluation = {**prepared, **execution}

    # Reuse the Agent 6 result produced in sequence after Agent 5.
    # Do not silently substitute the legacy heuristic report.
    evaluation["code_quality"] = execution.get("code_quality") or {
        "status": "unavailable",
        "review_type": "ai_led",
        "summary": "Agent 6 review was not present in the execution results.",
        "findings": [],
        "limitations": ["The AI-led Agent 6 review was not completed."],
    }

    benchmark = record.get("complexity_benchmark")
    if isinstance(benchmark, dict):
        evaluation["complexity_benchmark"] = benchmark

    temp = tempfile.NamedTemporaryFile(suffix=".pdf", delete=False)
    report_path = Path(temp.name)
    temp.close()

    try:
        generate_pdf_report(evaluation, report_path)
    except Exception:
        report_path.unlink(missing_ok=True)
        raise

    return FileResponse(
        report_path,
        media_type="application/pdf",
        filename="autograder-evaluation-report.pdf",
        background=BackgroundTask(report_path.unlink, missing_ok=True),
    )


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

import time
from collections import defaultdict, deque
import threading
import hashlib
from pathlib import Path
import os
import secrets

from fastapi import FastAPI, HTTPException, Header
from pydantic import BaseModel, Field

from analyzers.source_risks import analyze_source_risks
from analyzers.complexity_estimator import estimate_complexity
from app.orchestrator import evaluate_submission
from fastapi.responses import HTMLResponse
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

    return evaluate_submission(
        source=request.source,
        problem_statement=request.problem_statement,
    )


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

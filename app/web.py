from pathlib import Path

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from analyzers.source_risks import analyze_source_risks
from analyzers.complexity_estimator import estimate_complexity
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

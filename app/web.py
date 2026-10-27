from pathlib import Path

from fastapi import FastAPI
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

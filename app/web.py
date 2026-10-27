from fastapi import FastAPI

app = FastAPI(
    title="AutoGrader API",
    description="Rule-driven evaluator for C programs",
    version="0.1.0",
)


@app.get("/health")
def health():
    return {
        "status": "ok",
        "service": "autograder",
        "code_execution_enabled": False,
    }

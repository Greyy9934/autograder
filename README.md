# AutoGrader: A Rule-Driven Evaluator for C Programs

AutoGrader evaluates C submissions using compiler/runtime checks, configurable grading rules, test cases, static heuristics, optional memory diagnostics, and AI-assisted analysis.

## Features
- C compilation and execution with Bubblewrap isolation and resource limits.
- Preflight and source-risk analysis.
- Test-case evaluation and candidate reference solutions.
- Differential testing, edge-case analysis, and complexity estimation.
- Optional memory diagnostics and AI-assisted problem reconstruction.
- Rule-driven scoring with unavailable metrics excluded and weights renormalized.

## Requirements
- Python 3.12 or compatible version, GCC, Bubblewrap, and Linux namespace support.
- Valgrind for the optional Valgrind diagnostics.

## Installation
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt -r requirements-dev.txt
```

## Configuration
Copy `.env.example` to `.env` and set `GEMINI_API_KEY` and optionally `GEMINI_MODEL`. Never commit `.env` or expose API keys.

## Tests
```bash
python -m pytest -q
git diff --check
```

## Main Entry Point
Use `evaluate_submission()` from `app.orchestrator`. See `reports/final_report.md` for architecture, examples, limitations, and status.

## Security Notice
This is a development prototype, not a security-certified public sandbox. Do not expose the runner directly to the public internet without further isolation review and adversarial testing.

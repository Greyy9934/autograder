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
Copy .env.example to .env. The default provider is Gemini; set GEMINI_API_KEY and optionally GEMINI_MODEL. DeepSeek is opt-in: set AI_PROVIDER=deepseek, DEEPSEEK_API_KEY, and DEEPSEEK_MODEL=deepseek-flash. Keep AUTOGRADER_MOCK_MODE=1 for no-charge workflow testing; turn it off only when intentionally enabling a paid provider.

Set NEON_DATABASE_URL to the pooled connection string from Neon for persistent UI state, grade snapshots, and the shared AI request budget. Production refuses to fall back to local SQLite. AI_DAILY_REQUEST_CREDITS defaults to 7 (one provider call per credit, enough for one standard seven-call evaluation per UTC day). DeepSeek defaults to DEEPSEEK_MAX_TOKENS=4096 and low reasoning effort; automatic retries are disabled for both paid providers so a reserved credit permits at most one provider request. Identical repeated Agent 3 requests are served from the existing submission state. This request cap is not a monetary cap; configure a provider-side spending limit as well. Never commit .env or expose credentials.

## Offline workflow simulation

Set `AUTOGRADER_MOCK_MODE=1` in `.env` to exercise the instructor workflow without
an AI provider or paid API calls. The mock provider supplies deterministic,
explicitly labelled simulated responses for Agents 1–6. Preflight, GCC
compilation, approved-schema validation, Agent 3A generator execution,
benchmarking, differential C execution, and report generation remain on the
normal local execution path. Agent 5/6 mock responses are not proofs or actual
AI code reviews. Mock mode is rejected when `APP_ENV=production`.

Set `AUTOGRADER_MOCK_MODE=0` (or remove it) to return to the configured provider.

## Tests
```bash
python -m pytest -q
git diff --check
```

## Main Entry Point
Use `evaluate_submission()` from `app.orchestrator`. See `reports/final_report.md` for architecture, examples, limitations, and status.

## Security Notice
This is a development prototype, not a security-certified public sandbox. The production API endpoint /api/ui/execute-tests is intentionally disabled; a live provider key alone cannot enable complete hosted grading. Do not expose the runner directly to the public internet without further isolation review and adversarial testing.

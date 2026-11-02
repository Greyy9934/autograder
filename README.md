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

Set NEON_DATABASE_URL to the pooled connection string from Neon for persistent UI state, grade snapshots, and the shared AI request budget. Production refuses to fall back to local SQLite. AI_DAILY_REQUEST_CREDITS defaults to 350 (one provider call per credit, enough for 50 standard seven-call evaluations per UTC day). This is an application request allowance, not a dollar cap; the provider bills actual input and output tokens. DeepSeek uses per-agent output ceilings totaling 53,248 tokens for one standard seven-call workflow: reconstruction 4,096; reference solutions 12,288; random generator 8,192; edge-case analysis 12,288; complexity 4,096; mathematical verification 8,192; code quality 4,096. The app caps any one completion at 16,384 tokens. These are ceilings chosen by response shape, not targets; DeepSeek currently documents a much higher model maximum, so the app keeps its own moderate safety limit. Response schemas still bound generator size, edge-case count, and review detail. These are maximum completion-token ceilings, not targets; prompts and response schemas constrain unnecessary output. The app blocks DeepSeek requests whose serialized input exceeds 48 KiB before reserving a credit or making a provider call. Requests fail closed if an unmapped DeepSeek task is introduced. Reasoning effort is low for analysis tasks and disabled for the code-quality task; automatic retries are disabled for both paid providers so a reserved credit permits at most one provider request. Request logs record actual token usage, the output ceiling, reasoning-token usage when supplied, and the provider finish reason, so truncation can be distinguished from other invalid responses. Identical repeated Agent 3 requests are served from the existing submission state. Request-credit and token ceilings are not monetary spending limits; configure a provider-side spending limit as well. Never commit .env or expose credentials.

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

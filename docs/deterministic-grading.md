# Deterministic grading

The final grade is a weighted average of evidence-backed metrics. The rubric is versioned in `rules/grading.json`; v2.0 weights are correctness 45%, edge-case agreement 15%, mathematical verification 15%, complexity assessment 10%, readability 5%, modularity 5%, and design originality 5%.

For included metrics, the overall score is `round(sum(score_i * weight_i) / sum(included weights), 2)`. Unavailable metrics are omitted and the remaining weights are renormalized. Grade bands are A (90-100), B (80-89.99), C (70-79.99), D (60-69.99), and F (below 60). A grade remains provisional when the approved problem or determinate test evidence is incomplete.

## Evidence mappings

- **Correctness:** determinate explicit-test pass rate plus random differential cases where the brute-force reference completed. A student timeout, a reference timeout, or infrastructure failure is inconclusive and excluded.
- **Edge cases:** determinate Agent 3B student-vs-brute-force agreement rate.
- **Mathematical verification:** a validated AI `proof_sketch` maps to 75, a concrete constraint-valid `counterexample_found` maps to 0, a formally verified result maps to 100, and `inconclusive` is unavailable. AI is instructed not to return a numeric grade.
- **Complexity fit:** Agent 4 must return an integer 0-4 with exact source-line evidence. The application maps it to `rating * 25`. The fixed anchors are 0 contradicted, 1 major gap, 2 plausible with a meaningful gap, 3 supported with minor omissions, and 4 complete, source-supported analysis and reconciliation.
- **Agent 6:** readability, modularity, and design originality each use an integer 0-4 with exact quoted source-line evidence. The application maps each to `rating * 25`. Anchors: 0 deficient, 1 weak, 2 adequate, 3 strong, 4 exceptional. AI-supplied numeric scores are rejected; only the anchored ratings are accepted.

Ratings require exact source-line matches and a non-empty rationale. Failed citations make that dimension unavailable. Demo and offline-mock ratings are explicitly simulated.

## Repeatability

Complete metric snapshots are keyed by source SHA-256, approved specification fingerprint, grading-rules SHA-256, and snapshot schema version. The first complete metric vector wins, including unavailable dimensions, so later random or AI-generated cases cannot silently change a repeat submission grade. Current-run execution observations remain available for audit, while the scorecard marks when a stored grade snapshot was reused. A rubric or snapshot schema change creates a new evaluation key.

In production, `NEON_DATABASE_URL` (or `DATABASE_URL`) is required and Neon PostgreSQL stores submissions, session revocations, and immutable grade snapshots. Local development may use SQLite; it is never the production fallback. Render's `/health` check verifies that the configured database accepts connections and can answer a query. No submitted source code is stored in the grade-snapshot table, only a hash key and normalized metric values; submission workflow records are stored in the submissions table and expire after the configured TTL.

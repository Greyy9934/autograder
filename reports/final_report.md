# AutoGrader: A Rule-Driven Evaluator for C Programs

## 1. Abstract

AutoGrader is a modular system for evaluating C-program submissions.
It combines conventional compiler and runtime checks, rule-driven scoring,
program-analysis heuristics, differential testing, memory diagnostics,
and optional AI-assisted analysis.

The design separates deterministic evidence from AI-generated suggestions.
The goal is reproducible grading with actionable feedback, not an
unsupported claim that any single test or model can prove correctness.

## 2. Objectives

- Compile and execute C submissions with resource limits.
- Reject invalid or unsuitable submissions before deeper analysis.
- Support externally configurable grading weights and policies.
- Generate candidate reference solutions and validate them where possible.
- Identify likely edge cases and compare programs on shared inputs.
- Provide optional memory-safety diagnostics.
- Produce structured reports with explicit limitations and uncertainty.
- Keep AI providers replaceable through a provider-independent interface.

## 3. System Architecture

The implementation is organized into five logical analysis roles, supported
by conventional program-analysis and execution components.

### 3.1 Problem Reconstruction Agent

Examines the source and any supplied problem statement or tests. It can
propose candidate interpretations, but ambiguity must be surfaced rather
than silently resolved. Missing constraints are not treated as known facts.

### 3.2 Reference Solution Agent

Produces brute-force and efficient candidate solutions when the problem
interpretation is sufficiently clear. Generated references are not trusted
until they have been checked.

### 3.3A Random Test Generation

Generates reproducible candidate inputs using a seed and configured bounds.
Differential testing compares outputs from two programs on the same inputs.
Generic integer-list inputs are only appropriate for problems whose input
format matches that structure.

### 3.3B Targeted Edge-Case Analysis

Examines potential boundary conditions such as minimum and maximum values,
duplicates, ordering, index boundaries, and overflow risks. Suggested
cases are not automatically proof that a submission handles them correctly.

### 3.4 Mathematical Verification

Attempts an independent correctness argument or searches for counterexamples.
An AI-generated proof sketch is not a machine-checked proof. Results must
distinguish a counterexample, a proof sketch, and an inconclusive analysis.

### 3.5 Code Quality and Explanation

Supports readability, modularity, maintainability, and explanatory feedback.
Similarity or originality indicators are advisory and must not be treated as
proof of plagiarism.

### Supporting Components

- **Preflight and source-risk checks:** perform early screening.
- **C runner:** compiles and executes submissions under configured limits.
- **Complexity estimator:** provides heuristic source-based estimates.
- **Memory diagnostics:** optionally use sanitizers or Valgrind.
- **Orchestrator:** coordinates analysis and records unavailable results.
- **Grading engine:** applies external rules to eligible evidence.
- **AI provider interface:** isolates provider-specific request handling.

## 4. Processing Workflow

1. Receive source code and optional problem statement and test cases.
2. Validate the request and run preflight checks.
3. Perform source-risk analysis and estimate complexity.
4. Reconstruct the problem when an AI provider is available.
5. Request clarification if multiple plausible interpretations remain.
6. Generate candidate reference solutions for a sufficiently clear problem.
7. Validate references where suitable test inputs are available.
8. Run eligible edge-case, differential, mathematical, and memory analyses.
9. Convert eligible evidence into metric scores.
10. Apply grading rules and produce a structured result.

Failures in optional AI analysis should be reported as unavailable or
inconclusive. They must not be silently converted into successful evidence.

## 5. Rule-Driven Grading

The current rules are stored in `rules/grading.json`.

| Metric | Weight |
|---|---:|
| Correctness | 50 |
| Edge cases | 10 |
| Code quality | 10 |
| Complexity | 10 |
| Memory safety | 10 |
| Readability | 5 |
| Originality review | 5 |
| **Total** | **100** |

The grading engine validates the configuration, excludes unavailable
metrics, and renormalizes eligible weights according to policy.

Correctness requires successful preflight, an unambiguous selected problem,
and explicit completed test-case evaluation. A compilation success alone
does not establish correctness.

The current deterministic scoring implementation is intentionally
conservative: metrics without validated scoring evidence remain unavailable
rather than receiving invented scores.

## 6. Algorithms and Techniques

### Differential Testing

For each selected input, execute both candidate programs and compare their
outputs. Report mismatches with the relevant input and execution results.
This technique is useful only when the reference implementation is trusted
enough for the intended comparison.

### Reference Validation

Compile and run candidate reference programs on supplied cases. Agreement
between two references is useful evidence but does not prove that either
implements the specification correctly.

### Complexity Estimation

Inspect source patterns and available evidence to estimate likely complexity.
Static estimates can be misleading when control flow, input constraints, or
library behavior are not fully understood. Empirical timing is a separate
measurement and should be reported separately.

### Memory Diagnostics

Use supported runtime diagnostics to detect certain invalid accesses,
undefined behaviors, leaks, and related defects. Tool availability and
coverage vary. A clean run does not prove memory safety.

## 7. Security and Resource Controls

The current development runner uses Bubblewrap namespaces, separate
compilation and execution environments, process-group cleanup, execution
timeouts, output caps, and resource limits. Network isolation and selected
filesystem restrictions have been smoke-tested.

Observed development tests include:

- Infinite-loop termination near the configured runtime limit.
- Output truncation at 1 MiB.
- Failure of an oversized memory allocation under the configured limit.
- A repeated-fork test that stopped when process creation failed.
- A child-process cleanup regression test that passed.
- A full test suite that passed after the recent runner changes.

These results are development smoke tests, not a security certification.
The current setup must not be described as safe for arbitrary hostile code
on a public multi-tenant service without further adversarial testing and
stronger isolation review.

## 8. Example Scenarios

### Example A: Incorrect arithmetic result

A submission compiles but produces an output different from a trusted
reference on a supplied input. The report can identify the failing input,
expected output, and actual output, provided the reference is validated.

### Example B: Boundary-condition defect

A program handles ordinary inputs but fails on a permitted minimum-size
input or repeated values. Targeted cases and differential testing can expose
the defect if the input format and constraints are known.

### Example C: Infinite loop

A program does not finish within the configured time limit. The runner
terminates the execution and reports a timeout rather than waiting forever.

### Example D: Suspected similarity

A similarity check identifies overlap with another submission or known
source. The result is a review signal only. Legitimate common algorithms,
templates, and standard idioms can also produce similarity.

These are illustrative scenarios, not claims that specific student
submissions have already produced these results.

## 9. Usefulness

- Automates repetitive compilation and execution checks.
- Makes grading policy editable without changing the scoring code.
- Produces reproducible test inputs when a seed is fixed.
- Can identify concrete mismatches instead of giving only a numeric grade.
- Separates measured results from heuristic or AI-generated judgments.
- Helps instructors focus review on suspicious or uncertain cases.

## 10. Limitations

- Tests cover only selected inputs and cannot prove general correctness.
- Problem reconstruction may be ambiguous or incorrect.
- Generated references may contain defects.
- Generic edge cases may not match the actual specification.
- Static complexity estimates are heuristic.
- Sanitizers and Valgrind detect only certain classes of defects.
- AI outputs can be incorrect, inconsistent, unavailable, or delayed.
- Similarity is not proof of plagiarism or AI authorship.
- Current deterministic scoring supports only metrics with sufficient
  validated evidence; not every configured metric necessarily receives
  a score in every run.
- The sandbox has not been security-certified for public hostile workloads.
- A dependable public execution service may require paid compute and
  stronger isolation than a free hosting tier provides.

## 11. Testing and Verification

The latest reported full regression run passed 149 tests and 11 subtests.
The child-process cleanup regression test also passed independently.
These results establish that the tested cases passed in the development
environment; they do not establish production reliability or security.

Before submission, rerun the test suite from the final commit and retain
the actual terminal output. Record the exact commit and environment used.

## 12. Deployment Status

The application is currently developed in a local Linux environment under
WSL. Public deployment is not yet complete. The live Gemini request has
not been verified successfully; one attempt exceeded a 25-second external
timeout. An HTTP response from Google's API hostname confirms host
reachability only, not successful model generation.

Before public deployment:

1. Verify a live AI request with a bounded timeout.
2. Review sandbox escape and resource-exhaustion risks.
3. Keep API keys in server-side environment variables.
4. Never expose secrets in frontend code, logs, reports, or Git.
5. Run the full test suite in the deployment environment.
6. Configure request limits, logging, and operational error handling.
7. Confirm hosting limits and costs before accepting public submissions.

## 13. Conclusion

AutoGrader provides a modular foundation for rule-driven C-program
evaluation, combining conventional execution evidence with optional
AI-assisted analysis. Its strongest design principle is separation of
evidence from judgment: deterministic checks support reproducibility,
while uncertain AI and heuristic outputs remain advisory.

The implementation should be presented as a working development prototype
until live AI behavior, production deployment, and security isolation have
been independently verified.

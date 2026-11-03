"""Per-agent DeepSeek completion budgets for one standard grading workflow."""
# In plain terms: This file sets a reasonable maximum answer size for each agent. The limits are ceilings, not a bill or a promise to use every token.

from types import MappingProxyType

from app.ai.base import AIProviderError


TASK_RECONSTRUCTION = "Reconstruct the intended programming problem."
TASK_REFERENCES = "Generate candidate C reference solutions."
TASK_RANDOM_GENERATOR = "Design a problem-specific randomized test generator for Agent 3A."
TASK_EDGE_CASES = "Discover concrete adversarial edge cases for the submitted C program."
TASK_COMPLEXITY = "Perform AI-first time and space complexity analysis."
TASK_MATHEMATICAL_PROOF = "Produce a mathematical correctness proof or concrete counterexample."
TASK_CODE_QUALITY = "Perform the final AI-led code quality and maintainability review."

# Per-task completion ceilings provide headroom for complete structured answers.
# They are maxima, not reservations: billing follows provider-reported usage.
AGENT_OUTPUT_TOKEN_CAPS = MappingProxyType({
    TASK_RECONSTRUCTION: 8192,
    TASK_REFERENCES: 14336,
    TASK_RANDOM_GENERATOR: 10240,
    TASK_EDGE_CASES: 14336,
    TASK_COMPLEXITY: 8192,
    TASK_MATHEMATICAL_PROOF: 10240,
    TASK_CODE_QUALITY: 6144,
})
# Sum of seven per-request ceilings only; this is not pre-reserved or pre-billed.
PER_SUBMISSION_OUTPUT_TOKEN_BUDGET = 71_680
MAX_OUTPUT_TOKENS_PER_REQUEST = 16384
MAX_PROVIDER_INPUT_JSON_BYTES = 48 * 1024

# Preserve low reasoning for algorithmic work; the final code/proof must still
# fit inside the explicit per-agent completion cap. Agent 6 is a bounded review.
TASK_REASONING_EFFORT = MappingProxyType({
    TASK_RECONSTRUCTION: "low",
    TASK_REFERENCES: "low",
    TASK_RANDOM_GENERATOR: "low",
    TASK_EDGE_CASES: "low",
    TASK_COMPLEXITY: "low",
    TASK_MATHEMATICAL_PROOF: "low",
    TASK_CODE_QUALITY: "none",
})

if sum(AGENT_OUTPUT_TOKEN_CAPS.values()) != PER_SUBMISSION_OUTPUT_TOKEN_BUDGET:
    raise RuntimeError("Per-agent output caps must sum to the submission budget.")
if any(
    not 1 <= cap <= MAX_OUTPUT_TOKENS_PER_REQUEST
    for cap in AGENT_OUTPUT_TOKEN_CAPS.values()
):
    raise RuntimeError("An agent output cap is outside the provider limit.")


def reasoning_effort_for_task(task: str) -> str:
    """Return the deliberately selected DeepSeek reasoning mode for a task."""
    # In simple terms: Return the deliberately selected DeepSeek reasoning mode for a task.
    # What the inputs mean:
    # - task: the task used for this step.
    # What it gives back: It returns text.
    try:
        return TASK_REASONING_EFFORT[task]
    except (KeyError, TypeError) as exc:
        raise AIProviderError(
            "No DeepSeek reasoning policy is configured for this agent.",
            category="configuration_error",
        ) from exc


def output_token_cap_for_task(task: str) -> int:
    """Return the cap for a known task; reject unmapped calls rather than guess."""
    # In simple terms: Return the cap for a known task; reject unmapped calls rather than guess.
    # What the inputs mean:
    # - task: the task used for this step.
    # What it gives back: It returns the int result.
    try:
        return AGENT_OUTPUT_TOKEN_CAPS[task]
    except (KeyError, TypeError) as exc:
        raise AIProviderError(
            "No DeepSeek output-token allocation is configured for this agent.",
            category="configuration_error",
        ) from exc

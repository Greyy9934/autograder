"""Per-agent DeepSeek completion budgets for one standard grading workflow."""

from types import MappingProxyType

from app.ai.base import AIProviderError


TASK_RECONSTRUCTION = "Reconstruct the intended programming problem."
TASK_REFERENCES = "Generate candidate C reference solutions."
TASK_RANDOM_GENERATOR = "Design a problem-specific randomized test generator for Agent 3A."
TASK_EDGE_CASES = "Discover concrete adversarial edge cases for the submitted C program."
TASK_COMPLEXITY = "Perform AI-first time and space complexity analysis."
TASK_MATHEMATICAL_PROOF = "Produce a mathematical correctness proof or concrete counterexample."
TASK_CODE_QUALITY = "Perform the final AI-led code quality and maintainability review."

# Completion-token limits sum to the previous 7 x 4096 workflow allowance.
AGENT_OUTPUT_TOKEN_CAPS = MappingProxyType({
    TASK_RECONSTRUCTION: 3072,
    TASK_REFERENCES: 8192,
    TASK_RANDOM_GENERATOR: 4096,
    TASK_EDGE_CASES: 3072,
    TASK_COMPLEXITY: 2048,
    TASK_MATHEMATICAL_PROOF: 6144,
    TASK_CODE_QUALITY: 2048,
})
PER_SUBMISSION_OUTPUT_TOKEN_BUDGET = 28_672
MAX_OUTPUT_TOKENS_PER_REQUEST = 8192

if sum(AGENT_OUTPUT_TOKEN_CAPS.values()) != PER_SUBMISSION_OUTPUT_TOKEN_BUDGET:
    raise RuntimeError("Per-agent output caps must sum to the submission budget.")
if any(
    not 1 <= cap <= MAX_OUTPUT_TOKENS_PER_REQUEST
    for cap in AGENT_OUTPUT_TOKEN_CAPS.values()
):
    raise RuntimeError("An agent output cap is outside the provider limit.")


def output_token_cap_for_task(task: str) -> int:
    """Return the cap for a known task; reject unmapped calls rather than guess."""
    try:
        return AGENT_OUTPUT_TOKEN_CAPS[task]
    except (KeyError, TypeError) as exc:
        raise AIProviderError(
            "No DeepSeek output-token allocation is configured for this agent.",
            category="configuration_error",
        ) from exc

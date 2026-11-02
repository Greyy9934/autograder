'''Explicit offline provider for the instructor workflow.

AI-shaped responses are deterministic simulations. Compilation, schema
validation, generated-input execution, benchmarking, and C execution remain real.
'''
from __future__ import annotations

import json
import random
from copy import deepcopy
from typing import Any

from app.ai.mock_scenarios import get_scenario
from app.ai.output_budget import (
    TASK_CODE_QUALITY,
    TASK_COMPLEXITY,
    TASK_EDGE_CASES,
    TASK_MATHEMATICAL_PROOF,
    TASK_RANDOM_GENERATOR,
    TASK_RECONSTRUCTION,
    TASK_REFERENCES,
)


def _sample_input(schema: dict[str, Any], seed: int = 0) -> str:
    rng = random.Random(seed)
    if "fields" not in schema:
        count = int(schema.get("token_count", 1))
        low, high = int(schema.get("minimum", 0)), int(schema.get("maximum", 10))
        return " ".join(str(rng.randint(low, high)) for _ in range(count)) + "\n"

    values: dict[str, Any] = {}
    output: list[str] = []
    desired_size = 4 + (seed % 5)
    for field in schema["fields"]:
        name, kind = field["name"], field["type"]
        low, high = int(field["min"]), int(field["max"])
        if kind == "int":
            value = min(high, max(low, desired_size)) if name == schema.get("size_field") else min(high, max(low, 3))
            values[name] = value
            output.append(str(value))
        elif kind == "int_array":
            length = int(values[field["length_from"]])
            pool = [min(high, max(low, x)) for x in (-2, 0, 2, 5, 9)]
            array = [rng.choice(pool) for _ in range(length)]
            values[name] = array
            output.append(" ".join(map(str, array)))
    return "\n".join(output) + "\n"


def _generator_program(schema: dict[str, Any]) -> str:
    encoded = json.dumps(schema, separators=(",", ":"))
    return (
        "import json, random, sys\n"
        f"SCHEMA = json.loads({encoded!r})\n"
        "seed = int(sys.argv[1]); count = int(sys.argv[2]); rng = random.Random(seed)\n"
        "def make_case(index):\n"
        "    if 'fields' not in SCHEMA:\n"
        "        n=int(SCHEMA['token_count']); lo=int(SCHEMA['minimum']); hi=int(SCHEMA['maximum'])\n"
        "        return ' '.join(str(rng.randint(lo,hi)) for _ in range(n)) + '\\n'\n"
        "    fields=SCHEMA['fields']; size_field=SCHEMA.get('size_field')\n"
        "    array_field=next((f for f in fields if f['name']==size_field and f['type']=='int_array'),None)\n"
        "    length_name=array_field.get('length_from') if array_field else size_field\n"
        "    length_field=next((f for f in fields if f['name']==length_name and f['type']=='int'),None)\n"
        "    desired=None\n"
        "    if length_field:\n"
        "        lo=int(length_field['min']); hi=min(int(length_field['max']),max(lo,128))\n"
        "        span=hi-lo\n"
        "        if count < 10: desired=rng.randint(lo,hi)\n"
        "        elif index < count*70//100: desired=rng.randint(lo,lo+span//4)\n"
        "        elif index < count*90//100: desired=rng.randint(lo+span//4,lo+span//2)\n"
        "        else: desired=rng.randint(lo+span//2,hi)\n"
        "    values={}; lines=[]\n"
        "    for f in fields:\n"
        "        name=f['name']; kind=f['type']; lo=int(f['min']); hi=int(f['max'])\n"
        "        if kind=='int':\n"
        "            value=desired if name==length_name and desired is not None else min(hi,max(lo,3))\n"
        "            values[name]=value; lines.append(str(value))\n"
        "        elif kind=='int_array':\n"
        "            length=int(values[f['length_from']]); vals=[rng.randint(lo,hi) for _ in range(length)]\n"
        "            values[name]=vals; lines.append(' '.join(map(str,vals)))\n"
        "    return '\\n'.join(lines)+'\\n'\n"
        "cases=[{'input_size':1,'input':make_case(i),'distribution':'seeded_progressive'} for i in range(count)]\n"
        "print(json.dumps({'inputs':cases}))\n"
    )


class MockWorkflowProvider:
    '''Task-routed deterministic responses; never makes network/API calls.'''
    mock_mode = True
    provider_name = "offline_mock"

    def __init__(self):
        self.calls: list[dict[str, Any]] = []

    def generate_json(self, task: str, payload: dict, schema: dict) -> dict:
        from app.ai.guardrails import GuardedProvider

        class _MockAdapter:
            def __init__(self, owner):
                self.owner = owner

            def generate_json(self, inner_task, inner_payload, inner_schema):
                return self.owner._generate_json_unchecked(
                    inner_task, inner_payload, inner_schema
                )

        return GuardedProvider(_MockAdapter(self)).generate_json(
            task, payload, schema
        )

    def _generate_json_unchecked(self, task: str, payload: dict, schema: dict) -> dict:
        self.calls.append({"task": task, "payload": deepcopy(payload), "schema": deepcopy(schema)})
        if task == TASK_RECONSTRUCTION:
            statement = ""
            if isinstance(payload, dict):
                statement = str(
                    payload.get("problem_statement")
                    or payload.get("assignment_statement")
                    or ""
                ).strip()

            if not statement:
                return {
                    "status": "needs_clarification",
                    "candidates": [],
                    "clarifying_questions": [
                        "Provide the exact programming problem statement and input/output format."
                    ],
                    "constraints": [],
                    "confidence": 0.0,
                    "message": (
                        "Offline mock mode requires the actual problem statement. "
                        "It will not invent an assignment from source code."
                    ),
                    "limitations": [
                        "No assignment-specific mock fixture was selected.",
                        "Generated cases are unavailable until the specification is confirmed."
                    ],
                }

            if "two sum" not in statement.lower():
                return {
                    "status": "needs_clarification",
                    "candidates": [],
                    "clarifying_questions": [
                        "Provide instructor-confirmed problem details for this assignment."
                    ],
                    "constraints": [],
                    "confidence": 0.0,
                    "message": (
                        "The offline mock provider only supports its explicit Two Sum demo. "
                        "This assignment requires instructor-provided problem details."
                    ),
                    "limitations": [
                        "No unrelated Two Sum cases will be generated."
                    ],
                }

            response = get_scenario("agent1", "ready")
            response["limitations"] = list(response.get("limitations") or []) + [
                "SIMULATED DEMO: built-in Two Sum fixture selected from the supplied statement."
            ]
            return response

        if task == TASK_REFERENCES:
            return get_scenario("agent2", "reference_solutions")
        if task == TASK_RANDOM_GENERATOR:
            input_schema = payload.get("agent1_input_schema") or {}
            return {
                "generator_program": _generator_program(input_schema),
                "design_rationale": "Offline generator follows the approved input schema and uses a reproducible seed.",
                "distributions": ["seeded_progressive"],
                "size_strategy": "Seeded 70/20/10 size bands favor small/medium brute-force comparisons with a few larger probes.",
                "limitations": ["SIMULATED AGENT 3A RESPONSE: generator design is deterministic, not AI-authored."],
            }
        if task == TASK_EDGE_CASES:
            input_schema = payload.get("agent1_input_schema") or {}
            return {
                "summary": "Offline mock proposals exercise representative schema-valid inputs.",
                "cases": [
                    {
                        "name": f"mock_valid_case_{i}",
                        "input": _sample_input(input_schema, i),
                        "expected_output": None,
                        "target": ["student", "brute_force", "efficient"],
                        "rationale": "Representative valid input generated from the approved schema.",
                        "failure_hypothesis": "No defect is asserted; compare actual executions.",
                        "constraint_basis": "Generated within the approved Agent 1 input schema.",
                    } for i in range(1, 4)
                ],
                "limitations": ["SIMULATED AGENT 3B RESPONSE: proposals are not AI-derived adversarial hypotheses."],
            }
        if task == TASK_COMPLEXITY:
            response = get_scenario("agent4", "inconclusive")
            source_lines = str(payload.get("source_code", "")).splitlines()
            if source_lines:
                response["grading_assessment"] = {
                    "rating": 2,
                    "rationale": "The offline mock has insufficient analysis context for a substantive complexity rating.",
                    "evidence": [{"line": 1, "quote": source_lines[0].strip()}],
                }
            else:
                response["grading_assessment"] = {
                    "rating": 2, "rationale": "Structural schema fixture only.",
                    "evidence": [{"line": 1, "quote": "int main(void) { return 0; }"}],
                }
            return response
        if task == TASK_MATHEMATICAL_PROOF:
            return get_scenario("agent5", "inconclusive")
        if task == TASK_CODE_QUALITY:
            source = payload.get("submitted_source_code", "")
            return {
                "summary": "Offline mock review completed structurally; no source-specific quality conclusion is asserted.",
                "strengths": [],
                "findings": [],
                "rubric_ratings": {
                    name: {
                        "rating": 2,
                        "rationale": "Offline schema fixture only; no quality claim is asserted.",
                        "evidence": [{"line": 1, "quote": source.splitlines()[0].strip()}] if source.splitlines() else [{"line": 1, "quote": "int main(void) { return 0; }"}],
                    }
                    for name in ("readability", "modularity", "design_originality")
                },
                "limitations": [
                    "SIMULATED AGENT 6 RESPONSE: no AI code review was performed.",
                    f"Source length received: {len(source.splitlines())} lines.",
                    "Use a configured AI provider for source-linked findings.",
                ],
            }
        raise ValueError(f"No offline mock response is registered for task: {task}")

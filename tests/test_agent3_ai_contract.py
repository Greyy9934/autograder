import json
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from analyzers.agent3_ai import (
    analyze_agent3b_edges,
    execute_agent3a_program,
    generate_agent3a_program,
)
from analyzers.input_schema import IntegerInputSchema


class CapturingProvider:
    def __init__(self, response):
        self.response = response
        self.calls = []

    def generate_json(self, *, task, payload, schema):
        self.calls.append({"task": task, "payload": payload, "schema": schema})
        return self.response


def _problem(schema):
    return {
        "problem_statement": "Read n and return the array sum.",
        "user_supplied_problem_statement": "Given n integers, print their sum.",
        "constraints": ["1 <= n <= 10"],
        "input_format": "n followed by n integers",
        "output_format": "Print one integer",
        "input_schema": schema,
    }


def _schema():
    return {
        "version": 1,
        "fields": [
            {"name": "n", "type": "int", "min": 1, "max": 10},
            {"name": "values", "type": "int_array", "length_from": "n", "min": -50, "max": 50},
        ],
        "size_field": "values",
    }


class Agent3ContractTests(unittest.TestCase):
    def test_agent3a_gets_approved_contract_full_context_and_both_references(self):
        schema = _schema()
        provider = CapturingProvider({
            "generator_program": "print('{}')",
            "design_rationale": "Seeded valid generator.",
            "distributions": ["uniform"],
            "size_strategy": "Small sizes",
            "limitations": [],
        })
        result = generate_agent3a_program(
            provider,
            problem=_problem(schema),
            schema=schema,
            references={
                "brute_force": {"code": "int main(void){}"},
                "efficient": {"code": "int main(void){return 0;}"},
            },
            student_source="int main(void){return 0;}",
            max_cases=4,
        )
        self.assertEqual(result["status"], "program_generated_unexecuted")
        payload = provider.calls[0]["payload"]
        self.assertEqual(payload["approved_execution_contract"]["input_schema"], schema)
        self.assertEqual(payload["approved_execution_contract"]["input_format"], "n followed by n integers")
        self.assertEqual(payload["approved_execution_contract"]["output_format"], "Print one integer")
        self.assertEqual(payload["approved_execution_contract"]["output_contract"]["format"], "Print one integer")
        self.assertEqual(payload["agent1_problem_reconstruction"]["user_supplied_problem_statement"], "Given n integers, print their sum.")
        self.assertEqual(payload["agent2_brute_force"]["code"], "int main(void){}")
        self.assertEqual(payload["agent2_efficient"]["code"], "int main(void){return 0;}")
        self.assertEqual(payload["student_c_source"], "int main(void){return 0;}")

    def test_agent3a_fails_closed_if_approved_schema_is_missing(self):
        provider = CapturingProvider({})
        problem = _problem(_schema())
        del problem["input_schema"]
        result = generate_agent3a_program(
            provider, problem=problem, schema=_schema(), references={},
            student_source="int main(void){}", max_cases=1,
        )
        self.assertEqual(result["status"], "schema_contract_mismatch")
        self.assertEqual(provider.calls, [])

    def test_agent3a_fails_closed_if_passed_schema_differs_from_approved(self):
        approved = _schema()
        altered = {**approved, "size_field": "n"}
        provider = CapturingProvider({})
        result = generate_agent3a_program(
            provider, problem=_problem(approved), schema=altered,
            references={}, student_source="int main(void){}", max_cases=1,
        )
        self.assertEqual(result["status"], "schema_contract_mismatch")
        self.assertEqual(provider.calls, [])

    def test_agent3b_receives_identical_authoritative_io_contract(self):
        schema = _schema()
        provider = CapturingProvider({"summary": "Boundary cases.", "cases": [], "limitations": []})
        result = analyze_agent3b_edges(
            provider, problem=_problem(schema), schema=schema,
            references={"brute_force": {"code": "bf"}, "efficient": {"code": "fast"}},
            student_source="student",
        )
        self.assertEqual(result["status"], "proposed_unvalidated")
        contract = provider.calls[0]["payload"]["approved_execution_contract"]
        self.assertEqual(contract["input_schema"], schema)
        self.assertEqual(contract["input_format"], "n followed by n integers")
        self.assertEqual(contract["output_format"], "Print one integer")

    def test_invalid_case_is_excluded_without_discarding_valid_batch(self):
        with patch(
            "analyzers.agent3_ai.subprocess.run",
            return_value=SimpleNamespace(
                returncode=0,
                stdout=json.dumps({"inputs": [
                    {"input": "42\n"},
                    {"input": "101\n"},
                ]}),
                stderr="",
            ),
        ):
            result = execute_agent3a_program(
                {"generator_program": "pass"}, seed=1,
                schema=IntegerInputSchema(1, 0, 100), max_cases=2,
            )
        self.assertEqual(result["status"], "generated")
        self.assertEqual([item["input"] for item in result["inputs"]], ["42\n"])
        self.assertEqual(result["rejected_count"], 1)
        self.assertIn("[0, 100]", result["rejected_cases"][0]["reason"])
        self.assertTrue(result["validation"]["all_returned_cases_validated"])

    def test_all_schema_invalid_cases_fail_closed(self):
        with patch(
            "analyzers.agent3_ai.subprocess.run",
            return_value=SimpleNamespace(
                returncode=0,
                stdout=json.dumps({"inputs": [{"input": "101\n"}]}),
                stderr="",
            ),
        ):
            result = execute_agent3a_program(
                {"generator_program": "pass"}, seed=1,
                schema=IntegerInputSchema(1, 0, 100), max_cases=1,
            )
        self.assertEqual(result["status"], "generator_output_invalid")
        self.assertIn("No generated case matched", result["message"])
        self.assertEqual(result["inputs"], [])



if __name__ == "__main__":
    unittest.main()

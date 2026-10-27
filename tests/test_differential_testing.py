import unittest
from unittest.mock import patch

from analyzers.differential_testing import (
    compare_programs,
    generate_integer_list_inputs,
    generate_integer_list_edge_cases,
)


def completed(output):
    return {
        "status": "completed",
        "exit_code": 0,
        "stdout": output,
        "stderr": "",
    }


class DifferentialTestingTests(unittest.TestCase):
    def test_matching_outputs_agree(self):
        with patch(
            "analyzers.differential_testing.run_c_program",
            side_effect=[completed("5\n"), completed("5\n")],
        ):
            result = compare_programs("int main(void){return 0;}",
                                      "int main(void){return 0;}", ["1\n"])
        self.assertEqual(result["status"], "agreement_on_tested_inputs")
        self.assertEqual(result["agreement_count"], 1)
        self.assertFalse(result["references_trusted"])

    def test_different_outputs_find_counterexample(self):
        with patch(
            "analyzers.differential_testing.run_c_program",
            side_effect=[completed("5\n"), completed("6\n")],
        ):
            result = compare_programs("a", "b", ["1\n"])
        self.assertEqual(result["status"], "counterexample_found")
        self.assertEqual(result["comparisons"][0]["input"], "1\n")

    def test_execution_failure_is_not_agreement(self):
        with patch(
            "analyzers.differential_testing.run_c_program",
            side_effect=[
                {"status": "timeout", "exit_code": None, "stdout": ""},
                completed("5\n"),
            ],
        ):
            result = compare_programs("a", "b", ["1\n"])
        self.assertEqual(result["status"], "execution_failure")
        self.assertEqual(result["failure_count"], 1)

    def test_invalid_inputs_rejected(self):
        result = compare_programs("a", "b", [])
        self.assertEqual(result["status"], "invalid_request")

    def test_random_inputs_are_reproducible(self):
        first = generate_integer_list_inputs(seed=123, count=10)
        second = generate_integer_list_inputs(seed=123, count=10)
        self.assertEqual(first["inputs"], second["inputs"])

    def test_random_inputs_differ_by_seed(self):
        first = generate_integer_list_inputs(seed=123, count=10)
        second = generate_integer_list_inputs(seed=456, count=10)
        self.assertNotEqual(first["inputs"], second["inputs"])

    def test_random_input_format_and_bounds(self):
        result = generate_integer_list_inputs(
            seed=9, count=5, min_length=2, max_length=4,
            min_value=-3, max_value=7,
        )
        self.assertEqual(result["count"], 5)
        for case in result["inputs"]:
            lines = case.splitlines()
            n = int(lines[0])
            values = list(map(int, lines[1].split()))
            self.assertEqual(n, len(values))
            self.assertTrue(2 <= n <= 4)
            self.assertTrue(all(-3 <= x <= 7 for x in values))

    def test_bad_count_rejected(self):
        self.assertEqual(
            generate_integer_list_inputs(seed=1, count=0)["status"],
            "invalid_request",
        )


    def test_truncated_output_is_not_treated_as_agreement(self):
        truncated = {
            "status": "completed",
            "exit_code": 0,
            "stdout": "same\\n",
            "stderr": "",
            "stdout_truncated": True,
            "stderr_truncated": False,
        }
        with patch(
            "analyzers.differential_testing.run_c_program",
            side_effect=[truncated, completed("same\\n")],
        ):
            result = compare_programs("a", "b", ["input\\n"])
        self.assertEqual(result["status"], "execution_failure")
        self.assertEqual(result["failure_count"], 1)

    def test_integer_generator_rejects_invalid_bounds(self):
        result = generate_integer_list_inputs(
            seed=1, count=2, min_length=0
        )
        self.assertEqual(result["status"], "invalid_request")

    def test_integer_generator_rejects_invalid_argument_types(self):
        invalid_arguments = [
            {"seed": True},
            {"count": 1.5},
            {"min_length": "2"},
            {"max_length": 3.5},
            {"min_value": "0"},
            {"max_value": False},
        ]
        for override in invalid_arguments:
            with self.subTest(override=override):
                arguments = {"seed": 1, "count": 2}
                arguments.update(override)
                result = generate_integer_list_inputs(**arguments)
                self.assertEqual(result["status"], "invalid_request")

    def test_edge_case_generator_includes_supported_boundaries(self):
        result = generate_integer_list_edge_cases(
            min_length=1,
            max_length=3,
            min_value=-2,
            max_value=2,
        )
        self.assertEqual(result["status"], "generated")
        self.assertEqual(result["count"], len(result["inputs"]))
        self.assertTrue(result["inputs"])

        decoded = []
        for case in result["inputs"]:
            lines = case.splitlines()
            length = int(lines[0])
            values = list(map(int, lines[1].split()))
            self.assertEqual(length, len(values))
            self.assertTrue(1 <= length <= 3)
            self.assertTrue(all(-2 <= value <= 2 for value in values))
            decoded.append(values)

        self.assertIn([-2], decoded)
        self.assertIn([2], decoded)
        self.assertIn([0], decoded)
        self.assertIn([-2, -1, 0], decoded)

    def test_edge_case_generator_rejects_invalid_arguments(self):
        for arguments in (
            {"min_length": 0},
            {"max_length": 0},
            {"min_value": 5, "max_value": 2},
            {"min_length": True},
            {"max_value": "10"},
        ):
            with self.subTest(arguments=arguments):
                result = generate_integer_list_edge_cases(**arguments)
                self.assertEqual(result["status"], "invalid_request")


if __name__ == "__main__":
    unittest.main()

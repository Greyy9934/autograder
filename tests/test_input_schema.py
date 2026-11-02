import random
import unittest

from analyzers.input_schema import IntegerInputSchema
from analyzers.assignment_spec import AssignmentSpec
from analyzers.random_test_generator import generate_schema_test_batch
from analyzers.structured_input_schema import StructuredIntegerInputSchema
from analyzers.workload_limits import (
    MAX_GENERATED_ARRAY_LENGTH,
    MAX_GENERATED_BATCH_INPUT_BYTES,
    MAX_GENERATED_CASE_INPUT_BYTES,
)


class InputSchemaTests(unittest.TestCase):
    def setUp(self):
        self.schema = IntegerInputSchema(token_count=2, minimum=-10, maximum=10)
        self.spec = AssignmentSpec(
            problem_id="sum-two",
            title="Sum two integers",
            problem_statement="Read two integers and print their sum.",
            constraints=("Each integer is between -10 and 10.",),
            input_format="Two whitespace-separated integers.",
            output_format="Their sum.",
        ).confirm(instructor_approved=True)

    def test_validates_correct_input(self):
        self.assertTrue(self.schema.validate("-10 10\n"))

    def test_rejects_wrong_token_count(self):
        self.assertFalse(self.schema.validate("1 2 3"))

    def test_rejects_out_of_range_values(self):
        self.assertFalse(self.schema.validate("1 11"))

    def test_rejects_non_integer_values(self):
        self.assertFalse(self.schema.validate("one 2"))

    def test_generation_is_reproducible(self):
        first = self.schema.generate(random.Random(42), "uniform")
        second = self.schema.generate(random.Random(42), "uniform")
        self.assertEqual(first, second)

    def test_all_distributions_generate_valid_inputs(self):
        for mode in ("uniform", "boundary_biased", "duplicate_heavy", "sorted", "reverse_sorted"):
            for seed in range(10):
                value = self.schema.generate(random.Random(seed), mode)
                self.assertTrue(self.schema.validate(value), (mode, value))

    def test_schema_batch_generation(self):
        result = generate_schema_test_batch(
            self.spec, schema=self.schema, seed=42, count=20,
            distribution="boundary_biased",
        )
        self.assertEqual(result["status"], "generated")
        self.assertEqual(len(result["inputs"]), 20)
        self.assertTrue(all(self.schema.validate(item) for item in result["inputs"]))

    def test_huge_approved_array_bound_is_not_used_as_a_random_allocation_target(self):
        schema = StructuredIntegerInputSchema.from_dict({
            "version": 1,
            "fields": [
                {"name": "n", "type": "int", "min": 1, "max": 2147483647},
                {"name": "Arr", "type": "int_array", "length_from": "n", "min": -2147483648, "max": 2147483647},
            ],
            "size_field": "n",
        })
        spec = AssignmentSpec(
            problem_id="bounded-array", title="Bounded array", problem_statement="Read n values.",
            constraints=("n is in the approved schema bounds",), input_format="n then n integers",
            output_format="one integer", input_schema=schema.to_dict(),
        ).confirm(instructor_approved=True)

        result = generate_schema_test_batch(
            spec, schema=schema, seed=7, count=100, distribution="uniform",
        )

        self.assertEqual(result["status"], "generated")
        self.assertEqual(len(result["inputs"]), 100)
        self.assertLessEqual(max(schema.input_size(value) for value in result["inputs"]), MAX_GENERATED_ARRAY_LENGTH)
        self.assertTrue(all(len(value.encode("utf-8")) <= MAX_GENERATED_CASE_INPUT_BYTES for value in result["inputs"]))
        self.assertLessEqual(result["total_input_bytes"], MAX_GENERATED_BATCH_INPUT_BYTES)

    def test_minimum_array_size_above_operational_cap_fails_without_allocating(self):
        schema = StructuredIntegerInputSchema.from_dict({
            "version": 1,
            "fields": [
                {"name": "n", "type": "int", "min": 2147483647, "max": 2147483647},
                {"name": "Arr", "type": "int_array", "length_from": "n", "min": 0, "max": 1},
            ],
            "size_field": "n",
        })
        spec = AssignmentSpec(
            problem_id="impossible-array", title="Impossible array", problem_statement="Read n values.",
            constraints=("n is fixed",), input_format="n then n integers", output_format="one integer",
            input_schema=schema.to_dict(),
        ).confirm(instructor_approved=True)

        result = generate_schema_test_batch(
            spec, schema=schema, seed=1, count=1, distribution="uniform",
        )

        self.assertEqual(result["status"], "generator_error")
        self.assertIn("exceeds the local test-generation limit", result["message"])


if __name__ == "__main__":
    unittest.main()

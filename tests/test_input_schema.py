import random
import unittest

from analyzers.input_schema import IntegerInputSchema
from analyzers.assignment_spec import AssignmentSpec
from analyzers.random_test_generator import generate_schema_test_batch


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


if __name__ == "__main__":
    unittest.main()

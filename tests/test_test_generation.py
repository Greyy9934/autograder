import unittest

from analyzers.assignment_spec import AssignmentSpec
from analyzers.input_schema import IntegerInputSchema
from analyzers.test_generation import generate_test_plans


class TestGenerationCoordinatorTests(unittest.TestCase):
    def setUp(self):
        self.draft = AssignmentSpec(
            problem_id="sum",
            title="Sum two integers",
            problem_statement="Read two integers and print their sum.",
            constraints=("Each integer is between -10 and 10.",),
            input_format="Two whitespace-separated integers.",
            output_format="Print their sum.",
        )
        self.spec = self.draft.confirm(instructor_approved=True)
        self.schema = IntegerInputSchema(2, -10, 10)
        self.source = "int main(void) { int a[2]; return 0; }"

    def test_both_agents_generate_from_confirmed_spec(self):
        result = generate_test_plans(
            self.source, self.spec, self.schema,
            random_count=10,
            adversarial_count=10,
        )
        self.assertEqual(result["status"], "generated")
        self.assertEqual(result["random_tests"]["count"], 10)
        self.assertGreater(result["adversarial_tests"]["case_count"], 0)
        self.assertFalse(result["execution_performed"])

    def test_unconfirmed_spec_is_rejected(self):
        result = generate_test_plans(self.source, self.draft, self.schema)
        self.assertEqual(result["status"], "rejected")

    def test_missing_input_schema_is_rejected(self):
        result = generate_test_plans(self.source, self.spec, None)
        self.assertEqual(result["status"], "invalid_request")

    def test_random_generation_is_reproducible(self):
        first = generate_test_plans(
            self.source, self.spec, self.schema, random_seed=123
        )
        second = generate_test_plans(
            self.source, self.spec, self.schema, random_seed=123
        )
        self.assertEqual(
            first["random_tests"]["inputs"],
            second["random_tests"]["inputs"],
        )

    def test_spec_fingerprint_is_preserved(self):
        result = generate_test_plans(self.source, self.spec, self.schema)
        self.assertEqual(result["spec_fingerprint"], self.spec.fingerprint())


if __name__ == "__main__":
    unittest.main()

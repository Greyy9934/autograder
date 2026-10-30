import unittest

from analyzers.assignment_spec import AssignmentSpec
from analyzers.input_schema import IntegerInputSchema
from analyzers.adversarial_test_planner import plan_adversarial_tests


class AdversarialPlannerTests(unittest.TestCase):
    def setUp(self):
        self.spec = AssignmentSpec(
            problem_id="sum-two",
            title="Sum two integers",
            problem_statement="Read two integers and print their sum.",
            constraints=("Each integer is between -10 and 10.",),
            input_format="Two whitespace-separated integers.",
            output_format="Their sum.",
        ).confirm(instructor_approved=True)
        self.schema = IntegerInputSchema(2, -10, 10)
        self.source = """
        #include <stdio.h>
        int main(void) {
            int a[2], x;
            for (int i = 0; i <= 2; i++) scanf("%d", &x);
            return 0;
        }
        """

    def test_plans_cases_from_source_and_boundaries(self):
        result = plan_adversarial_tests(self.source, self.spec, self.schema)
        self.assertEqual(result["status"], "planned")
        self.assertGreater(result["case_count"], 0)
        self.assertTrue(any("array" in c["source_trigger"] for c in result["cases"]))

    def test_all_inputs_match_schema(self):
        result = plan_adversarial_tests(self.source, self.spec, self.schema)
        self.assertTrue(all(self.schema.validate(c["input"]) for c in result["cases"]))

    def test_same_seed_is_reproducible(self):
        first = plan_adversarial_tests(self.source, self.spec, self.schema, seed=17)
        second = plan_adversarial_tests(self.source, self.spec, self.schema, seed=17)
        self.assertEqual(first["cases"], second["cases"])

    def test_source_hash_is_recorded(self):
        result = plan_adversarial_tests(self.source, self.spec, self.schema)
        self.assertEqual(len(result["source_sha256"]), 64)

    def test_unvalidated_reference_is_failure_evidence_only(self):
        result = plan_adversarial_tests(
            self.source, self.spec, self.schema,
            reference_metadata={"oracle_scope": "correctness_judgment_allowed"},
        )
        self.assertEqual(result["reference_oracle_scope"], "correctness_judgment_allowed")

    def test_invalid_oracle_scope_is_restricted(self):
        result = plan_adversarial_tests(
            self.source, self.spec, self.schema,
            reference_metadata={"oracle_scope": "anything"},
        )
        self.assertEqual(result["reference_oracle_scope"], "failure_evidence_only")

    def test_unconfirmed_spec_is_rejected(self):
        draft = AssignmentSpec(
            problem_id="draft", title="Draft", problem_statement="Unconfirmed",
            constraints=(), input_format="unknown", output_format="unknown",
        )
        result = plan_adversarial_tests(self.source, draft, self.schema)
        self.assertEqual(result["status"], "rejected")

    def test_case_limit_is_enforced(self):
        result = plan_adversarial_tests(self.source, self.spec, self.schema, max_cases=3)
        self.assertLessEqual(result["case_count"], 3)


if __name__ == "__main__":
    unittest.main()

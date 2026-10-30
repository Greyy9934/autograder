import random
import unittest

from analyzers.assignment_spec import AssignmentSpec
from analyzers.random_test_generator import generate_random_test_batch


class RandomTestGeneratorTests(unittest.TestCase):
    def setUp(self):
        self.spec = AssignmentSpec(
            problem_id="sum",
            title="Sum integers",
            problem_statement="Read two integers and print their sum.",
            constraints=("Both values are between -100 and 100.",),
            input_format="Two integers separated by whitespace.",
            output_format="Print their sum.",
        ).confirm(instructor_approved=True)

    @staticmethod
    def builder(rng, spec, distribution):
        values = [rng.randint(-100, 100), rng.randint(-100, 100)]
        if distribution == "boundary_biased":
            values = [
                rng.choice([-100, -99, -1, 0, 1, 99, 100])
                for _ in range(2)
            ]
        elif distribution == "duplicate_heavy":
            value = rng.randint(-100, 100)
            values = [value, value]
        elif distribution == "sorted":
            values.sort()
        elif distribution == "reverse_sorted":
            values.sort(reverse=True)
        return f"{values[0]} {values[1]}\n"

    @staticmethod
    def validator(value, spec):
        parts = value.split()
        return (
            len(parts) == 2
            and all(-100 <= int(x) <= 100 for x in parts)
        )

    def generate(self, seed=42, count=20):
        return generate_random_test_batch(
            self.spec,
            seed=seed,
            count=count,
            input_generator=self.builder,
            input_validator=self.validator,
        )

    def test_same_seed_reproduces_identical_batch(self):
        self.assertEqual(self.generate(), self.generate())

    def test_different_seeds_change_batch(self):
        self.assertNotEqual(
            self.generate(seed=42)["inputs"],
            self.generate(seed=43)["inputs"],
        )

    def test_batch_has_requested_count(self):
        result = self.generate(count=25)
        self.assertEqual(result["status"], "generated")
        self.assertEqual(result["count"], 25)

    def test_unconfirmed_specification_is_rejected(self):
        draft = AssignmentSpec(
            problem_id="sum",
            title="Sum",
            problem_statement="Add two numbers.",
            constraints=(),
            input_format="Two integers.",
            output_format="Their sum.",
        )
        result = generate_random_test_batch(
            draft, seed=1, count=5,
            input_generator=self.builder,
            input_validator=self.validator,
        )
        self.assertEqual(result["status"], "rejected")

    def test_invalid_generated_input_is_rejected(self):
        result = generate_random_test_batch(
            self.spec, seed=1, count=5,
            input_generator=lambda rng, spec, distribution: "invalid",
            input_validator=self.validator,
        )
        self.assertEqual(result["status"], "validation_failed")

    def test_invalid_count_is_rejected(self):
        result = self.generate(count=0)
        self.assertEqual(result["status"], "invalid_request")

    def test_supported_distributions_are_recorded(self):
        for distribution in (
            "uniform", "boundary_biased", "duplicate_heavy",
            "sorted", "reverse_sorted",
        ):
            result = generate_random_test_batch(
                self.spec, seed=7, count=5,
                input_generator=self.builder,
                input_validator=self.validator,
                distribution=distribution,
            )
            self.assertEqual(result["status"], "generated")
            self.assertEqual(result["distribution"], distribution)

    def test_unknown_distribution_is_rejected(self):
        result = generate_random_test_batch(
            self.spec, seed=7, count=5,
            input_generator=self.builder,
            input_validator=self.validator,
            distribution="invented",
        )
        self.assertEqual(result["status"], "invalid_request")

    def test_spec_fingerprint_is_recorded(self):
        result = self.generate()
        self.assertEqual(result["spec_fingerprint"], self.spec.fingerprint())


if __name__ == "__main__":
    unittest.main()

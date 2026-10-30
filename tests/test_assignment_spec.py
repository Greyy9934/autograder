import unittest
from dataclasses import FrozenInstanceError

from analyzers.assignment_spec import AssignmentSpec


CANDIDATE = {
    "id": "sum",
    "title": "Sum two integers",
    "problem_statement": "Read two integers and print their sum.",
}


class AssignmentSpecTests(unittest.TestCase):
    def make_draft(self):
        return AssignmentSpec.create_draft(
            CANDIDATE,
            constraints=("Integers fit in signed 32-bit range.",),
            input_format="Two integers separated by whitespace.",
            output_format="Print their sum followed by a newline.",
            time_limit_seconds=1.0,
            memory_limit_mb=128,
        )

    def test_created_spec_is_unconfirmed(self):
        spec = self.make_draft()
        self.assertFalse(spec.confirmed)

    def test_requires_explicit_approval(self):
        with self.assertRaises(ValueError):
            self.make_draft().confirm(instructor_approved=False)

    def test_confirmation_returns_new_immutable_spec(self):
        draft = self.make_draft()
        confirmed = draft.confirm(instructor_approved=True)
        self.assertFalse(draft.confirmed)
        self.assertTrue(confirmed.confirmed)
        self.assertNotEqual(draft.fingerprint(), confirmed.fingerprint())

    def test_spec_is_immutable(self):
        spec = self.make_draft()
        with self.assertRaises(FrozenInstanceError):
            spec.title = "Changed"

    def test_fingerprint_is_deterministic(self):
        self.assertEqual(self.make_draft().fingerprint(), self.make_draft().fingerprint())

    def test_missing_input_format_is_rejected(self):
        with self.assertRaises(ValueError):
            AssignmentSpec.create_draft(
                CANDIDATE,
                output_format="Print the answer.",
            )

    def test_invalid_constraints_are_rejected(self):
        with self.assertRaises(ValueError):
            AssignmentSpec.create_draft(
                CANDIDATE,
                constraints=("Valid", ""),
                input_format="Read input.",
                output_format="Print output.",
            )


if __name__ == "__main__":
    unittest.main()

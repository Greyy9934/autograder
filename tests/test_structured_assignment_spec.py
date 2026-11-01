import pytest

from analyzers.assignment_spec import AssignmentSpec


def _candidate(schema=None):
    candidate = {
        "id": "array_problem",
        "title": "Array task",
        "problem_statement": "Read n integers and a target.",
        "input_format": "n, n values, target",
        "output_format": "one integer",
    }
    if schema is not None:
        candidate["input_schema"] = schema
    return candidate


def _schema(maximum=100):
    return {
        "version": 1,
        "fields": [
            {"name": "n", "type": "int", "min": 1, "max": maximum},
            {"name": "values", "type": "int_array", "length_from": "n",
             "min": -1000, "max": 1000},
            {"name": "target", "type": "int", "min": -1000, "max": 1000},
        ],
        "size_field": "values",
    }


def test_schema_round_trips_and_is_in_approval_fingerprint():
    draft = AssignmentSpec.create_draft(
        _candidate(_schema()),
        constraints=("1 <= n <= 100",),
        input_format="n values target",
        output_format="one integer",
    )
    assert draft.to_dict()["input_schema"] == _schema()
    approved = draft.confirm(instructor_approved=True)
    assert approved.to_dict()["input_schema"] == _schema()

    changed = AssignmentSpec.create_draft(
        _candidate(_schema(200)),
        constraints=("1 <= n <= 100",),
        input_format="n values target",
        output_format="one integer",
    )
    assert approved.fingerprint() != changed.fingerprint()


def test_legacy_assignment_without_schema_still_works():
    draft = AssignmentSpec.create_draft(
        _candidate(),
        constraints=(),
        input_format="two integers",
        output_format="one integer",
    )
    assert draft.to_dict()["input_schema"] is None


def test_invalid_schema_is_rejected():
    bad = _schema()
    bad["fields"][1]["length_from"] = "not_declared"
    with pytest.raises(ValueError, match="input_schema is invalid"):
        AssignmentSpec.create_draft(
            _candidate(bad),
            constraints=(),
            input_format="n values target",
            output_format="one integer",
        )


def test_schema_input_size_can_use_a_scalar_workload_field():
    from analyzers.structured_input_schema import StructuredIntegerInputSchema

    schema = StructuredIntegerInputSchema.from_dict({
        "version": 1,
        "fields": [{"name": "n", "type": "int", "min": 0, "max": 40}],
        "size_field": "n",
    })

    assert schema.input_size("21\n") == 21

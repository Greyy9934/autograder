import pytest

from analyzers.assignment_spec import AssignmentSpec
from analyzers.input_schema import IntegerInputSchema
from analyzers.test_generation import generate_test_plans, plan_adversarial_tests
from analyzers.complexity_estimator import estimate_complexity


def make_spec(confirmed=True):
    return AssignmentSpec(
        problem_id="two-sum",
        title="Two Sum",
        problem_statement="Determine whether two distinct integers sum to a target.",
        constraints=("1 <= n <= 100", "-1000 <= values <= 1000"),
        input_format="n, followed by n integers and target",
        output_format="YES or NO",
        confirmed=confirmed,
    )


def make_schema():
    return IntegerInputSchema(token_count=12, minimum=-1000, maximum=1000)


def test_agent3_reproducible_random_and_adversarial_plan():
    first = generate_test_plans(
        "int main(void) { return 0; }",
        make_spec(),
        make_schema(),
        random_seed=101,
        random_count=12,
        adversarial_seed=202,
        adversarial_count=8,
    )
    second = generate_test_plans(
        "int main(void) { return 0; }",
        make_spec(),
        make_schema(),
        random_seed=101,
        random_count=12,
        adversarial_seed=202,
        adversarial_count=8,
    )
    assert first == second
    assert first["execution_performed"] is False
    assert first["random_tests"]["count"] == 12
    assert len(first["random_tests"]["inputs"]) == 12
    assert first["adversarial_tests"]["status"] == "planned"
    assert first["adversarial_tests"]["case_count"] == 8
    assert len(first["adversarial_tests"]["cases"]) == 8
    assert all(case["execution_status"] == "not_executed" for case in first["adversarial_tests"]["cases"])
    assert all(case["expected_output"] is None for case in first["adversarial_tests"]["cases"])


def test_agent3a_generates_reproducible_uniform_distribution():
    result = generate_test_plans(
        "int main(void) { return 0; }",
        make_spec(),
        make_schema(),
        random_seed=77,
        random_count=10,
        random_distribution="uniform",
        adversarial_count=0,
    )
    assert result["random_tests"]["status"] == "generated"
    assert result["random_tests"]["count"] == 10
    assert len(result["random_tests"]["inputs"]) == 10


def test_agent3a_rejects_unsupported_distribution():
    result = generate_test_plans(
        "int main(void) { return 0; }",
        make_spec(),
        make_schema(),
        random_count=10,
        random_distribution="boundary",
        adversarial_count=0,
    )
    assert result["random_tests"]["status"] == "invalid_request"
    assert result["random_tests"]["inputs"] == []


def test_agent3_rejects_unconfirmed_assignment():
    result = generate_test_plans(
        "int main(void) { return 0; }",
        make_spec(confirmed=False),
        make_schema(),
        random_count=2,
        adversarial_count=2,
    )
    assert result["status"] == "rejected"
    assert "confirmed" in result["reason"].lower()
    assert result["random_tests"] is None
    assert result["adversarial_tests"] is None


def test_agent3b_uses_source_and_static_findings():
    result = plan_adversarial_tests(
        "int main(void) { int a[10]; for (int i=0; i<=10; i++) a[i]=i; }",
        make_spec(),
        make_schema(),
        seed=19,
        max_cases=10,
        static_findings=[{"rule_id": "array_bounds", "line": 1}],
    )
    assert isinstance(result, dict)
    assert result
    assert result["status"] == "planned"
    assert result["case_count"] == len(result["cases"])
    assert result["case_count"] <= 10
    assert all(case["execution_status"] == "not_executed" for case in result["cases"])


@pytest.mark.parametrize(
    ("source", "minimum_loops"),
    [
        ("int main(void) { return 0; }", 0),
        ("int main(void) { for(int i=0;i<n;i++) {} }", 1),
        ("int main(void) { for(int i=0;i<n;i++) for(int j=0;j<n;j++) {} }", 2),
    ],
)
def test_agent4_loop_pattern_scenarios(source, minimum_loops):
    result = estimate_complexity(source)
    assert result["status"] == "completed"
    assert result["loop_count"] >= minimum_loops
    assert result["message"]
    assert result["limitations"]


def test_agent4_reports_dynamic_allocation_pattern():
    result = estimate_complexity(
        "int main(void) { int *a = malloc(n * sizeof(int)); free(a); }"
    )
    assert result["status"] == "completed"
    assert result["dynamic_allocation_count"] >= 1


def test_agent4_never_claims_static_estimate_is_empirical_proof():
    result = estimate_complexity(
        "int main(void) { for(int i=0;i<n;i++) {} }"
    )
    combined = " ".join([
        result["message"],
        *result["limitations"],
    ]).lower()
    assert "not measured runtime" in combined
    assert "not derived" in combined or "not fully parsed" in combined

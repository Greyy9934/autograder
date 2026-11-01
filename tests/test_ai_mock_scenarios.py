from copy import deepcopy

import pytest
from jsonschema import Draft202012Validator

from app.ai.mock_scenarios import SCENARIOS, SCHEMA_BY_AGENT, get_scenario


@pytest.mark.parametrize(
    ("agent", "name"),
    [
        (agent, name)
        for agent, scenarios in SCENARIOS.items()
        for name in scenarios
    ],
)
def test_every_mock_scenario_matches_its_real_agent_schema(agent, name):
    validator = Draft202012Validator(SCHEMA_BY_AGENT[agent])
    errors = list(validator.iter_errors(get_scenario(agent, name)))
    assert not errors, "\n".join(error.message for error in errors)


def test_scenario_catalog_has_multiple_outcomes_for_each_provider_agent():
    assert set(SCENARIOS) == {"agent1", "agent2", "agent4", "agent5"}
    assert len(SCENARIOS["agent1"]) >= 2
    assert len(SCENARIOS["agent2"]) >= 1
    assert {"linear_scan", "nested_loops", "recursive_divide_and_conquer", "sorting", "inconclusive", "plausible_but_wrong"} <= set(SCENARIOS["agent4"])
    assert {"counterexample", "proof_sketch", "inconclusive"} <= set(SCENARIOS["agent5"])


def test_get_scenario_returns_independent_copy():
    first = get_scenario("agent1", "ready")
    first["candidates"][0]["evidence"].append("mutated")

    second = get_scenario("agent1", "ready")
    assert "mutated" not in second["candidates"][0]["evidence"]


def test_unknown_scenario_fails_clearly():
    with pytest.raises(KeyError, match="Unknown mock scenario"):
        get_scenario("agent5", "made_up")

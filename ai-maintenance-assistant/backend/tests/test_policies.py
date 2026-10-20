from itertools import combinations, permutations

import pytest

from app.policies.rules import SAFETY_MESSAGES, category_for_asset_type, determine_priority, evaluate_safety


# Pin the agreed display contract independently of the implementation constant.
WARNING_ORDER = ("fire_or_smoke", "electrical_risk", "exposed_wires", "flooding")


def test_policies():
    assert category_for_asset_type("air_conditioner") == "HVAC"
    assert category_for_asset_type("printer") == "IT Equipment"
    assert determine_priority("air_conditioner", symptoms=["water_leak"], safety_signals=["electrical_risk"]) == "CRITICAL"
    assert evaluate_safety(["electrical_risk"]) is not None


@pytest.mark.parametrize("hazards", [subset for size in range(5) for subset in combinations(WARNING_ORDER, size)])
def test_every_hazard_set_has_one_warning_regardless_of_order_or_duplicates(hazards):
    expected = " ".join(SAFETY_MESSAGES[signal] for signal in hazards) or None
    for ordered in permutations(hazards):
        assert evaluate_safety(ordered) == expected
        assert evaluate_safety(["unknown", *ordered, *ordered]) == expected
    if len(hazards) == 1:
        assert expected == SAFETY_MESSAGES[hazards[0]]


@pytest.mark.parametrize("asset_type", ["air_conditioner", "printer", "plumbing", "electrical", "other"])
def test_warning_aggregation_keeps_existing_priority_rules(asset_type):
    for ordered in permutations(WARNING_ORDER):
        evaluate_safety(ordered)
        assert determine_priority(asset_type, safety_signals=ordered) == "CRITICAL"
    assert determine_priority(asset_type, safety_signals=["flooding"]) == (
        "CRITICAL" if asset_type in {"air_conditioner", "electrical"} else "LOW")
    for symptoms, priority in [([], "LOW"), (["water_leak"], "HIGH"), (["paper_jam"], "MEDIUM")]:
        assert evaluate_safety([]) is None
        assert determine_priority(asset_type, symptoms=symptoms) == priority

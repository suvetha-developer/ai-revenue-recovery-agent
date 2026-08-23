"""
Unit tests for RecoverAI Action Cost Model & Expected Net Value calculations.
"""

import pytest
from src.cost_model import ACTION_COSTS, get_action_cost, calculate_expected_net_value


def test_action_costs():
    """Verify each action returns exact fixed cost."""
    assert get_action_cost("retry_immediately") == 0.00
    assert get_action_cost("retry_in_3_days") == 0.00
    assert get_action_cost("send_payment_update_email") == 0.01
    assert get_action_cost("escalate_to_human_review") == 5.00
    assert get_action_cost("do_not_pursue") == 0.00
    assert get_action_cost("unknown_action") == 0.00


def test_expected_net_value():
    """Verify Expected Net Value formula: (Amount * Prob) - Cost."""
    # Example 1: $100 invoice, 80% prob, retry_immediately ($0 cost) -> $80.00
    net1 = calculate_expected_net_value(100.0, 0.8, "retry_immediately")
    assert net1 == 80.00

    # Example 2: $100 invoice, 80% prob, escalate_to_human_review ($5 cost) -> $75.00
    net2 = calculate_expected_net_value(100.0, 0.8, "escalate_to_human_review")
    assert net2 == 75.00

    # Example 3: $150 invoice, 72% prob, send_payment_update_email ($0.01 cost) -> $107.99
    net3 = calculate_expected_net_value(150.0, 0.72, "send_payment_update_email")
    assert pytest.approx(net3, 0.01) == 107.99

    # Example 4: Write-off action do_not_pursue -> 0.00
    net4 = calculate_expected_net_value(50.0, 0.0, "do_not_pursue")
    assert net4 == 0.00

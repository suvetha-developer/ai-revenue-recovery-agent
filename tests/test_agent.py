"""
Unit tests for RecoverAI Decision Engine & Heuristic Fallback Logic.
"""

import pytest
import pandas as pd
from unittest.mock import patch
from src.agent import get_cost_aware_heuristic, predict_payment_recovery
from src.cost_model import get_action_cost


def test_rule_based_fallback_do_not_pursue():
    """Low LTV customer with chronic payment failures should trigger do_not_pursue."""
    row = pd.Series({
        "customer_id": "CUST_TEST_LOW_LTV",
        "customer_tenure_days": 10,
        "past_successful_payments": 0,
        "past_failed_payments": 6,
        "failure_reason": "insufficient_funds",
        "amount_due": 12.0,
        "days_since_last_successful_payment": 90,
        "customer_ltv": 15.0,
        "customer_segment": "at_risk_low_value",
    })
    res = get_cost_aware_heuristic(row)
    assert res["action"] == "do_not_pursue"
    assert res["decision_source"] == "rule_based_fallback"
    assert get_action_cost(res["action"]) == 0.00


def test_rule_based_fallback_card_expired():
    """High LTV customer with card_expired should trigger send_payment_update_email."""
    row = pd.Series({
        "customer_id": "CUST_TEST_CARD_EXPIRED",
        "customer_tenure_days": 365,
        "past_successful_payments": 12,
        "past_failed_payments": 0,
        "failure_reason": "card_expired",
        "amount_due": 149.99,
        "days_since_last_successful_payment": 30,
        "customer_ltv": 1500.0,
        "customer_segment": "loyal_high_value",
    })
    res = get_cost_aware_heuristic(row)
    assert res["action"] == "send_payment_update_email"
    assert get_action_cost(res["action"]) == 0.01
    assert res["estimated_recovery_probability"] >= 0.50


def test_rule_based_fallback_fraud_check_high_amount():
    """Fraud check failure on high amount invoice ($100+) should escalate to human review."""
    row = pd.Series({
        "customer_id": "CUST_TEST_FRAUD",
        "customer_tenure_days": 100,
        "past_successful_payments": 5,
        "past_failed_payments": 0,
        "failure_reason": "card_declined_fraud_check",
        "amount_due": 250.0,
        "days_since_last_successful_payment": 20,
        "customer_ltv": 2000.0,
        "customer_segment": "loyal_high_value",
    })
    res = get_cost_aware_heuristic(row)
    assert res["action"] == "escalate_to_human_review"
    assert get_action_cost(res["action"]) == 5.00


def test_rule_based_fallback_network_timeout():
    """Transient network timeout for loyal customer should retry_immediately ($0 cost)."""
    row = pd.Series({
        "customer_id": "CUST_TEST_TIMEOUT",
        "customer_tenure_days": 400,
        "past_successful_payments": 15,
        "past_failed_payments": 0,
        "failure_reason": "network_timeout",
        "amount_due": 89.99,
        "days_since_last_successful_payment": 15,
        "customer_ltv": 900.0,
        "customer_segment": "loyal_high_value",
    })
    res = get_cost_aware_heuristic(row)
    assert res["action"] == "retry_immediately"
    assert get_action_cost(res["action"]) == 0.00


def test_predict_payment_recovery_cache_hit_bypasses_llm():
    """Verify pre-computed decision is served from cache without invoking Groq LLM."""
    row = pd.Series({
        "customer_id": "CUST_0001",  # Existing customer in SQLite pre-computed database
        "customer_tenure_days": 300,
        "past_successful_payments": 10,
        "past_failed_payments": 1,
        "failure_reason": "card_expired",
        "amount_due": 99.99,
        "days_since_last_successful_payment": 25,
        "customer_ltv": 800.0,
        "customer_segment": "loyal_high_value",
    })

    with patch("src.agent.call_llm_with_resilience") as mock_llm:
        res = predict_payment_recovery(row)
        assert res["decision_source"] == "cache"
        assert "action" in res
        # Confirm live LLM function was NOT called
        mock_llm.assert_not_called()

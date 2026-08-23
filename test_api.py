"""
Comprehensive API & Failure-Mode Stress Test Suite
Verifies normal endpoints, malformed payloads, rate-limit/fake-key fallbacks,
non-existent customer lookups, and pipeline idempotency.
"""

import os
import sqlite3
import pandas as pd
from fastapi.testclient import TestClient
from src.api import app
from src.agent import predict_payment_recovery
from run_demo import seed_demo

client = TestClient(app)


def test_normal_endpoints():
    print("--- 1. Testing Normal Endpoints ---")
    r1 = client.get("/")
    assert r1.status_code == 200, "Root endpoint failed"
    print("   [PASS] GET /")

    sample = {
        "customer_id": "CUST_TEST_01",
        "customer_tenure_days": 420,
        "past_successful_payments": 18,
        "past_failed_payments": 1,
        "failure_reason": "card_expired",
        "amount_due": 149.99,
        "days_since_last_successful_payment": 25,
        "customer_ltv": 1850.00,
        "customer_segment": "loyal_high_value",
    }
    r2 = client.post("/predict-recovery", json=sample)
    assert r2.status_code == 200, "Predict endpoint failed"
    print(f"   [PASS] POST /predict-recovery -> Action: {r2.json().get('recommended_action')}")

    r3 = client.post("/webhook/payment-failed", json=sample)
    assert r3.status_code == 200, "Webhook endpoint failed"
    print(f"   [PASS] POST /webhook/payment-failed -> Decision ID: {r3.json().get('decision_id')}")

    r4 = client.get("/metrics/summary")
    assert r4.status_code == 200, "Metrics summary endpoint failed"
    print("   [PASS] GET /metrics/summary")


def test_malformed_payloads():
    print("\n--- 2. Testing Malformed Payload Handling ---")
    # Missing required field 'amount_due'
    bad_payload_1 = {
        "customer_id": "CUST_BAD_01",
        "failure_reason": "card_expired",
    }
    r1 = client.post("/predict-recovery", json=bad_payload_1)
    assert r1.status_code == 422, "Malformed predict payload should return 422"
    print("   [PASS] Malformed POST /predict-recovery -> Returned clean 422 Validation Error")

    # Invalid type for 'amount_due'
    bad_payload_2 = {
        "customer_id": "CUST_BAD_02",
        "customer_tenure_days": "invalid_number_string",
        "past_successful_payments": 5,
        "past_failed_payments": 1,
        "failure_reason": "card_expired",
        "amount_due": "not_a_float",
        "days_since_last_successful_payment": 10,
        "customer_ltv": 500.0,
    }
    r2 = client.post("/webhook/payment-failed", json=bad_payload_2)
    assert r2.status_code == 422, "Malformed webhook payload should return 422"
    print("   [PASS] Malformed POST /webhook/payment-failed -> Returned clean 422 Validation Error")


def test_non_existent_customer_lookup():
    print("\n--- 3. Testing Non-Existent Customer Lookup ---")
    r = client.get("/audit-log/CUST_NONEXISTENT_99999")
    assert r.status_code == 200, "Non-existent customer lookup should return 200 with empty list"
    data = r.json()
    assert data["total_records"] == 0, "Total records should be 0"
    assert data["audit_history"] == [], "Audit history should be empty list"
    print("   [PASS] GET /audit-log/CUST_NONEXISTENT_99999 -> Returned clean 200 OK with total_records: 0")


def test_fake_api_key_fallback():
    print("\n--- 4. Testing Invalid API Key / Live Rate-Limit Fallback ---")
    original_key = os.environ.get("GROQ_API_KEY")
    original_demo = os.environ.get("DEMO_MODE")

    try:
        # Force DEMO_MODE=false and set a fake API key
        os.environ["DEMO_MODE"] = "false"
        os.environ["GROQ_API_KEY"] = "gsk_invalid_fake_key_for_stress_testing_12345"

        row = pd.Series(
            {
                "customer_id": "CUST_UNCACHED_STRESS_TEST",
                "customer_tenure_days": 150,
                "past_successful_payments": 4,
                "past_failed_payments": 2,
                "failure_reason": "card_declined_fraud_check",
                "amount_due": 120.00,
                "days_since_last_successful_payment": 15,
                "customer_ltv": 800.00,
                "customer_segment": "mid_tier_stable",
            }
        )

        # Force live call bypass cache
        decision = predict_payment_recovery(row, force_live=True)
        assert decision["decision_source"] == "rule_based_fallback", f"Expected rule_based_fallback, got {decision['decision_source']}"
        assert "action" in decision, "Decision must contain action"
        assert "reasoning" in decision, "Decision must contain reasoning"
        print(f"   [PASS] Fake API Key Fallback -> Triggered rule_based_fallback cleanly!")
        print(f"          Action: {decision['action']} | Source: {decision['decision_source']}")

    finally:
        # Restore environment
        if original_key:
            os.environ["GROQ_API_KEY"] = original_key
        else:
            os.environ.pop("GROQ_API_KEY", None)
        if original_demo:
            os.environ["DEMO_MODE"] = original_demo
        else:
            os.environ["DEMO_MODE"] = "true"


def test_pipeline_idempotency():
    print("\n--- 5. Testing Pipeline Idempotency (Consecutive Re-Runs) ---")
    # Run seed_demo twice consecutively without deleting DB
    seed_demo()
    seed_demo()

    db_path = os.path.join(os.path.dirname(__file__), "data", "payments.db")
    conn = sqlite3.connect(db_path)
    payments_count = conn.execute("SELECT count(*) FROM failed_payments").fetchone()[0]
    audit_count = conn.execute("SELECT count(*) FROM audit_log").fetchone()[0]
    conn.close()

    assert payments_count == 500, f"Expected 500 failed payments, got {payments_count}"
    assert audit_count == 1000, f"Expected 1000 audit log rows (500 baseline + 500 agent), got {audit_count}"
    print(f"   [PASS] Double execution verified -> Exactly 500 payments & 1000 audit entries cleanly updated!")


def run_all_stress_tests():
    print("=" * 65)
    print("🧪 EXECUTING FAILURE-MODE & API STRESS TEST SUITE")
    print("=" * 65)

    test_normal_endpoints()
    test_malformed_payloads()
    test_non_existent_customer_lookup()
    test_fake_api_key_fallback()
    test_pipeline_idempotency()

    print("\n" + "=" * 65)
    print("🎉 ALL STRESS TESTS PASSED WITH 100% SUCCESS!")
    print("=" * 65)


if __name__ == "__main__":
    run_all_stress_tests()

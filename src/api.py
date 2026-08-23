"""
Step 7 — FastAPI Live REST Microservice
Provides real-time dunning decision endpoints, gateway webhooks, customer audit trails, and live metrics.

Endpoints:
  - POST /predict-recovery
  - POST /webhook/payment-failed
  - GET  /audit-log/{customer_id}
  - GET  /metrics/summary
"""

import os
import sqlite3
import pandas as pd
from fastapi import FastAPI, HTTPException, Path
from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any

from src.agent import predict_payment_recovery
from src.audit import get_audit_trail_for_customer, log_decision
from src.cost_model import calculate_expected_net_value, get_action_cost
from src.razorpay_client import create_payment_link

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "payments.db")

app = FastAPI(
    title="RecoverAI — Autonomous Revenue Recovery Microservice (Razorpay-Native)",
    description="Cost-aware Dunning Automation Engine optimizing NET Recovered Revenue for Razorpay Merchants.",
    version="2.0.0",
)


# ---------------------------------------------------------------------------
# Pydantic Schemas
# ---------------------------------------------------------------------------
class FailedPaymentPayload(BaseModel):
    customer_id: str = Field(..., example="CUST_0102")
    customer_tenure_days: int = Field(..., example=340)
    past_successful_payments: int = Field(..., example=14)
    past_failed_payments: int = Field(..., example=1)
    failure_reason: str = Field(..., example="card_expired")
    amount_due: float = Field(..., example=149.99)
    days_since_last_successful_payment: int = Field(..., example=22)
    customer_ltv: float = Field(..., example=1250.00)
    customer_segment: Optional[str] = Field("mid_tier_stable", example="loyal_high_value")


class PredictionResponse(BaseModel):
    customer_id: str
    recommended_action: str
    action_cost: float
    estimated_recovery_probability: float
    estimated_expected_net_value: float
    reasoning: str
    decision_source: str


class WebhookResponse(BaseModel):
    status: str
    event: str
    customer_id: str
    decision_id: str
    recommended_action: str
    action_cost: float
    reasoning: str
    audit_logged: bool


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------
@app.get("/")
def read_root():
    return {
        "service": "AI Payment Recovery Agent API",
        "status": "online",
        "docs": "/docs",
        "demo_mode": os.environ.get("DEMO_MODE", "true").lower() == "true",
    }


@app.post("/predict-recovery", response_model=PredictionResponse)
def predict_recovery(payload: FailedPaymentPayload):
    """
    Predict optimal cost-aware recovery action for a failed payment event.
    Calculates expected NET revenue = (amount_due * prob) - action_cost.
    """
    row = pd.Series(payload.model_dump())
    decision = predict_payment_recovery(row)

    action = decision["action"]
    prob = decision.get("estimated_recovery_probability", 0.5)
    cost = get_action_cost(action)
    net_val = calculate_expected_net_value(payload.amount_due, prob, action)

    return PredictionResponse(
        customer_id=payload.customer_id,
        recommended_action=action,
        action_cost=cost,
        estimated_recovery_probability=prob,
        estimated_expected_net_value=net_val,
        reasoning=decision["reasoning"],
        decision_source=decision.get("decision_source", "cache"),
    )


@app.post("/webhook/payment-failed", response_model=WebhookResponse)
def payment_failed_webhook(payload: FailedPaymentPayload):
    """
    Gateway Webhook (Stripe/Razorpay style):
    Receives real-time payment failure event, runs agent, logs to audit_log, and returns action.
    """
    row = pd.Series(payload.model_dump())
    decision = predict_payment_recovery(row)

    action = decision["action"]
    prob = decision.get("estimated_recovery_probability", 0.5)
    cost = get_action_cost(action)

    # Log to audit_log table
    entry = log_decision(
        customer_id=payload.customer_id,
        system="agent_webhook",
        decision_source=decision.get("decision_source", "cache"),
        action=action,
        estimated_recovery_prob=prob,
        action_cost=cost,
        reasoning=decision["reasoning"],
        recovered=0,  # Pending outcome simulation
        amount_due=payload.amount_due,
        db_path=DB_PATH,
    )

    return WebhookResponse(
        status="processed",
        event="payment.failed",
        customer_id=payload.customer_id,
        decision_id=entry["decision_id"],
        recommended_action=action,
        action_cost=cost,
        reasoning=decision["reasoning"],
        audit_logged=True,
    )


@app.get("/audit-log/{customer_id}")
def get_customer_audit_trail(customer_id: str = Path(..., example="CUST_0102")):
    """
    Retrieve full historical decision audit trail for a customer.
    Demonstrates compliance and explainability.
    """
    df = get_audit_trail_for_customer(customer_id, db_path=DB_PATH)
    if df.empty:
        return {
            "customer_id": customer_id,
            "total_records": 0,
            "audit_history": [],
            "message": f"No historical audit records found for customer_id '{customer_id}'.",
        }
    return {
        "customer_id": customer_id,
        "total_records": len(df),
        "audit_history": df.to_dict(orient="records"),
    }


@app.post("/razorpay/create-recovery-link")
def create_razorpay_recovery_link(customer_id: str, amount_due: Optional[float] = 149.99):
    """
    Create a Razorpay Test Mode Payment Link for a customer recovery workflow.
    Uses real Razorpay SDK when RAZORPAY_LIVE_INTEGRATION=true or simulated link in DEMO_MODE.
    """
    res = create_payment_link(amount=amount_due or 149.99, customer_id=customer_id)
    return {
        "status": "success",
        "customer_id": customer_id,
        "amount_due": amount_due,
        "payment_link_id": res.get("payment_link_id"),
        "payment_link_url": res.get("short_url"),
        "mode": res.get("mode"),
    }




@app.get("/metrics/summary")
def get_metrics_summary():
    """
    Return baseline vs AI agent comparative metrics, total costs, and NET revenue uplift.
    """
    if not os.path.exists(DB_PATH):
        raise HTTPException(status_code=500, detail="Database not initialized. Please run dataset generator first.")

    conn = sqlite3.connect(DB_PATH)
    try:
        df = pd.read_sql("SELECT * FROM comparison_headlines", conn)
        conn.close()
        if df.empty:
            headlines = run_comparison(DB_PATH)
        else:
            headlines = df.iloc[0].to_dict()
    except Exception:
        conn.close()
        headlines = run_comparison(DB_PATH)

    return {
        "status": "success",
        "metrics": headlines,
    }

"""
Step 4 & 10 — Resilient Cost-Aware AI Agent
Uses Groq LLM (llama-3.1-8b-instant) with JSON mode, decision caching, DEMO_MODE,
exponential backoff retries, and graceful cost-aware rule fallback.

Objective: Maximize NET Recovered Revenue = (amount_due * recovery_prob) - action_cost
"""

import hashlib
import hashlib
import json
import os
import sqlite3
import time
import pandas as pd
from dotenv import load_dotenv
from src.cost_model import ACTION_COSTS, calculate_expected_net_value
from src.planner import RecoveryPlanner
from src.razorpay_client import create_payment_link

load_dotenv()

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "payments.db")

VALID_ACTIONS = [
    "retry_immediately",
    "retry_in_3_days",
    "send_payment_update_email",
    "escalate_to_human_review",
    "do_not_pursue",
]

# System prompt emphasizing NET revenue & cost awareness
SYSTEM_PROMPT = """You are an AI payment recovery specialist for a fintech company. Your objective is to MAXIMIZE NET RECOVERED REVENUE = (Amount Due × Estimated Recovery Probability) - Action Cost.

## Available Actions & Cost Table:
1. "retry_immediately" — Cost: $0.00. Best for transient network errors with strong payment history.
2. "retry_in_3_days" — Cost: $0.00. Standard automated retry for moderate risk cases.
3. "send_payment_update_email" — Cost: $0.01. Email prompt to update card details; ideal for expired cards or high-LTV customers.
4. "escalate_to_human_review" — Cost: $5.00. Manual review by human agent; ONLY justify if amount_due or expected recovery is high enough to offset the $5.00 cost (e.g. fraud-flagged high amount).
5. "do_not_pursue" — Cost: $0.00. Recovery: $0.00. Deliberately write off payment when expected recovery < pursuit cost or customer is low-LTV with chronic failures.

## Important Constraint:
Always weigh the Expected NET Revenue. Do NOT pick $5.00 human review for low-value payments where cost exceeds expected recovery!

You MUST respond with a valid JSON object containing exactly three fields:
{
  "action": "<one of the 5 valid actions>",
  "estimated_recovery_probability": <float between 0.0 and 1.0>,
  "reasoning": "<one specific sentence explicitly explaining the cost/value tradeoff for THIS customer>"
}
Do NOT include any text outside the JSON object."""


def compute_feature_hash(row: pd.Series) -> str:
    """Create deterministic SHA256 hash of customer payment context."""
    raw = f"{row['customer_id']}|{row['failure_reason']}|{row['amount_due']}|{row['customer_ltv']}|{row['past_failed_payments']}|{row['past_successful_payments']}|{row['days_since_last_successful_payment']}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# SQLite Cache Helpers
# ---------------------------------------------------------------------------
def init_cache_table(db_path: str = DB_PATH):
    """Ensure decision_cache table exists in SQLite."""
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS decision_cache (
            feature_hash TEXT PRIMARY KEY,
            customer_id TEXT,
            action TEXT,
            estimated_recovery_prob REAL,
            reasoning TEXT,
            decision_source TEXT,
            created_at TEXT
        );
        """
    )
    conn.commit()
    conn.close()


def get_cached_decision(feature_hash: str, db_path: str = DB_PATH) -> dict:
    """Lookup decision from cache."""
    init_cache_table(db_path)
    conn = sqlite3.connect(db_path)
    cursor = conn.execute(
        "SELECT action, estimated_recovery_prob, reasoning FROM decision_cache WHERE feature_hash = ?",
        (feature_hash,),
    )
    row = cursor.fetchone()
    conn.close()
    if row:
        return {
            "action": row[0],
            "estimated_recovery_probability": row[1],
            "reasoning": row[2],
            "decision_source": "cache",
        }
    return None


def save_cached_decision(feature_hash: str, customer_id: str, decision: dict, decision_source: str, db_path: str = DB_PATH):
    """Save decision to cache."""
    init_cache_table(db_path)
    conn = sqlite3.connect(db_path)
    conn.execute(
        """
        INSERT OR REPLACE INTO decision_cache 
        (feature_hash, customer_id, action, estimated_recovery_prob, reasoning, decision_source, created_at)
        VALUES (?, ?, ?, ?, ?, ?, datetime('now'))
        """,
        (
            feature_hash,
            customer_id,
            decision["action"],
            decision.get("estimated_recovery_probability", 0.5),
            decision["reasoning"],
            decision_source,
        ),
    )
    conn.commit()
    conn.close()


# ---------------------------------------------------------------------------
# Smart Cost-Aware Rule Fallback
# ---------------------------------------------------------------------------
def get_cost_aware_heuristic(row: pd.Series) -> dict:
    """
    Rule-based cost-aware recovery decision generator.
    Serves as graceful fallback under rate limits or offline mode.
    Calculates expected NET revenue for each candidate action and picks optimal.
    """
    reason = row["failure_reason"]
    ltv = row["customer_ltv"]
    successes = row["past_successful_payments"]
    failures = row["past_failed_payments"]
    amount = row["amount_due"]

    if reason == "network_timeout":
        if successes >= 2:
            prob = 0.72
            action = "retry_immediately"
            reasoning = f"Transient network issue for reliable customer ({successes} past successes); immediate retry ($0.00 cost) yields expected net value of ${amount * prob:.2f}."
        else:
            prob = 0.55
            action = "retry_in_3_days"
            reasoning = f"Network timeout for customer with brief history; retrying in 3 days ($0.00 cost) with estimated net value of ${amount * prob:.2f}."

    elif reason == "card_expired":
        if ltv >= 300 or amount >= 40:
            prob = 0.58
            action = "send_payment_update_email"
            cost = ACTION_COSTS["send_payment_update_email"]
            net_val = (amount * prob) - cost
            reasoning = f"Card expired for valuable customer (${ltv:,.2f} LTV); sending payment update email ($0.01 cost) yields high net value of ${net_val:.2f}."
        else:
            prob = 0.18
            action = "retry_in_3_days"
            reasoning = f"Card expired on low-LTV customer; retrying in 3 days for free ($0.00 cost) instead of sending email."

    elif reason == "card_declined_fraud_check":
        # Only escalate to human review ($5.00 cost) if amount is large enough ($50+) to cover cost
        expected_human_prob = 0.48
        human_cost = ACTION_COSTS["escalate_to_human_review"]
        expected_human_net = (amount * expected_human_prob) - human_cost

        if amount >= 45.0 and expected_human_net > 5.0:
            prob = expected_human_prob
            action = "escalate_to_human_review"
            reasoning = f"Fraud check decline on large charge (${amount:,.2f}); human review ($5.00 cost) justified by high expected net value (${expected_human_net:.2f})."
        else:
            prob = 0.10
            action = "retry_in_3_days"
            reasoning = f"Fraud decline on lower-amount charge (${amount:,.2f}); $5.00 human escalation cost exceeds expected recovery, falling back to 3-day retry."

    elif reason == "insufficient_funds":
        if failures >= 5 and ltv < 150 and amount < 30:
            prob = 0.0
            action = "do_not_pursue"
            reasoning = f"Low LTV (${ltv:,.2f}) with {failures} prior failures; expected recovery is negligible, writing off ($0.00 cost) to prevent chasing uncollectible debt."
        else:
            prob = 0.22
            action = "retry_in_3_days"
            reasoning = f"Insufficient funds failure; scheduling free retry in 3 days ($0.00 cost) allowing customer account replenishment."

    else:
        prob = 0.25
        action = "retry_in_3_days"
        reasoning = "Standard recovery retry in 3 days ($0.00 cost) based on payment risk profile."

    return {
        "action": action,
        "estimated_recovery_probability": round(prob, 2),
        "reasoning": reasoning,
        "decision_source": "rule_based_fallback",
    }


# ---------------------------------------------------------------------------
# LLM Execution with Retries & Fallback
# ---------------------------------------------------------------------------
def call_llm_with_resilience(row: pd.Series, client=None) -> dict:
    """
    Attempt LLM call with 2 retries & exponential backoff.
    Gracefully degrades to cost-aware rule fallback on rate limit or API error.
    """
    from groq import Groq

    api_key = os.environ.get("GROQ_API_KEY")
    if not client and api_key:
        client = Groq(api_key=api_key)

    if not client:
        return get_cost_aware_heuristic(row)

    user_prompt = f"""Analyze this failed payment and recommend the optimal recovery action considering action costs:

Customer ID: {row['customer_id']}
Customer Tenure: {row['customer_tenure_days']} days
Past Successful Payments: {row['past_successful_payments']}
Past Failed Payments: {row['past_failed_payments']}
Failure Reason: {row['failure_reason']}
Amount Due: ${row['amount_due']:,.2f}
Days Since Last Successful Payment: {row['days_since_last_successful_payment']}
Customer Lifetime Value (LTV): ${row['customer_ltv']:,.2f}
Customer Segment: {row['customer_segment']}

Respond with your JSON decision."""

    retries = 2
    backoff = 2.0

    for attempt in range(retries + 1):
        try:
            response = client.chat.completions.create(
                model="llama-3.1-8b-instant",
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt},
                ],
                response_format={"type": "json_object"},
                temperature=0.2,
                max_tokens=220,
                timeout=5.0,
            )


            content = response.choices[0].message.content.strip()
            result = json.loads(content)

            if result.get("action") in VALID_ACTIONS:
                result["decision_source"] = "llm"
                if "estimated_recovery_probability" not in result:
                    result["estimated_recovery_probability"] = 0.5
                return result

        except Exception as e:
            if attempt < retries:
                time.sleep(backoff)
                backoff *= 2
            else:
                break

    # Degrade gracefully to cost-aware heuristic on LLM rate-limit or error
    fallback = get_cost_aware_heuristic(row)
    fallback["reasoning"] += " [Fallback: API rate limit / offline fallback active]"
    return fallback


# ---------------------------------------------------------------------------
# Primary Decision Engine (Cached, Demo-Mode Aware)
# ---------------------------------------------------------------------------
def predict_payment_recovery(row: pd.Series, force_live: bool = False, db_path: str = DB_PATH) -> dict:
    """
    Main entry point for agent prediction.
    Executes explicit state machine planning, cost evaluation, and optional Razorpay link creation.
    """
    planner = RecoveryPlanner(row.to_dict())
    planner.diagnose(row["failure_reason"])

    demo_mode = os.environ.get("DEMO_MODE", "true").lower() == "true"
    f_hash = compute_feature_hash(row)

    # 1. Cache lookup
    cached = get_cached_decision(f_hash, db_path)
    if cached and not force_live:
        decision = dict(cached)
    elif demo_mode and not force_live:
        # 2. DEMO_MODE enforcement
        decision = get_cost_aware_heuristic(row)
        decision["decision_source"] = "cache"
        save_cached_decision(f_hash, row["customer_id"], decision, "cache", db_path)
    else:
        # 3. Live LLM execution
        decision = call_llm_with_resilience(row)
        save_cached_decision(f_hash, row["customer_id"], decision, decision.get("decision_source", "llm"), db_path)

    act = decision["action"]
    prob = decision.get("estimated_recovery_probability", 0.5)
    net_val = calculate_expected_net_value(row["amount_due"], prob, act)

    planner.evaluate_cost_tradeoff(net_val, prob)
    planner.select_action(act)
    planner.execute(decision.get("decision_source", "cache"))
    planner.complete()

    decision["state_sequence"] = planner.get_sequence()

    # Create Razorpay Payment Link for email prompt action
    if act == "send_payment_update_email":
        rzp_res = create_payment_link(row["amount_due"], row["customer_id"])
        decision["payment_link_url"] = rzp_res.get("short_url")
        decision["payment_link_id"] = rzp_res.get("payment_link_id")

    return decision


def run_agent(db_path: str = DB_PATH) -> pd.DataFrame:
    """Process all failed payments through the agent engine and write to SQLite."""
    conn = sqlite3.connect(db_path)
    df = pd.read_sql("SELECT * FROM failed_payments", conn)

    results = []
    print(f"🤖 Agent evaluating {len(df)} failed payments (Cost-Aware Engine) ...")

    for _, row in df.iterrows():
        decision = predict_payment_recovery(row, db_path=db_path)
        results.append(
            {
                "customer_id": row["customer_id"],
                "agent_action": decision["action"],
                "agent_estimated_prob": decision.get("estimated_recovery_probability", 0.5),
                "agent_reasoning": decision["reasoning"],
                "decision_source": decision.get("decision_source", "cache"),
            }
        )

    results_df = pd.DataFrame(results)
    results_df.to_sql("agent_results", conn, if_exists="replace", index=False)
    conn.close()

    print(f"✅ Agent evaluation complete. Action distribution:")
    print(results_df["agent_action"].value_counts().to_dict())
    print(f"   Decision sources: {results_df['decision_source'].value_counts().to_dict()}")
    return results_df


if __name__ == "__main__":
    run_agent()

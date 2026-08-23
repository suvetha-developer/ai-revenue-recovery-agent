"""
Step 5 — Outcome Simulation Engine (Cost-Aware & NET Revenue Focused)
Simulates recovery outcomes for agent decisions, computes realized NET revenue,
and logs every event to the audit_log table.
"""

import sqlite3
import os
import numpy as np
import pandas as pd
from src.cost_model import ACTION_COSTS, get_action_cost, calculate_realized_net_value
from src.audit import log_decision

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "payments.db")

ACTION_PROBS = {
    "retry_immediately": {
        "network_timeout": 0.72,
        "card_expired": 0.10,
        "insufficient_funds": 0.12,
        "card_declined_fraud_check": 0.08,
    },
    "retry_in_3_days": {
        "network_timeout": 0.55,
        "card_expired": 0.18,
        "insufficient_funds": 0.22,
        "card_declined_fraud_check": 0.10,
    },
    "send_payment_update_email": {
        "network_timeout": 0.30,
        "card_expired": 0.58,
        "insufficient_funds": 0.18,
        "card_declined_fraud_check": 0.15,
    },
    "escalate_to_human_review": {
        "network_timeout": 0.40,
        "card_expired": 0.35,
        "insufficient_funds": 0.30,
        "card_declined_fraud_check": 0.48,
    },
    "do_not_pursue": {
        "network_timeout": 0.0,
        "card_expired": 0.0,
        "insufficient_funds": 0.0,
        "card_declined_fraud_check": 0.0,
    },
}


def compute_agent_probability(row: pd.Series) -> float:
    action = row["agent_action"]
    reason = row["failure_reason"]

    base_p = ACTION_PROBS.get(action, {}).get(reason, 0.15)
    if action == "do_not_pursue":
        return 0.0

    ltv = row["customer_ltv"]
    if ltv > 1000:
        base_p += 0.06
    elif ltv > 500:
        base_p += 0.03

    tenure = row["customer_tenure_days"]
    if tenure > 500:
        base_p += 0.04
    elif tenure > 200:
        base_p += 0.02

    past_fails = row["past_failed_payments"]
    if past_fails > 10:
        base_p -= 0.12
    elif past_fails > 5:
        base_p -= 0.06

    days_since = row["days_since_last_successful_payment"]
    if days_since > 90:
        base_p -= 0.10
    elif days_since > 60:
        base_p -= 0.05

    if (
        action == "send_payment_update_email"
        and reason == "card_expired"
        and row["past_successful_payments"] > 5
    ):
        base_p += 0.08

    if (
        action == "escalate_to_human_review"
        and reason == "card_declined_fraud_check"
        and row["amount_due"] > 50
    ):
        base_p += 0.06

    return float(np.clip(base_p, 0.0, 0.92))


def run_simulation(db_path: str = DB_PATH, seed: int = 42) -> pd.DataFrame:
    np.random.seed(seed)

    conn = sqlite3.connect(db_path)
    payments = pd.read_sql("SELECT * FROM failed_payments", conn)
    agent = pd.read_sql("SELECT * FROM agent_results", conn)

    # Delete previous agent entries from audit_log
    conn.execute("DELETE FROM audit_log WHERE system = 'agent'")
    conn.commit()

    df = payments.merge(agent, on="customer_id", how="inner")

    df["agent_recovery_prob"] = df.apply(compute_agent_probability, axis=1)
    df["agent_recovered"] = (
        np.random.random(len(df)) < df["agent_recovery_prob"]
    ).astype(int)

    # Calculate action costs and realized net value
    df["action_cost"] = df["agent_action"].apply(get_action_cost)
    df["agent_net_value"] = df.apply(
        lambda r: calculate_realized_net_value(
            r["amount_due"], r["agent_recovered"], r["agent_action"]
        ),
        axis=1,
    )

    # Log each decision to audit_log table
    for _, row in df.iterrows():
        log_decision(
            customer_id=row["customer_id"],
            system="agent",
            decision_source=row.get("decision_source", "cache"),
            action=row["agent_action"],
            estimated_recovery_prob=row["agent_recovery_prob"],
            action_cost=row["action_cost"],
            reasoning=row["agent_reasoning"],
            recovered=int(row["agent_recovered"]),
            amount_due=row["amount_due"],
            db_path=db_path,
        )

    # Save to agent_outcomes table
    save_cols = [
        "customer_id",
        "customer_segment",
        "customer_tenure_days",
        "past_successful_payments",
        "past_failed_payments",
        "failure_reason",
        "amount_due",
        "days_since_last_successful_payment",
        "customer_ltv",
        "agent_action",
        "action_cost",
        "agent_reasoning",
        "decision_source",
        "agent_recovery_prob",
        "agent_recovered",
        "agent_net_value",
    ]
    df[save_cols].to_sql("agent_outcomes", conn, if_exists="replace", index=False)
    conn.close()

    recovered = df["agent_recovered"].sum()
    total = len(df)
    gross_rev = df.loc[df["agent_recovered"] == 1, "amount_due"].sum()
    total_costs = df["action_cost"].sum()
    net_rev = df["agent_net_value"].sum()

    print(f"✅ Agent outcome simulation complete.")
    print(f"   Recovered: {recovered}/{total} ({recovered / total * 100:.1f}%)")
    print(f"   Gross revenue: ${gross_rev:,.2f} | Costs: ${total_costs:,.2f} | NET revenue: ${net_rev:,.2f}")

    return df


def main():
    print("Simulating agent recovery outcomes...")
    run_simulation()


if __name__ == "__main__":
    main()

"""
Step 2 — Baseline Recovery Logic (Cost-Aware)
Applies a single rule to every failed payment: "retry after 3 days + generic email."
Cost: $0.00. Records decisions directly into SQLite and the audit_log table.
"""

import sqlite3
import os
import numpy as np
import pandas as pd
from src.cost_model import get_action_cost, calculate_realized_net_value
from src.audit import log_decision, init_audit_log

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "payments.db")

BASE_PROBABILITIES = {
    "network_timeout": 0.55,
    "card_expired": 0.20,
    "insufficient_funds": 0.15,
    "card_declined_fraud_check": 0.10,
}


def compute_baseline_probability(row: pd.Series) -> float:
    base_p = BASE_PROBABILITIES.get(row["failure_reason"], 0.15)
    days_since = row["days_since_last_successful_payment"]
    if days_since > 90:
        base_p -= 0.15
    elif days_since > 60:
        base_p -= 0.08

    past_fails = row["past_failed_payments"]
    if past_fails > 10:
        base_p -= 0.12
    elif past_fails > 5:
        base_p -= 0.07

    if row["customer_ltv"] > 1000:
        base_p += 0.04

    return float(np.clip(base_p, 0.02, 0.90))


def run_baseline(db_path: str = DB_PATH, seed: int = 42) -> pd.DataFrame:
    np.random.seed(seed)
    init_audit_log(db_path)

    conn = sqlite3.connect(db_path)
    df = pd.read_sql("SELECT * FROM failed_payments", conn)

    # Delete previous baseline entries from audit_log
    conn.execute("DELETE FROM audit_log WHERE system = 'baseline'")
    conn.commit()

    df["baseline_recovery_prob"] = df.apply(compute_baseline_probability, axis=1)
    df["baseline_recovered"] = (
        np.random.random(len(df)) < df["baseline_recovery_prob"]
    ).astype(int)
    df["baseline_action"] = "retry_in_3_days"
    df["baseline_action_cost"] = df["baseline_action"].apply(get_action_cost)
    df["baseline_net_value"] = df.apply(
        lambda r: calculate_realized_net_value(
            r["amount_due"], r["baseline_recovered"], r["baseline_action"]
        ),
        axis=1,
    )

    # Log each baseline decision to audit_log
    for _, row in df.iterrows():
        log_decision(
            customer_id=row["customer_id"],
            system="baseline",
            decision_source="rule_based_baseline",
            action="retry_in_3_days",
            estimated_recovery_prob=row["baseline_recovery_prob"],
            action_cost=0.00,
            reasoning="Naive baseline rule: apply standard 3-day retry to all failed payments without cost awareness.",
            recovered=int(row["baseline_recovered"]),
            amount_due=row["amount_due"],
            db_path=db_path,
        )

    # Save to baseline_results
    results = df[
        [
            "customer_id",
            "failure_reason",
            "amount_due",
            "customer_ltv",
            "baseline_action",
            "baseline_action_cost",
            "baseline_recovery_prob",
            "baseline_recovered",
            "baseline_net_value",
        ]
    ]
    results.to_sql("baseline_results", conn, if_exists="replace", index=False)
    conn.close()

    recovered = results["baseline_recovered"].sum()
    total = len(results)
    gross_rev = results.loc[results["baseline_recovered"] == 1, "amount_due"].sum()
    net_rev = results["baseline_net_value"].sum()

    print(f"✅ Baseline simulation complete.")
    print(f"   Recovered: {recovered}/{total} ({recovered/total*100:.1f}%)")
    print(f"   Gross revenue: ${gross_rev:,.2f} | NET revenue: ${net_rev:,.2f}")

    return results


def main():
    print("Running baseline simulation...")
    run_baseline()


if __name__ == "__main__":
    main()

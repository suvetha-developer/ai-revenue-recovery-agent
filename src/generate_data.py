"""
Step 1 — Synthetic Dataset Generator (Enhanced)
Generates ~500 realistic failed payment events in USD ($) and saves to SQLite.

Customer segments drive correlated features so distinct risk profiles emerge naturally.
"""

import sqlite3
import os
import random
import numpy as np
import pandas as pd
from datetime import datetime, timedelta

NUM_RECORDS = 500
DB_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")
DB_PATH = os.path.join(DB_DIR, "payments.db")

SEGMENTS = {
    "loyal_high_value": {
        "weight": 0.25,
        "tenure": (300, 1200),
        "successes": (10, 60),
        "failures": (0, 3),
        "ltv": (600, 3500),
        "amount": (49.99, 499.99),
        "reason_weights": {
            "card_expired": 0.40,
            "network_timeout": 0.35,
            "insufficient_funds": 0.10,
            "card_declined_fraud_check": 0.15,
        },
        "days_since_last_success": (1, 35),
    },
    "mid_tier_stable": {
        "weight": 0.30,
        "tenure": (90, 400),
        "successes": (3, 20),
        "failures": (1, 5),
        "ltv": (150, 1200),
        "amount": (29.99, 199.99),
        "reason_weights": {
            "card_expired": 0.25,
            "network_timeout": 0.25,
            "insufficient_funds": 0.30,
            "card_declined_fraud_check": 0.20,
        },
        "days_since_last_success": (5, 60),
    },
    "new_uncertain": {
        "weight": 0.25,
        "tenure": (7, 120),
        "successes": (0, 5),
        "failures": (1, 8),
        "ltv": (20, 300),
        "amount": (14.99, 99.99),
        "reason_weights": {
            "card_expired": 0.10,
            "network_timeout": 0.15,
            "insufficient_funds": 0.45,
            "card_declined_fraud_check": 0.30,
        },
        "days_since_last_success": (10, 90),
    },
    "churning": {
        "weight": 0.20,
        "tenure": (30, 300),
        "successes": (2, 10),
        "failures": (5, 15),
        "ltv": (30, 250),
        "amount": (9.99, 79.99),
        "reason_weights": {
            "card_expired": 0.10,
            "network_timeout": 0.10,
            "insufficient_funds": 0.55,
            "card_declined_fraud_check": 0.25,
        },
        "days_since_last_success": (30, 120),
    },
}


def noisy_int(low: int, high: int, noise_pct: float = 0.15) -> int:
    val = random.randint(low, high)
    noise = np.random.normal(0, val * noise_pct) if val > 0 else 0
    return max(0, int(val + noise))


def noisy_float(low: float, high: float, noise_pct: float = 0.12) -> float:
    val = random.uniform(low, high)
    noise = np.random.normal(0, val * noise_pct) if val > 0 else 0
    return max(1.0, round(val + noise, 2))


def generate_dataset(n: int = NUM_RECORDS, seed: int = 42) -> pd.DataFrame:
    random.seed(seed)
    np.random.seed(seed)

    records = []
    segment_names = list(SEGMENTS.keys())
    segment_weights = [SEGMENTS[s]["weight"] for s in segment_names]

    for i in range(1, n + 1):
        seg_name = random.choices(segment_names, weights=segment_weights, k=1)[0]
        seg = SEGMENTS[seg_name]

        tenure = noisy_int(*seg["tenure"])
        successes = noisy_int(*seg["successes"])
        failures = noisy_int(*seg["failures"])
        ltv = noisy_float(*seg["ltv"])
        amount = noisy_float(*seg["amount"])
        days_since = noisy_int(*seg["days_since_last_success"])

        reasons = list(seg["reason_weights"].keys())
        weights = list(seg["reason_weights"].values())
        failure_reason = random.choices(reasons, weights=weights, k=1)[0]

        base_date = datetime(2026, 8, 1, 12, 0, 0)
        failed_at = base_date - timedelta(
            days=random.uniform(0, 30),
            hours=random.randint(0, 23),
            minutes=random.randint(0, 59),
        )


        records.append(
            {
                "customer_id": f"CUST_{i:04d}",
                "customer_segment": seg_name,
                "customer_tenure_days": tenure,
                "past_successful_payments": successes,
                "past_failed_payments": failures,
                "failure_reason": failure_reason,
                "amount_due": amount,
                "days_since_last_successful_payment": days_since,
                "customer_ltv": ltv,
                "failed_at_timestamp": failed_at.isoformat(),
            }
        )

    return pd.DataFrame(records)


def save_to_sqlite(df: pd.DataFrame, db_path: str = DB_PATH) -> None:
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    conn = sqlite3.connect(db_path)
    df.to_sql("failed_payments", conn, if_exists="replace", index=False)
    conn.close()
    print(f"✅ Saved {len(df)} records to {db_path} -> table 'failed_payments'")


def main():
    print("Generating synthetic failed-payment dataset...")
    df = generate_dataset()
    save_to_sqlite(df)
    print(f"   Amount range: ${df['amount_due'].min():.2f} - ${df['amount_due'].max():.2f}")
    print(f"   LTV range   : ${df['customer_ltv'].min():.2f} - ${df['customer_ltv'].max():.2f}")


if __name__ == "__main__":
    main()

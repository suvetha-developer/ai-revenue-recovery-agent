"""
Pre-computed Demo Seeder Script (Step 10)
Generates the synthetic dataset, runs baseline and AI agent simulations,
populates the cache and audit logs, and prepares SQLite for instant zero-config demos.
"""

import os
from src.generate_data import generate_dataset, save_to_sqlite
from src.baseline import run_baseline
from src.agent import run_agent
from src.simulate_outcomes import run_simulation
from src.compare_results import run_comparison

from src.export_metrics import export_metrics_json

def seed_demo():
    print("=" * 65)
    print("🚀 SEEDING DEMO ENVIRONMENT (Pre-computing All Decisions)")
    print("=" * 65)

    # 0. Clean Audit Log
    db_path = os.path.join(os.path.dirname(__file__), "data", "payments.db")
    if os.path.exists(db_path):
        import sqlite3
        conn = sqlite3.connect(db_path)
        try:
            conn.execute("DELETE FROM audit_log")
            conn.commit()
        except Exception:
            pass
        conn.close()

    # 1. Generate Synthetic Dataset
    df = generate_dataset()
    save_to_sqlite(df)


    # 2. Run Baseline Simulation & Audit Log
    run_baseline()

    # 3. Run Agent Evaluation & Cache Population
    run_agent()

    # 4. Run Agent Outcome Simulation & Audit Log
    run_simulation()

    # 5. Run Comparison Metrics & Export JSON
    run_comparison()
    export_metrics_json()

    print("\n" + "=" * 65)
    print("✨ DEMO ENVIRONMENT FULLY SEEDED & READY!")
    print("   Database: data/payments.db")
    print("   Metrics : data/metrics_summary.json")
    print("   Both FastAPI microservice and Streamlit app can now run instantly!")
    print("=" * 65)


if __name__ == "__main__":
    seed_demo()

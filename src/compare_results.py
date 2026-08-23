"""
Step 5 & 6 — Comparison Analysis Module (NET Revenue & Audit Metrics)
Computes baseline vs agent recovery rates, gross revenue, action costs,
and NET revenue metrics for SQLite and dashboard consumption.
"""

import sqlite3
import os
import pandas as pd

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "payments.db")


def run_comparison(db_path: str = DB_PATH) -> dict:
    conn = sqlite3.connect(db_path)
    baseline = pd.read_sql("SELECT * FROM baseline_results", conn)
    agent = pd.read_sql("SELECT * FROM agent_outcomes", conn)

    # ---------------------------------------------------------------------------
    # Headline Metrics
    # ---------------------------------------------------------------------------
    b_total = len(baseline)
    b_recovered = int(baseline["baseline_recovered"].sum())
    b_rate = round(b_recovered / b_total * 100, 1) if b_total > 0 else 0.0
    b_gross_rev = round(baseline.loc[baseline["baseline_recovered"] == 1, "amount_due"].sum(), 2)
    b_costs = round(baseline["baseline_action_cost"].sum(), 2)
    b_net_rev = round(b_gross_rev - b_costs, 2)

    a_total = len(agent)
    a_recovered = int(agent["agent_recovered"].sum())
    a_rate = round(a_recovered / a_total * 100, 1) if a_total > 0 else 0.0
    a_gross_rev = round(agent.loc[agent["agent_recovered"] == 1, "amount_due"].sum(), 2)
    a_costs = round(agent["action_cost"].sum(), 2)
    a_net_rev = round(a_gross_rev - a_costs, 2)

    uplift_rate = round(a_rate - b_rate, 1)
    uplift_net_rev = round(a_net_rev - b_net_rev, 2)
    pct_net_improvement = round((a_net_rev - b_net_rev) / b_net_rev * 100, 1) if b_net_rev > 0 else 0.0

    headlines = {
        "baseline_total": b_total,
        "baseline_recovered": b_recovered,
        "baseline_rate": b_rate,
        "baseline_gross_revenue": b_gross_rev,
        "baseline_costs": b_costs,
        "baseline_net_revenue": b_net_rev,
        "agent_total": a_total,
        "agent_recovered": a_recovered,
        "agent_rate": a_rate,
        "agent_gross_revenue": a_gross_rev,
        "agent_costs": a_costs,
        "agent_net_revenue": a_net_rev,
        "uplift_rate_pts": uplift_rate,
        "uplift_net_revenue": uplift_net_rev,
        "pct_net_improvement": pct_net_improvement,
    }

    pd.DataFrame([headlines]).to_sql("comparison_headlines", conn, if_exists="replace", index=False)

    # ---------------------------------------------------------------------------
    # Breakdown by Failure Reason
    # ---------------------------------------------------------------------------
    merged = baseline[["customer_id", "failure_reason", "amount_due", "baseline_recovered", "baseline_net_value"]].merge(
        agent[["customer_id", "agent_action", "action_cost", "agent_recovered", "agent_net_value"]],
        on="customer_id",
        how="inner",
    )

    reason_breakdown = (
        merged.groupby("failure_reason")
        .agg(
            total=("customer_id", "count"),
            baseline_recovered=("baseline_recovered", "sum"),
            agent_recovered=("agent_recovered", "sum"),
            baseline_net_revenue=("baseline_net_value", "sum"),
            agent_net_revenue=("agent_net_value", "sum"),
            total_agent_costs=("action_cost", "sum"),
        )
        .reset_index()
    )

    reason_breakdown["baseline_rate"] = (reason_breakdown["baseline_recovered"] / reason_breakdown["total"] * 100).round(1)
    reason_breakdown["agent_rate"] = (reason_breakdown["agent_recovered"] / reason_breakdown["total"] * 100).round(1)
    reason_breakdown["uplift_net_revenue"] = (reason_breakdown["agent_net_revenue"] - reason_breakdown["baseline_net_revenue"]).round(2)

    reason_breakdown.to_sql("comparison_by_reason", conn, if_exists="replace", index=False)

    # ---------------------------------------------------------------------------
    # Breakdown by Customer Segment
    # ---------------------------------------------------------------------------
    merged_seg = agent[["customer_id", "customer_segment", "amount_due", "agent_action", "action_cost", "agent_recovered", "agent_net_value"]].merge(
        baseline[["customer_id", "baseline_recovered", "baseline_net_value"]],
        on="customer_id",
        how="inner",
    )

    seg_breakdown = (
        merged_seg.groupby("customer_segment")
        .agg(
            total=("customer_id", "count"),
            baseline_recovered=("baseline_recovered", "sum"),
            agent_recovered=("agent_recovered", "sum"),
            baseline_net_revenue=("baseline_net_value", "sum"),
            agent_net_revenue=("agent_net_value", "sum"),
        )
        .reset_index()
    )

    seg_breakdown["baseline_rate"] = (seg_breakdown["baseline_recovered"] / seg_breakdown["total"] * 100).round(1)
    seg_breakdown["agent_rate"] = (seg_breakdown["agent_recovered"] / seg_breakdown["total"] * 100).round(1)
    seg_breakdown["uplift_net_revenue"] = (seg_breakdown["agent_net_revenue"] - seg_breakdown["baseline_net_revenue"]).round(2)

    seg_breakdown.to_sql("comparison_by_segment", conn, if_exists="replace", index=False)

    # ---------------------------------------------------------------------------
    # Action Distribution
    # ---------------------------------------------------------------------------
    action_dist = (
        agent["agent_action"]
        .value_counts()
        .reset_index()
        .rename(columns={"index": "action", "agent_action": "action", "count": "count"})
    )
    action_dist.to_sql("action_distribution", conn, if_exists="replace", index=False)

    conn.close()

    print("=" * 65)
    print("📊 COST-AWARE COMPARISON RESULTS")
    print("=" * 65)
    print(f"  Baseline Recovery Rate : {b_rate:.1f}%  |  NET Revenue: ${b_net_rev:,.2f}")
    print(f"  Agent Recovery Rate    : {a_rate:.1f}%  |  NET Revenue: ${a_net_rev:,.2f}")
    print(f"  Total Action Costs     : Baseline: ${b_costs:.2f} | Agent: ${a_costs:.2f}")
    print(f"  Uplift in NET Revenue  : +${uplift_net_rev:,.2f}  ({pct_net_improvement:.1f}% improvement)")
    print("=" * 65)

    return headlines


def main():
    run_comparison()


if __name__ == "__main__":
    main()

"""
Audit Logger Module
Handles table creation and logging of every decision (baseline AND agent) to the SQLite audit_log table.
"""

import sqlite3
import os
from datetime import datetime
import uuid
import pandas as pd

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "payments.db")

CREATE_AUDIT_LOG_SQL = """
CREATE TABLE IF NOT EXISTS audit_log (
    decision_id TEXT PRIMARY KEY,
    customer_id TEXT,
    timestamp TEXT,
    system TEXT,                  -- 'baseline' or 'agent'
    decision_source TEXT,         -- 'llm', 'cache', or 'rule_based_fallback'
    action TEXT,
    estimated_recovery_prob REAL,
    action_cost REAL,
    reasoning TEXT,
    recovered INTEGER,            -- 0 or 1
    amount_recovered REAL,
    net_value REAL
);
"""


def init_audit_log(db_path: str = DB_PATH):
    """Ensure audit_log table exists."""
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.execute(CREATE_AUDIT_LOG_SQL)
    conn.commit()
    conn.close()


def log_decision(
    customer_id: str,
    system: str,
    decision_source: str,
    action: str,
    estimated_recovery_prob: float,
    action_cost: float,
    reasoning: str,
    recovered: int,
    amount_due: float,
    db_path: str = DB_PATH,
    timestamp: str = None,
) -> dict:
    """Record a single decision event to audit_log table."""
    init_audit_log(db_path)

    decision_id = f"DEC_{uuid.uuid4().hex[:10].upper()}"
    ts = timestamp or datetime.utcnow().isoformat()
    amount_rec = amount_due if recovered == 1 else 0.0
    net_val = round(amount_rec - action_cost, 2)

    entry = {
        "decision_id": decision_id,
        "customer_id": customer_id,
        "timestamp": ts,
        "system": system,
        "decision_source": decision_source,
        "action": action,
        "estimated_recovery_prob": round(estimated_recovery_prob, 3),
        "action_cost": round(action_cost, 2),
        "reasoning": reasoning,
        "recovered": int(recovered),
        "amount_recovered": round(amount_rec, 2),
        "net_value": net_val,
    }

    conn = sqlite3.connect(db_path)
    conn.execute(
        """
        INSERT INTO audit_log (
            decision_id, customer_id, timestamp, system, decision_source,
            action, estimated_recovery_prob, action_cost, reasoning,
            recovered, amount_recovered, net_value
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            entry["decision_id"],
            entry["customer_id"],
            entry["timestamp"],
            entry["system"],
            entry["decision_source"],
            entry["action"],
            entry["estimated_recovery_prob"],
            entry["action_cost"],
            entry["reasoning"],
            entry["recovered"],
            entry["amount_recovered"],
            entry["net_value"],
        ),
    )
    conn.commit()
    conn.close()
    return entry


def get_audit_trail_for_customer(customer_id: str, db_path: str = DB_PATH) -> pd.DataFrame:
    """Retrieve full audit trail for a customer."""
    init_audit_log(db_path)
    conn = sqlite3.connect(db_path)
    df = pd.read_sql(
        "SELECT * FROM audit_log WHERE customer_id = ? ORDER BY timestamp DESC",
        conn,
        params=(customer_id,),
    )
    conn.close()
    return df

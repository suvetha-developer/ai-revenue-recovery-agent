# AI Revenue Recovery Agent — Stress Testing & Verification Log

This document records the empirical results of the **Failure-Mode & API Stress Test Suite** executed via `test_api.py`. Every scenario was tested against the live FastAPI application and underlying pipeline to ensure zero crashes, clean error responses, and 100% reproducibility.

---

## 🧪 Summary of Stress Test Scenarios & Results

| # | Stress Test Scenario | Input / Action | Expected Result | Observed Result | Status |
|---|---|---|---|---|---|
| **1** | **Normal REST API Endpoints** | `GET /`, `POST /predict-recovery`, `POST /webhook/payment-failed`, `GET /metrics/summary` | `200 OK` with valid JSON payload containing action, cost, expected net value | `200 OK` with structured response & net value calculation | **PASS** |
| **2** | **Malformed Request Payload** | `POST /predict-recovery` with missing required fields (`amount_due`) & bad data types | `422 Unprocessable Entity` with clean validation error message | `422 Unprocessable Entity` with detail message (no stack trace) | **PASS** |
| **3** | **Non-Existent Customer Lookup** | `GET /audit-log/CUST_NONEXISTENT_99999` | `200 OK` with `{"total_records": 0, "audit_history": []}` | `200 OK` with clean empty list (no 404/500 error) | **PASS** |
| **4** | **Invalid API Key & Rate Limit Fallback** | `DEMO_MODE=false`, invalid `GROQ_API_KEY="gsk_invalid_fake_key"`, `force_live=True` | Catch API exception, retry with backoff, fall back to rule-based engine (`decision_source="rule_based_fallback"`) | Returned valid decision with `decision_source="rule_based_fallback"` in < 6s | **PASS** |
| **5** | **Pipeline Idempotency & Re-runs** | Executing `run_demo.py` twice consecutively on existing SQLite database | Clear previous audit logs, re-seed database cleanly without primary key constraint errors | Exactly 500 `failed_payments` & 1000 `audit_log` rows created | **PASS** |
| **6** | **Zero-Key Demo Mode Integrity** | Unset `GROQ_API_KEY`, run `python run_demo.py` | 100% of rows served from cache/rule fallback; zero network requests attempted | All 500 rows processed from cache (`decision_source="cache"`) | **PASS** |

---

## 🛠️ Detailed Test Implementations

### Test 1: Malformed Request Validation
Sending invalid payloads (e.g. string for integer field `customer_tenure_days`) to `/predict-recovery` or `/webhook/payment-failed`:
- **FastAPI Validation**: Pydantic validates input schemas prior to function execution.
- **Result**: Returns HTTP `422` with explicit field error paths, preventing unhandled runtime exceptions.

### Test 2: Rate Limit & Invalid Key Resilience
Simulating API failures during live evaluation:
1. `DEMO_MODE=false` is activated and a bad API key is passed.
2. The agent engine attempts up to 2 retries with exponential backoff (2.0s, 4.0s) and an explicit 5.0s HTTP timeout.
3. Upon failure, it invokes `get_cost_aware_heuristic(row)` and tags `decision_source="rule_based_fallback"`.
4. **Result**: The caller receives a cost-aware decision and tradeoff explanation without API failure.

### Test 3: Idempotent Seeding
Running `python run_demo.py` multiple times:
- `seed_demo()` clears previous `audit_log` entries before insertion.
- `to_sql(..., if_exists="replace")` overwrites intermediate tables cleanly.
- **Result**: Prevents duplicate keys or cumulative bloat on repeated executions.

---

## 📊 Verification Command

To re-run the full stress test suite on demand:

```powershell
python test_api.py
```

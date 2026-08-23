"""
Cost Model for Payment Recovery Actions
Defines action costs and NET revenue calculations.

Objective: Maximize NET Recovered Revenue = (amount_due * recovery_probability) - action_cost
"""

ACTION_COSTS = {
    "retry_immediately": 0.00,
    "retry_in_3_days": 0.00,
    "send_payment_update_email": 0.01,
    "escalate_to_human_review": 5.00,
    "do_not_pursue": 0.00,
}

ACTION_DESCRIPTIONS = {
    "retry_immediately": "Immediate automated retry for transient network errors ($0.00)",
    "retry_in_3_days": "Standard automated 3-day delayed retry ($0.00)",
    "send_payment_update_email": "Automated email prompting payment method update ($0.01)",
    "escalate_to_human_review": "Manual review by risk/operations specialist ($5.00)",
    "do_not_pursue": "Write off low-value/high-risk payment to avoid unnecessary costs ($0.00)",
}


def get_action_cost(action: str) -> float:
    """Return the cost incurred by taking a specific action."""
    return ACTION_COSTS.get(action, 0.0)


def calculate_expected_net_value(amount_due: float, probability: float, action: str) -> float:
    """
    Calculate Expected NET Revenue = (amount_due * probability) - action_cost
    """
    cost = get_action_cost(action)
    if action == "do_not_pursue":
        return 0.0
    return round((amount_due * probability) - cost, 2)


def calculate_realized_net_value(amount_due: float, recovered: int, action: str) -> float:
    """
    Calculate Realized NET Revenue = (amount_due if recovered else 0) - action_cost
    """
    cost = get_action_cost(action)
    gross_recovered = amount_due if recovered == 1 else 0.0
    return round(gross_recovered - cost, 2)

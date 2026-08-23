"""
RecoverAI Lightweight State Machine Planner
Tracks explicit agent state transitions:
RECEIVED -> DIAGNOSED -> COST_EVALUATED -> ACTION_SELECTED:<action> -> EXECUTED -> LOGGED
"""

from typing import List, Dict, Any


class RecoveryPlanner:
    def __init__(self, payment_event: Dict[str, Any]):
        self.payment_event = payment_event
        self.state_history: List[str] = []
        self.transition("RECEIVED")

    def transition(self, state_name: str):
        self.state_history.append(state_name)

    def diagnose(self, failure_reason: str) -> str:
        self.transition(f"DIAGNOSED:{failure_reason}")
        return failure_reason

    def evaluate_cost_tradeoff(self, net_value: float, prob: float):
        self.transition(f"COST_EVALUATED:net_${net_value:.2f}_prob_{int(prob*100)}%")

    def select_action(self, action_name: str):
        self.transition(f"ACTION_SELECTED:{action_name}")

    def execute(self, execution_mode: str):
        self.transition(f"EXECUTED:{execution_mode}")

    def complete(self):
        self.transition("LOGGED")

    def get_sequence(self) -> List[str]:
        return list(self.state_history)

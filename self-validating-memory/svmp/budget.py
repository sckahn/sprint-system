"""Budget economy: computation as a finite survival resource (§4.2).

Every operation deducts from a finite pool. A maintenance cost is charged each
round and *tightens* over time like a curriculum, so a purely passive agent runs
out of budget and "dies". Rewards are paid back into the budget, making compute a
currency the agent must earn.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field

from .config import BudgetConfig


class BudgetExhausted(RuntimeError):
    """Raised (optionally) when the budget would go negative — agent death."""


@dataclass
class BudgetEconomy:
    cfg: BudgetConfig
    balance: float = field(init=False)
    round: int = field(init=False, default=0)
    alive: bool = field(init=False, default=True)
    spent_by_reason: dict[str, float] = field(init=False)

    def __post_init__(self) -> None:
        self.balance = self.cfg.total
        self.spent_by_reason = defaultdict(float)

    # --- per-round maintenance (curriculum tightening) ---------------------
    @property
    def maintenance_cost(self) -> float:
        return self.cfg.maintenance_base + self.cfg.maintenance_growth * self.round

    def tick(self) -> None:
        """Advance one round and charge the (growing) maintenance cost."""
        self.round += 1
        self._deduct(self.maintenance_cost, "maintenance")

    # --- spending / earning ------------------------------------------------
    def spend(self, op: str) -> bool:
        """Charge the cost of a named operation. Returns False if it killed us."""
        cost = {
            "inference": self.cfg.cost_inference,
            "search": self.cfg.cost_search,
            "expert": self.cfg.cost_expert,
        }[op]
        return self._deduct(cost, op)

    def spend_experts(self, n: int) -> bool:
        return self._deduct(self.cfg.cost_expert * n, "expert")

    def earn(self, reward: float) -> None:
        """Pay reward back into the budget (reward may be negative)."""
        gain = reward * self.cfg.reward_to_budget
        self.balance += gain
        self.spent_by_reason["reward"] -= gain

    def _deduct(self, amount: float, reason: str) -> bool:
        self.balance -= amount
        self.spent_by_reason[reason] += amount
        if self.balance <= 0:
            self.alive = False
        return self.alive

    # --- introspection -----------------------------------------------------
    def snapshot(self) -> dict[str, float]:
        return {
            "round": self.round,
            "balance": round(self.balance, 3),
            "maintenance": round(self.maintenance_cost, 3),
            "alive": self.alive,
        }

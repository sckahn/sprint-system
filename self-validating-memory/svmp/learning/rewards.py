"""Reward topology: independent vs positional rewards (§4.5).

The design distinguishes two reward geometries:

- **Independent** (factual domains): each item is judged on its own — correct or
  not — with no dependence on other items. Think trivia / lookup.
- **Positional** (structural domains): reward depends on an item's *relational
  position* — ordering, consistency, or fit within a structure. A locally
  "correct" item can still be wrong if it breaks the global arrangement.

Both return a scalar reward in roughly [-1, 1] used by the neuromodulator and the
budget economy.
"""
from __future__ import annotations

import torch


class RewardTopology:
    def __init__(self, mode: str = "independent"):
        if mode not in ("independent", "positional"):
            raise ValueError(f"unknown reward mode: {mode}")
        self.mode = mode

    def __call__(self, prediction: int, target: int,
                 context: torch.Tensor | None = None,
                 order_target: list[int] | None = None,
                 history: list[int] | None = None) -> float:
        if self.mode == "independent":
            return self._independent(prediction, target)
        return self._positional(prediction, target, order_target, history)

    @staticmethod
    def _independent(prediction: int, target: int) -> float:
        return 1.0 if prediction == target else -1.0

    @staticmethod
    def _positional(prediction: int, target: int,
                    order_target: list[int] | None,
                    history: list[int] | None) -> float:
        """Reward correctness *and* consistency with the emerging structure.

        Half the reward is the local correct/incorrect signal; the other half
        rewards keeping the predicted sequence monotonically consistent with the
        target ordering (a simple stand-in for "structural fit").
        """
        local = 1.0 if prediction == target else -1.0
        if not history:
            return 0.5 * local
        # Structural term: did we preserve the target's relative order?
        prev = history[-1]
        if order_target is not None:
            try:
                consistent = order_target.index(prediction) > order_target.index(prev)
            except ValueError:
                consistent = False
        else:
            consistent = prediction >= prev
        structural = 1.0 if consistent else -1.0
        return 0.5 * local + 0.5 * structural

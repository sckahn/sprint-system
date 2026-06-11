"""Three-factor learning rule (§4.4).

    Δw_ij = η · e_ij · m · g

This is a *local* learning rule — not backpropagation. A weight changes only when
all three factors align:

    e (eligibility)     which synapses were recently active   → EligibilityTrace
    m (neuromodulator)  global reward prediction error        → Neuromodulator
    g (gate)            should we consolidate at all?          → ConsolidationGate

Because g is usually near 0, most rounds leave the weights untouched — plasticity
without catastrophic forgetting.

Note: REINFORCE is a special case of this rule with e = ∇log π(a|s),
m = reward − baseline, g = 1. We use that equivalence to make the demo task
actually learn while keeping the biological framing.
"""
from __future__ import annotations

import torch
import torch.nn as nn

from ..config import LearningConfig
from .eligibility import EligibilityTrace
from .gating import ConsolidationGate
from .neuromod import Neuromodulator


class ThreeFactorLearner:
    """Applies the three-factor rule to one ``nn.Linear`` layer.

    The eligibility trace is built from the layer's input (pre) and an
    output-side learning signal (post). For a policy/decision head the natural
    post signal is ``(onehot(action) − π)`` which makes the update equal to a
    reward-modulated REINFORCE step — a three-factor rule by construction.
    """

    def __init__(self, layer: nn.Linear, cfg: LearningConfig):
        self.layer = layer
        self.cfg = cfg
        self.elig = EligibilityTrace(layer.out_features, layer.in_features,
                                     cfg.eligibility_decay)
        self.neuromod = Neuromodulator(cfg)
        self.gate = ConsolidationGate(cfg)

    def observe(self, pre: torch.Tensor, post_signal: torch.Tensor) -> None:
        """Accumulate eligibility from this round's pre/post activity."""
        self.elig.accumulate(pre, post_signal)

    def update(self, external_reward: float, surprise: float, gap: float,
               source_quality: float) -> dict[str, float]:
        """Fire the three-factor update and return the factor values."""
        m = self.neuromod(external_reward)
        g = self.gate(surprise, gap, source_quality)
        dw = self.cfg.lr * m * g * self.elig.trace
        with torch.no_grad():
            self.layer.weight += dw
        return {
            "neuromod": round(m, 4),
            "gate": round(g, 4),
            "dw_norm": round(float(dw.norm()), 5),
        }

    def reset_episode(self) -> None:
        self.elig.reset()

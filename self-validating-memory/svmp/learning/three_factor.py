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
        # Benna-Fusi metaplastic consolidation buffer (per-weight, real-valued).
        # Inert unless cfg.metaplastic is True; allocated regardless so the
        # buffer survives episode resets and matches the weight tensor exactly.
        self.consol = torch.zeros_like(layer.weight)

    def observe(self, pre: torch.Tensor, post_signal: torch.Tensor) -> None:
        """Accumulate eligibility from this round's pre/post activity."""
        self.elig.accumulate(pre, post_signal)

    def update(self, external_reward: float, surprise: float, gap: float,
               source_quality: float,
               gate_override: float | None = None) -> dict[str, float]:
        """Fire the three-factor update and return the factor values.

        ``gate_override`` forces the gate value (e.g. 1.0 to ablate gating);
        ``self.gate.last`` is set to the value used so downstream consumers
        (the vault) see the same gate.
        """
        m = self.neuromod(external_reward)
        if gate_override is None:
            g = self.gate(surprise, gap, source_quality)
        else:
            g = gate_override
            self.gate.last = g
        dw = self.cfg.lr * m * g * self.elig.trace
        if self.cfg.metaplastic:
            # Benna-Fusi metaplasticity: synapses that have absorbed many gated
            # writes harden (large c) and resist further change — protecting old
            # task structure in the shared head (Zenke & Laborieux, §metaplasticity,
            # https://arxiv.org/abs/2405.16922). meta_eps keeps the first write
            # at full magnitude (1/(0+eps) = 1 when eps=1).
            dw = dw / (self.consol + self.cfg.meta_eps)
        with torch.no_grad():
            self.layer.weight += dw
            if self.cfg.metaplastic:
                # Consolidate proportionally to how strongly the gate fired and
                # how large the (already metaplastically-scaled) write was.
                self.consol += self.cfg.meta_alpha * g * dw.abs()
        return {
            "neuromod": round(m, 4),
            "gate": round(g, 4),
            "dw_norm": round(float(dw.norm()), 5),
        }

    def reset_episode(self) -> None:
        self.elig.reset()

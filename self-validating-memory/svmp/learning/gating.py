"""Consolidation gate: the *third* factor (§4.4).

Not every input should modify weights. The gate g ∈ [0, 1] opens when there is a
reason to consolidate — high surprise, a knowledge gap, and trustworthy external
evidence — and stays mostly closed otherwise. A closed gate ⇒ no weight change
and no vault write, which is what protects established knowledge from
catastrophic interference.

    g = σ( b + a_surprise·surprise + a_gap·gap + a_source·source_quality )
"""
from __future__ import annotations

import math

from ..config import LearningConfig


class ConsolidationGate:
    def __init__(self, cfg: LearningConfig):
        self.cfg = cfg
        self.last = 0.0

    def __call__(self, surprise: float, gap: float, source_quality: float) -> float:
        """Compute the gate.

        - ``surprise``: prediction error magnitude in [0, 1] (e.g. 1 - p(correct))
        - ``gap``: vault gap signal in [0, 1] (1 ⇒ unknown, must verify)
        - ``source_quality``: verifier's source trust in [0, 1] (0 if no search)
        """
        z = (
            self.cfg.gate_bias
            + self.cfg.gate_surprise_coef * surprise
            + self.cfg.gate_gap_coef * gap
            + self.cfg.gate_source_coef * source_quality
        )
        g = 1.0 / (1.0 + math.exp(-z))
        # A gap with no trustworthy source must NOT open the gate: we refuse to
        # consolidate unverified guesses (the system's weakest part is exactly
        # source-quality assessment — so we are conservative here).
        if gap > 0.5 and source_quality < 0.3:
            g *= 0.2
        self.last = g
        return g

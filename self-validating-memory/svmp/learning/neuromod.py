"""Neuromodulator: the *second* factor — a global, signed reward signal (§4.4).

Biologically dopamine-like: it broadcasts a scalar ``reward − baseline`` to every
synapse. The baseline is a slow running average, so the signal encodes a reward
*prediction error* (positive when better than expected, negative when worse).

Crucially, the agent cannot define this reward internally — it must come from an
external verifier or adversarial role separation (Design principle: external
verification).
"""
from __future__ import annotations

from .. config import LearningConfig


class Neuromodulator:
    def __init__(self, cfg: LearningConfig):
        self.cfg = cfg
        self.baseline = 0.0
        self.last = 0.0

    def __call__(self, external_reward: float) -> float:
        """Return the modulator m = reward − baseline and update the baseline."""
        m = external_reward - self.baseline
        d = self.cfg.neuromod_baseline_decay
        self.baseline = d * self.baseline + (1 - d) * external_reward
        self.last = m
        return m

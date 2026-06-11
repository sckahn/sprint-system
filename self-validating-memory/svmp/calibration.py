"""Confidence calibration and Jeopardy-style betting (§4.6, Phase 1).

The system must not just answer — it must *know how much it knows*. The
calibration head emits a confidence p̂ alongside each decision. In the Jeopardy
betting scheme the agent stakes an amount proportional to its confidence:

    reward = +stake   if correct
             −stake   if wrong

This makes over-confidence costly and under-confidence wasteful, so the only
optimal policy is to report *calibrated* confidence. ECE measures how far off it
is.
"""
from __future__ import annotations

import torch
import torch.nn as nn


class CalibrationHead(nn.Module):
    """Maps a decision feature to a confidence in [0, 1]."""

    def __init__(self, dim: int):
        super().__init__()
        self.net = nn.Sequential(nn.Linear(dim, dim // 2 or 1), nn.GELU(),
                                 nn.Linear(dim // 2 or 1, 1))

    def forward(self, feat: torch.Tensor) -> torch.Tensor:
        return torch.sigmoid(self.net(feat)).squeeze(-1)


def jeopardy_reward(correct: bool, confidence: float,
                    max_stake: float = 1.0) -> float:
    """Stake ∝ confidence; win it if correct, lose it if wrong."""
    stake = max_stake * confidence
    return stake if correct else -stake


class ECEMeter:
    """Streaming Expected Calibration Error over (confidence, correct) pairs."""

    def __init__(self, n_bins: int = 10):
        self.n_bins = n_bins
        self.conf_sum = [0.0] * n_bins
        self.correct_sum = [0.0] * n_bins
        self.count = [0] * n_bins

    def update(self, confidence: float, correct: bool) -> None:
        b = min(int(confidence * self.n_bins), self.n_bins - 1)
        self.conf_sum[b] += confidence
        self.correct_sum[b] += 1.0 if correct else 0.0
        self.count[b] += 1

    def compute(self) -> float:
        total = sum(self.count)
        if total == 0:
            return 0.0
        ece = 0.0
        for b in range(self.n_bins):
            if self.count[b]:
                avg_conf = self.conf_sum[b] / self.count[b]
                acc = self.correct_sum[b] / self.count[b]
                ece += self.count[b] / total * abs(avg_conf - acc)
        return ece

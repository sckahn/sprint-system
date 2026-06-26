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

from collections import deque

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


# --- Calibrated selective-prediction scores (opt-in uncertainty gate) --------
#
# Free functions that turn a logit/probability vector into a single uncertainty
# scalar. They drive the calibration-gated verification trigger: instead of
# spending the costly Verifier search only on a binary vault-miss, we can spend
# it whenever the predictive distribution is *uncertain*. Each is a single-pass
# torch op over one logit/prob vector (shape ``(n_classes,)``).
#
# Reference: Gupta et al., "Calibrated selective classification" / selective
# scores entropy・margin・Gini (https://arxiv.org/pdf/2401.12708). Higher score
# = more uncertain = more likely to abstain / verify.


def entropy_score(logits: torch.Tensor) -> float:
    """Normalized predictive entropy of softmax(logits), in [0, 1].

    H(p) / log(K): 0 for a one-hot (peaked) distribution, 1 for the uniform
    one. ``K`` is the number of classes; K=1 is treated as fully certain (0).
    높을수록 불확실 ⇒ 검증(verify)을 유발한다.
    """
    p = torch.softmax(logits.flatten(), dim=0)
    k = p.numel()
    if k <= 1:
        return 0.0
    h = -(p * torch.log(p.clamp_min(1e-12))).sum()
    return float(h / torch.log(torch.tensor(float(k))))


def margin_score(logits: torch.Tensor) -> float:
    """top1 − top2 of softmax(logits): the confidence *margin* in [0, 1].

    Large margin ⇒ certain; a tie gives 0. Note this is a *confidence* (not an
    uncertainty) signal — abstain when it is *small*. K=1 ⇒ margin 1.0.
    """
    p = torch.softmax(logits.flatten(), dim=0)
    if p.numel() == 1:
        return 1.0
    top2 = torch.topk(p, 2).values
    return float(top2[0] - top2[1])


def gini_score(probs: torch.Tensor) -> float:
    """Gini impurity 1 − Σ pᵢ² of a probability vector, in [0, 1−1/K].

    Expects an already-normalized distribution. 0 for one-hot, 1−1/K for
    uniform. A single-pass impurity measure of predictive spread.
    """
    p = probs.flatten()
    return float(1.0 - (p * p).sum())


class ConformalThreshold:
    """Split-conformal abstention threshold with optional ACI online update.

    Buffers nonconformity scores ``s = 1 − conf`` of recent decisions in a
    sliding window and exposes the empirical (1−α) conformal quantile. A new
    decision *abstains* (here: triggers verification) when its nonconformity
    meets or exceeds that quantile, which controls the error rate on the
    *accepted* (non-abstained) set near α.

    When ``online`` is set, α itself is adapted by Adaptive Conformal Inference
    (ACI): αₜ₊₁ = αₜ + γ·(α − errₜ), where errₜ ∈ {0, 1} is whether the last
    decision was wrong. This tracks the target coverage under distribution drift
    (e.g. a label-permutation switch).

    References: split-conformal abstention
    (https://www.emergentmind.com/topics/conformal-abstention); Gibbs & Candès,
    Adaptive Conformal Inference. Defaults are inert: an empty buffer never
    abstains, so wiring this in without feeding it leaves behaviour unchanged.
    """

    def __init__(self, alpha: float = 0.1, window: int = 500,
                 online: bool = False, gamma: float = 0.01):
        self.alpha0 = alpha          # target miscoverage (fixed reference)
        self.alpha = alpha           # current (possibly ACI-adapted) level
        self.online = online
        self.gamma = gamma
        self.scores: deque[float] = deque(maxlen=window)

    def update(self, conf: float, correct: bool) -> None:
        """Buffer one nonconformity s = 1 − conf and (if online) step α via ACI."""
        self.scores.append(1.0 - float(conf))
        if self.online:
            err = 0.0 if correct else 1.0
            # αₜ₊₁ = αₜ + γ·(α − errₜ); keep α in (0, 1) so the quantile is valid.
            self.alpha = min(0.999, max(1e-3,
                                        self.alpha + self.gamma * (self.alpha0 - err)))

    def quantile(self) -> float:
        """Empirical (1−α)(1+1/n) conformal quantile of buffered nonconformity.

        Uses the finite-sample-corrected rank ⌈(1−α)(n+1)⌉ clamped to the
        buffer. Returns +inf on an empty buffer ⇒ never abstain (safe default).
        """
        n = len(self.scores)
        if n == 0:
            return float("inf")
        s = sorted(self.scores)
        level = (1.0 - self.alpha) * (1.0 + 1.0 / n)
        if level >= 1.0:
            return s[-1]
        rank = max(0, min(n - 1, int(level * n)))  # 0-based clamped index
        return s[rank]

    def should_abstain(self, conf: float) -> bool:
        """Abstain (⇒ verify) when nonconformity 1 − conf ≥ the conformal quantile.

        Empty buffer ⇒ quantile is +inf ⇒ never abstains (safe no-op default).
        """
        return (1.0 - float(conf)) >= self.quantile()


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

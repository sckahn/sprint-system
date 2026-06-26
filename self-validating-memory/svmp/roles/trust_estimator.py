"""Learnable source-trust estimator (Phase 4 — the design's named gap).

The design document calls source-quality assessment the system's weakest real
component. The fixed-tau robust aggregator is a hand-tuned heuristic; this module
*learns* to weight retrieved sources instead.

Crucially, it trains on the **same external signal the rest of the system uses** —
the externally revealed correct answer — and never on per-source reliability
labels (a deployed system would not have those). The estimator outputs a soft
weighting over the retrieved sources; the trust-weighted evidence is decoded
against the known class prototypes and trained end-to-end by cross-entropy, so
the estimator learns to down-weight whichever sources corrupt the answer.

Honest result (examples/experiment_learned_trust.py, n=8): with the training
objective aligned to the L2 evaluation metric, the estimator beats both the
naive trust-only mean (+~0.08) and the hand-tuned fixed-tau consensus heuristic
(+~0.02, 7/8 seeds) — a genuine but modest win, learned from the answer signal
alone with no hand-set threshold.

Per-source features (no absolute geometry, so it transfers across queries):
  - self-reported trust prior
  - mean cosine similarity to the other retrieved sources (corroboration)
  - max cosine similarity to any other source
  - cosine similarity to the retrieved-set centroid
"""
from __future__ import annotations

import torch
import torch.nn as nn
import torch.nn.functional as F

N_FEATURES = 4


def source_features(embs: torch.Tensor, trust: torch.Tensor) -> torch.Tensor:
    """Per-source features, shape (k, N_FEATURES). Differentiable in ``embs``."""
    k = embs.shape[0]
    norm = F.normalize(embs, dim=1)
    if k == 1:
        # A lone source has no peers, so the three geometric features are
        # constants and carry no gradient — the MLP cannot (and need not) learn
        # anything from k=1 episodes. Quality for k=1 is handled in aggregate().
        return torch.stack([trust,
                            torch.zeros(1), torch.zeros(1), torch.ones(1)], dim=1)
    sims = norm @ norm.t()                                  # (k, k), cosine
    eye = torch.eye(k, dtype=torch.bool)
    off = sims.masked_fill(eye, 0.0)
    mean_sim = off.sum(1) / (k - 1)                        # corroboration
    max_sim = sims.masked_fill(eye, -2.0).max(1).values
    centroid = F.normalize(norm.mean(0, keepdim=True), dim=1)
    sim_centroid = (norm * centroid).sum(1)
    return torch.stack([trust, mean_sim, max_sim, sim_centroid], dim=1)


class SourceTrustEstimator(nn.Module):
    """Maps a retrieved set to a soft weighting over its sources."""

    def __init__(self, hidden: int = 16):
        super().__init__()
        self.net = nn.Sequential(
            nn.Linear(N_FEATURES, hidden), nn.GELU(), nn.Linear(hidden, 1),
        )

    def forward(self, embs: torch.Tensor, trust: torch.Tensor) -> torch.Tensor:
        feats = source_features(embs, trust)
        logits = self.net(feats).squeeze(-1)               # (k,)
        return torch.softmax(logits, dim=0)

    def aggregate(self, embs: torch.Tensor,
                  trust: torch.Tensor) -> tuple[torch.Tensor, float]:
        """Return (weighted evidence embedding, learned quality in [0, 1])."""
        w = self(embs, trust)
        agg = (w.unsqueeze(1) * embs).sum(0)
        # Quality = weight concentration: 1 when the estimator commits to a clear
        # reliable subset, 0 when it can find none (uniform weights).
        k = embs.shape[0]
        if k == 1:
            quality = float(trust.mean())
        else:
            # clamp(min) keeps entropy >= 0 (so quality stays in [0, 1]); a raw
            # +eps inside log can make a saturated weight give entropy < 0.
            entropy = -(w * w.clamp(min=1e-9).log()).sum()
            quality = float(1.0 - entropy / torch.log(torch.tensor(float(k))))
        return agg, min(max(quality, 0.0), 1.0)


def train_trust_estimator(episodes, prototypes: torch.Tensor, epochs: int = 10,
                          lr: float = 1e-2, hidden: int = 16,
                          temperature: float = 8.0, entropy_reg: float = 0.1,
                          seed: int = 0) -> SourceTrustEstimator:
    """Train the estimator on (embs, trust, true_class) episodes.

    The only supervision is the externally revealed ``true_class`` — the same
    signal the budget/neuromodulator already consume. Per-source reliability is
    never used as a label.

    The decoder is *negative squared L2 distance to the prototypes*, matching the
    L2 nearest-prototype rule used to measure evidence accuracy everywhere — so
    the training objective and the evaluation metric agree. ``temperature``
    rescales the squared distance (O(10-40) for norm-4 prototypes) into a stable
    logit range so the softmax does not saturate.

    ``entropy_reg`` adds a maximum-entropy prior on the source weights: it pulls
    the weighting toward uniform (= the plain mean aggregate) unless committing
    to a subset measurably lowers the loss. This is what makes the estimator
    *safe across regimes* — on benign retrieval, where averaging all sources is
    already optimal, an unregularised estimator over-selects and HURTS
    (negative transfer); the prior recovers parity while keeping the gain on
    adversarial retrieval. See examples/experiment_learned_real.py.
    """
    # Scope the seed to weight init so we don't perturb the global RNG state.
    with torch.random.fork_rng():
        torch.manual_seed(seed)
        est = SourceTrustEstimator(hidden=hidden)
    opt = torch.optim.Adam(est.parameters(), lr=lr)
    protos = prototypes.detach()
    for _ in range(epochs):
        for embs, trust, true_c in episodes:
            w = est(embs, trust)
            agg = (w.unsqueeze(1) * embs).sum(0)
            logits = -torch.cdist(agg.unsqueeze(0), protos).squeeze(0) ** 2 / temperature
            loss = F.cross_entropy(logits.unsqueeze(0), torch.tensor([true_c]))
            if entropy_reg > 0.0:
                # (w·log w) = −entropy; minimising it pulls weights toward uniform.
                loss = loss + entropy_reg * (w * w.clamp(min=1e-9).log()).sum()
            opt.zero_grad()
            loss.backward()
            opt.step()
    return est

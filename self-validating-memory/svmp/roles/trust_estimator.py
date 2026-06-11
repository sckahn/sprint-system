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

Honest result (examples/experiment_learned_trust.py, n=8): the estimator beats
the naive trust-only mean (+~0.04) but does NOT beat the hand-tuned fixed-tau
consensus heuristic. Learning from the answer signal alone recovers the easy
win, not the hard one — consistent with the design's warning that source-quality
assessment is the weakest real component.

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
            entropy = -(w * (w + 1e-9).log()).sum()
            quality = float(1.0 - entropy / torch.log(torch.tensor(float(k))))
        return agg, quality


def train_trust_estimator(episodes, prototypes: torch.Tensor, epochs: int = 10,
                          lr: float = 1e-2, hidden: int = 16,
                          seed: int = 0) -> SourceTrustEstimator:
    """Train the estimator on (embs, trust, true_class) episodes.

    The only supervision is the externally revealed ``true_class`` — the same
    signal the budget/neuromodulator already consume. Per-source reliability is
    never used as a label.
    """
    torch.manual_seed(seed)
    est = SourceTrustEstimator(hidden=hidden)
    opt = torch.optim.Adam(est.parameters(), lr=lr)
    protos = F.normalize(prototypes.detach(), dim=1)
    for _ in range(epochs):
        for embs, trust, true_c in episodes:
            w = est(embs, trust)
            agg = (w.unsqueeze(1) * embs).sum(0)
            # Decode in cosine space with a temperature: bounded, stable logits
            # (raw squared distance with norm-4 prototypes saturates softmax).
            logits = (protos @ F.normalize(agg, dim=0)) / 0.1
            loss = F.cross_entropy(logits.unsqueeze(0),
                                   torch.tensor([true_c]))
            opt.zero_grad()
            loss.backward()
            opt.step()
    return est

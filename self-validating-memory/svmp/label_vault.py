"""Decay-protected verified-fact memory that votes directly into the logits.

Motivated by the Phase-6 diagnosis (`examples/diagnose_forgetting.py`):

  * Forgetting lives mainly in the backprop *representation*, which re-specialises
    onto the new task (restoring it alone recovers ~0.88 of lost task-A accuracy).
  * The vault *keys* barely drift across tasks (nearest-key cosine -0.03), so an
    encoder-keyed memory still reliably recognises old-task inputs.

The original vault failed to protect old tasks because its retrieved value is
only fused as *soft context* and then flows through the drifted representation.
``LabelVault`` instead stores the externally **verified class** for a region of
input space and casts a conviction-weighted vote *directly onto the logits*,
bypassing the representation entirely. Verified entries are never decayed, so
task-A facts survive task-B training.

This is a faithful realisation of the design's own principle — "verified
knowledge is consolidated and retrieved to inform decisions" — wired so it can
actually reach the decision.
"""
from __future__ import annotations

import torch
import torch.nn.functional as F


class LabelVault:
    def __init__(self, dim: int, n_classes: int, sim_threshold: float = 0.55,
                 merge_threshold: float = 0.9, conviction_lr: float = 0.3,
                 top_k: int = 3):
        self.dim = dim
        self.n_classes = n_classes
        self.sim_threshold = sim_threshold
        self.merge_threshold = merge_threshold
        self.conviction_lr = conviction_lr
        self.top_k = top_k
        self.keys = torch.zeros(0, dim)
        self.labels = torch.zeros(0, dtype=torch.long)
        self.conviction = torch.zeros(0)

    def __len__(self) -> int:
        return self.keys.shape[0]

    def _cosine(self, q: torch.Tensor) -> torch.Tensor:
        return F.cosine_similarity(self.keys, q.unsqueeze(0), dim=1)

    def write(self, key: torch.Tensor, label: int, gate: float) -> str:
        """Store a verified (region → class) fact. Gated like all consolidation.

        Merges into a nearby entry of the *same* class (strengthening conviction);
        otherwise appends. Never decays — verified facts are permanent.
        """
        if gate <= 0.0:
            return "skipped"
        key = key.detach().flatten()
        if len(self) > 0:
            sims = self._cosine(key)
            best = int(torch.argmax(sims))
            if float(sims[best]) >= self.merge_threshold and int(self.labels[best]) == label:
                a = self.conviction_lr * gate
                self.conviction[best] = float(torch.clamp(
                    self.conviction[best] + a * (1.0 - self.conviction[best]), 0.0, 1.0))
                self.keys[best] = F.normalize(
                    (1 - a) * self.keys[best] + a * key, dim=0) * self.keys[best].norm()
                return "strengthen"
        self.keys = torch.cat([self.keys, key.unsqueeze(0)], dim=0)
        self.labels = torch.cat([self.labels, torch.tensor([label])])
        self.conviction = torch.cat([self.conviction,
                                     torch.tensor([self.conviction_lr * gate])])
        return "add"

    @torch.no_grad()
    def vote(self, query: torch.Tensor) -> torch.Tensor:
        """Conviction-weighted class vote for ``query`` (zeros if no confident match)."""
        vote = torch.zeros(self.n_classes)
        if len(self) == 0:
            return vote
        sims = self._cosine(query.detach().flatten())
        k = min(self.top_k, len(self))
        top_sim, top_idx = torch.topk(sims, k)
        for s, i in zip(top_sim, top_idx):
            if float(s) < self.sim_threshold:
                continue
            vote[int(self.labels[i])] += float(s) * float(self.conviction[i])
        return vote

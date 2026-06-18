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

**Context keys (Phase-6 part 4).** A context-free input→label memory cannot serve
*conflicting* mappings — when the same input region has different correct answers
in different tasks (domain-incremental), the vote commits to one task arbitrarily
(`experiment_forgetting_limits.py`). Passing a ``context`` vector tags each entry
and gates the vote by context similarity, so an entry only contributes when both
the input region *and* the context match. With a distinct context per task this
resolves the conflict; the open problem is inferring that context without a task
oracle (`experiment_context_key.py`).
"""
from __future__ import annotations

import torch
import torch.nn.functional as F


class LabelVault:
    def __init__(self, dim: int, n_classes: int, sim_threshold: float = 0.55,
                 merge_threshold: float = 0.9, conviction_lr: float = 0.3,
                 top_k: int = 3, ctx_dim: int = 0, ctx_threshold: float = 0.5):
        self.dim = dim
        self.n_classes = n_classes
        self.sim_threshold = sim_threshold
        self.merge_threshold = merge_threshold
        self.conviction_lr = conviction_lr
        self.top_k = top_k
        self.ctx_dim = ctx_dim
        self.ctx_threshold = ctx_threshold
        self.keys = torch.zeros(0, dim)
        self.labels = torch.zeros(0, dtype=torch.long)
        self.conviction = torch.zeros(0)
        self.contexts = torch.zeros(0, ctx_dim) if ctx_dim > 0 else None

    def __len__(self) -> int:
        return self.keys.shape[0]

    def _cosine(self, q: torch.Tensor) -> torch.Tensor:
        return F.cosine_similarity(self.keys, q.unsqueeze(0), dim=1)

    def _ctx(self, context):
        if self.ctx_dim == 0 or context is None:
            return None
        return context.detach().flatten()

    def write(self, key: torch.Tensor, label: int, gate: float,
              context=None) -> str:
        """Store a verified (region → class[, context]) fact. Gated as usual.

        Merges into a nearby entry of the *same* class **and matching context**
        (strengthening conviction); otherwise appends. Never decays.
        """
        if gate <= 0.0:
            return "skipped"
        key = key.detach().flatten()
        ctx = self._ctx(context)
        if len(self) > 0:
            sims = self._cosine(key)
            best = int(torch.argmax(sims))
            ctx_ok = (ctx is None or
                      float(F.cosine_similarity(self.contexts[best], ctx, dim=0))
                      >= self.ctx_threshold)
            if (float(sims[best]) >= self.merge_threshold
                    and int(self.labels[best]) == label and ctx_ok):
                a = self.conviction_lr * gate
                self.conviction[best] = float(torch.clamp(
                    self.conviction[best] + a * (1.0 - self.conviction[best]), 0.0, 1.0))
                self.keys[best] = F.normalize(
                    (1 - a) * self.keys[best] + a * key, dim=0) * self.keys[best].norm()
                if ctx is not None:
                    self.contexts[best] = (1 - a) * self.contexts[best] + a * ctx
                return "strengthen"
        self.keys = torch.cat([self.keys, key.unsqueeze(0)], dim=0)
        self.labels = torch.cat([self.labels, torch.tensor([label])])
        self.conviction = torch.cat([self.conviction,
                                     torch.tensor([self.conviction_lr * gate])])
        if self.ctx_dim > 0:
            row = (ctx if ctx is not None else torch.zeros(self.ctx_dim)).unsqueeze(0)
            self.contexts = torch.cat([self.contexts, row], dim=0)
        return "add"

    @torch.no_grad()
    def vote(self, query: torch.Tensor, context=None) -> torch.Tensor:
        """Conviction-weighted class vote, gated by region *and* context match.

        With ``context=None`` this is the plain region vote (back-compatible). With
        a context vector, each entry's contribution is scaled by the (non-negative)
        cosine between its stored context and ``context`` — so mismatched-context
        entries are suppressed and conflicting mappings no longer cancel.
        """
        vote = torch.zeros(self.n_classes)
        if len(self) == 0:
            return vote
        sims = self._cosine(query.detach().flatten())
        ctx = self._ctx(context)
        if ctx is not None:
            cgate = F.cosine_similarity(self.contexts, ctx.unsqueeze(0), dim=1).clamp(min=0)
        else:
            cgate = torch.ones(len(self))
        score = sims.clamp(min=0) * cgate
        k = min(self.top_k, len(self))
        _, top_idx = torch.topk(score, k)
        for i in top_idx:
            i = int(i)
            if float(sims[i]) < self.sim_threshold:
                continue
            if ctx is not None and float(cgate[i]) <= 0:
                continue
            vote[int(self.labels[i])] += (float(sims[i]) * float(self.conviction[i])
                                          * float(cgate[i]))
        return vote

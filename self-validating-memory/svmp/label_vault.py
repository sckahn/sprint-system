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
    def realign_region(self, region_key: torch.Tensor,
                       sim_threshold: float | None = None) -> int:
        """Selectively prune entries of a *drifted* input region (opt-in AMR).

        Adaptive Memory Realignment (Ashrafee et al. 2025, "Holistic Continual
        Learning under Concept Drift with Adaptive Memory Realignment",
        https://arxiv.org/abs/2507.02310): under concept drift the *correct* label
        of a region changes, so the never-forget vault now holds a stale fact that
        out-votes the (correct) re-learned model. Rather than blanket-decay every
        entry — which also erases unflipped regions the vault still protects — AMR
        선택적으로(selectively) removes only the outdated entries of the drifted
        region and lets subsequent verified writes repopulate it with the new
        mapping.

        Entries whose key is *similar* to ``region_key`` (cosine ≥ ``thr``) are the
        drifted region and get dropped; everything below threshold is kept. Uses the
        same masked-index reindex as :meth:`vault.GrowingVault.decay`. Returns the
        number of pruned entries. With the default never-forget agent (``amr=False``)
        this is never called, so semantics are unchanged.
        """
        if len(self) == 0:
            return 0
        thr = sim_threshold or self.merge_threshold
        sims = self._cosine(region_key.detach().flatten())
        keep = sims < thr
        pruned = int((~keep).sum())
        if pruned:
            self.keys = self.keys[keep]
            self.labels = self.labels[keep]
            self.conviction = self.conviction[keep]
            if self.ctx_dim > 0:
                self.contexts = self.contexts[keep]
        return pruned

    @torch.no_grad()
    def realign(self, projector) -> None:
        """Re-project every stored key through a learned old→new drift map (opt-in LDC).

        Learnable Drift Compensation (Gomez-Villa et al. 2024, "Exemplar-free
        Continual Representation Learning via Learnable Drift Compensation",
        https://arxiv.org/abs/2407.08536): when the encoder keeps training the
        feature space *drifts*, so a key written under the old encoder no longer
        lands where the same input now encodes — the never-forget vote starts
        mis-targeting. LDC fits a small linear projector mapping old→new encoder
        features and applies it to the stored prototypes/keys so they track the
        moving representation instead of being re-collected.

        키마다(per-key) 노름은 :meth:`write` 와 똑같이 보존한다 — only the *direction*
        is realigned (projector ∘ normalize), the conviction-encoding magnitude is
        carried over unchanged. With the default agent (``drift_realign=False``)
        this is never called, so semantics are unchanged.
        """
        if len(self) == 0:
            return
        norms = self.keys.norm(dim=1, keepdim=True)
        self.keys = F.normalize(projector(self.keys), dim=1) * norms

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

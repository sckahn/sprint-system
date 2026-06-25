"""Mixture-of-Experts with budget-priced, variable top-k routing (§4.3).

Each activated expert deducts from the budget, so the agent has an economic
incentive *not* to fire every expert — load balancing emerges from cost rather
than from an auxiliary loss alone. We still expose a load-balance loss to guard
against expert collapse (Phase 2: "expert collapse avoidance").
"""
from __future__ import annotations

from dataclasses import dataclass

import torch
import torch.nn as nn
import torch.nn.functional as F

from .config import MoEConfig


class Expert(nn.Module):
    def __init__(self, dim: int, hidden: int):
        super().__init__()
        self.net = nn.Sequential(
            nn.Linear(dim, hidden), nn.GELU(), nn.Linear(hidden, dim)
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.net(x)


@dataclass
class MoEOutput:
    y: torch.Tensor                 # (..., dim)
    experts_used: int               # number of distinct experts fired (for budget)
    load_balance_loss: torch.Tensor
    gate_weights: torch.Tensor      # (..., n_experts) full routing distribution
    last_top_idx: torch.Tensor      # (B, k) selected expert indices (for bias update)


class MoELayer(nn.Module):
    def __init__(self, cfg: MoEConfig):
        super().__init__()
        self.cfg = cfg
        self.router = nn.Linear(cfg.dim, cfg.n_experts)
        self.experts = nn.ModuleList(
            [Expert(cfg.dim, cfg.hidden) for _ in range(cfg.n_experts)]
        )
        # Auxiliary-loss-free load-balancing bias (DeepSeek, arXiv:2408.15664v1).
        # A gradient-free, per-expert bias added to the SELECTION scores only.
        # Starts at zero, so with loss_free_balance=False it never touches routing.
        self.register_buffer("expert_bias", torch.zeros(cfg.n_experts))

    def forward(self, x: torch.Tensor, top_k: int | None = None) -> MoEOutput:
        k = top_k or self.cfg.top_k
        k = min(k, self.cfg.n_experts)
        single = x.dim() == 1
        if single:
            x = x.unsqueeze(0)

        logits = self.router(x)                                # (B, E)
        full = F.softmax(logits, dim=-1)                       # OUTPUT gating distribution
        if self.cfg.loss_free_balance:
            # Auxiliary-loss-free balancing (arXiv:2408.15664v1): the per-expert
            # bias steers SELECTION only, never the output gate weights. We pick
            # top-k on the biased scores, then gather UNBIASED weights from `full`
            # so the output magnitude is exactly the no-bias result.
            sel = logits + self.expert_bias                    # (B, E) selection scores
            top_idx = torch.topk(sel, k, dim=-1).indices       # (B, k)
            top_val = torch.gather(full, -1, top_idx)          # unbiased gate weights
        else:
            top_val, top_idx = torch.topk(full, k, dim=-1)      # (B, k)
        top_w = top_val / (top_val.sum(-1, keepdim=True) + 1e-8)

        y = torch.zeros_like(x)
        for slot in range(k):
            idx = top_idx[:, slot]                              # (B,)
            w = top_w[:, slot].unsqueeze(-1)                    # (B, 1)
            for e in range(self.cfg.n_experts):
                m = idx == e
                if m.any():
                    y[m] += w[m] * self.experts[e](x[m])

        # Load-balance loss (Switch-Transformer style): importance × load.
        importance = full.mean(0)                              # (E,)
        load = torch.zeros(self.cfg.n_experts, device=x.device)
        for e in range(self.cfg.n_experts):
            load[e] = (top_idx == e).float().mean()
        lb = self.cfg.n_experts * (importance * load).sum() * self.cfg.load_balance_coef

        experts_used = int(torch.unique(top_idx).numel())
        last_top_idx = top_idx.detach()                        # (B, k) for bias update
        if single:
            y = y.squeeze(0)
            full = full.squeeze(0)
        return MoEOutput(y, experts_used, lb, full, last_top_idx)

    @torch.no_grad()
    def update_bias(self, top_idx: torch.Tensor, u: float | None = None) -> None:
        """Gradient-free routing-bias update (DeepSeek, arXiv:2408.15664v1, §3).

        Per-expert load is the fraction of selection slots that landed on each
        expert; the bias moves each expert toward the mean load by a fixed step:

            err = mean_load − load
            b_i += u · sign(err_i)

        So overloaded experts (load > mean) get a lower bias and starved experts a
        higher one, with no gradient flowing into the objective. ``top_idx`` is the
        ``(B, k)`` selection from :meth:`forward` (a single sample is ``(1, k)``).
        """
        u = self.cfg.bias_update_u if u is None else u
        idx = top_idx.reshape(-1)                              # flatten (B*k,)
        load = torch.zeros(self.cfg.n_experts, device=idx.device)
        for e in range(self.cfg.n_experts):
            load[e] = (idx == e).float().mean()
        err = load.mean() - load
        self.expert_bias += u * torch.sign(err)

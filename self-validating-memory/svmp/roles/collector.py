"""Collector: validates the Architect's hypothesis against existing knowledge (§3).

The Collector is the "discriminator" of the adversarial loop. It scores how well a
hypothesis is *supported* by what the vault already holds. Low support means the
hypothesis is either novel (needs external verification) or wrong.
"""
from __future__ import annotations

import torch
import torch.nn as nn

from ..config import RoleConfig


class Collector(nn.Module):
    def __init__(self, cfg: RoleConfig):
        super().__init__()
        self.cfg = cfg
        self.net = nn.Sequential(
            nn.Linear(cfg.dim * 2, cfg.hidden), nn.GELU(),
            nn.Linear(cfg.hidden, 1),
        )

    def forward(self, hypothesis: torch.Tensor,
                retrieved: torch.Tensor) -> torch.Tensor:
        """Return a support probability in [0, 1] for the hypothesis."""
        h = torch.cat([hypothesis.flatten(), retrieved.flatten()])
        return torch.sigmoid(self.net(h)).squeeze()

    def agrees(self, hypothesis: torch.Tensor, retrieved: torch.Tensor) -> bool:
        return float(self(hypothesis, retrieved)) >= self.cfg.collector_agree_threshold

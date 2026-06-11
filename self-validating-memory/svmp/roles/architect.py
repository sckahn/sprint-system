"""Architect: generates structural hypotheses about knowledge connections (§3).

Given the current input embedding and what the vault retrieved, the Architect
proposes a *hypothesis embedding* — its best guess at the latent structure that
connects the input to known knowledge. This is the "generator" half of the
GAN-like loop; the Collector is the discriminator.
"""
from __future__ import annotations

import torch
import torch.nn as nn

from ..config import RoleConfig


class Architect(nn.Module):
    def __init__(self, cfg: RoleConfig):
        super().__init__()
        self.net = nn.Sequential(
            nn.Linear(cfg.dim * 2, cfg.hidden), nn.GELU(),
            nn.Linear(cfg.hidden, cfg.dim),
        )

    def forward(self, x: torch.Tensor, retrieved: torch.Tensor) -> torch.Tensor:
        """Return a hypothesis embedding linking ``x`` to ``retrieved``."""
        h = torch.cat([x.flatten(), retrieved.flatten()])
        return self.net(h)

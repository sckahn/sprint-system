"""SelfValidatingModel: the neural core (§7).

A pure ``nn.Module`` that turns an input into a decision, fusing three sources of
information:

    encoder(x)  ─┐
                 ├─ fuse ─→ MoE ─→ decision head ─→ logits
    vault value ─┘                         └────→ calibration head ─→ confidence

The orchestration (budget accounting, vault read/write, adversarial roles,
three-factor weight updates) lives in :class:`svmp.agent.SelfValidatingAgent`;
this module is just the differentiable structure.
"""
from __future__ import annotations

from dataclasses import dataclass

import torch
import torch.nn as nn

from .config import SVMPConfig
from .moe import MoELayer, MoEOutput


@dataclass
class ModelOutput:
    logits: torch.Tensor         # (n_classes,)
    confidence: torch.Tensor     # scalar in [0, 1]
    feature: torch.Tensor        # (dim,) decision feature (pre of decision head)
    moe: MoEOutput


class SelfValidatingModel(nn.Module):
    def __init__(self, cfg: SVMPConfig, input_dim: int):
        super().__init__()
        self.cfg = cfg
        d = cfg.dim
        self.encoder = nn.Sequential(nn.Linear(input_dim, d), nn.GELU())
        self.fuse = nn.Linear(d * 2, d)
        self.moe = MoELayer(cfg.moe)
        # Decision head is a plain Linear so the three-factor rule can write to it.
        self.decision = nn.Linear(d, cfg.n_classes)
        from .calibration import CalibrationHead
        self.calib = CalibrationHead(cfg.n_classes)

    def forward(self, x: torch.Tensor, retrieved: torch.Tensor,
                top_k: int | None = None) -> ModelOutput:
        enc = self.encoder(x.flatten())
        fused = self.fuse(torch.cat([enc, retrieved.flatten()]))
        moe = self.moe(fused, top_k=top_k)
        feature = torch.relu(moe.y)              # pre-activation for decision head
        logits = self.decision(feature)
        confidence = self.calib(logits)
        return ModelOutput(logits, confidence, feature, moe)

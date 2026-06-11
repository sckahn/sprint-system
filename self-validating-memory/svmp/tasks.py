"""Synthetic tasks for exercising the system end-to-end (§5 Phase 1/2).

These are deliberately small, fully synthetic, and dependency-free so the whole
architecture runs in seconds on CPU. They are *scaffolding* to demonstrate the
learning dynamics (accuracy ↑, calibration error ↓, vault growth, budget
pressure), not benchmark tasks.
"""
from __future__ import annotations

import torch


class CalibrationBanditTask:
    """Prototype-classification with variable ambiguity (Phase 1).

    Each class has a fixed prototype. A sample is a prototype plus noise; the
    noise scale varies per sample, so some inputs are inherently ambiguous. A
    *calibrated* agent should be confident on clean samples and hedge on noisy
    ones — exactly what the Jeopardy betting reward pressures it toward.
    """

    def __init__(self, n_classes: int = 4, feature_dim: int = 16,
                 seed: int = 0):
        self.n_classes = n_classes
        self.feature_dim = feature_dim
        g = torch.Generator().manual_seed(seed)
        self.prototypes = torch.randn(n_classes, feature_dim, generator=g)
        self.gen = torch.Generator().manual_seed(seed + 1)

    def sample(self) -> tuple[torch.Tensor, int]:
        target = int(torch.randint(self.n_classes, (1,), generator=self.gen))
        # Ambiguity: signal strength uniformly in [0.3, 1.0].
        signal = 0.3 + 0.7 * float(torch.rand(1, generator=self.gen))
        noise = torch.randn(self.feature_dim, generator=self.gen) * (1 - signal)
        x = signal * self.prototypes[target] + noise
        return x, target


class PositionalOrderingTask:
    """Structural task where reward depends on relational position (Phase 2/§4.5).

    Targets must respect a hidden total order. A locally correct class can still
    be penalised if it breaks the order relative to the previous action — this is
    what ``RewardTopology(mode="positional")`` scores.
    """

    def __init__(self, n_classes: int = 4, feature_dim: int = 16, seed: int = 0):
        self.n_classes = n_classes
        self.feature_dim = feature_dim
        g = torch.Generator().manual_seed(seed)
        self.prototypes = torch.randn(n_classes, feature_dim, generator=g)
        self.order_target = torch.randperm(n_classes, generator=g).tolist()
        self.gen = torch.Generator().manual_seed(seed + 1)
        self._i = 0

    def sample(self) -> tuple[torch.Tensor, int, list[int]]:
        # Walk through the hidden order so structure is learnable.
        target = self.order_target[self._i % self.n_classes]
        self._i += 1
        noise = torch.randn(self.feature_dim, generator=self.gen) * 0.3
        x = self.prototypes[target] + noise
        return x, target, self.order_target

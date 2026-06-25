"""Synthetic tasks for exercising the system end-to-end (§5 Phase 1/2).

These are deliberately small, fully synthetic, and dependency-free so the whole
architecture runs in seconds on CPU. They are *scaffolding* to demonstrate the
learning dynamics (accuracy ↑, calibration error ↓, vault growth, budget
pressure), not benchmark tasks.
"""
from __future__ import annotations

import torch


class SplitContinualTask:
    """Class-incremental continual learning (for the catastrophic-forgetting study).

    ``n_classes`` are split into ``n_tasks`` disjoint groups. Task ``t`` emits only
    its class subset, so the agent sees a non-stationary stream A→B→C…. Each class
    has a fixed prototype, so a class re-appears in the same input region whenever
    it is evaluated — which is what lets an external memory (the vault) retain it
    while the shared decision head drifts onto later tasks.
    """

    def __init__(self, n_classes: int = 8, n_tasks: int = 2,
                 feature_dim: int = 16, seed: int = 0):
        if n_classes % n_tasks != 0:
            raise ValueError("n_classes must be divisible by n_tasks")
        self.n_classes = n_classes
        self.n_tasks = n_tasks
        self.feature_dim = feature_dim
        per = n_classes // n_tasks
        self.task_classes = [list(range(t * per, (t + 1) * per))
                             for t in range(n_tasks)]
        g = torch.Generator().manual_seed(seed)
        self.prototypes = torch.randn(n_classes, feature_dim, generator=g)
        self.gen = torch.Generator().manual_seed(seed + 1)

    def sample(self, task_idx: int) -> tuple[torch.Tensor, int]:
        classes = self.task_classes[task_idx]
        c = classes[int(torch.randint(len(classes), (1,), generator=self.gen))]
        signal = 0.5 + 0.5 * float(torch.rand(1, generator=self.gen))
        noise = torch.randn(self.feature_dim, generator=self.gen) * (1 - signal)
        x = signal * self.prototypes[c] + noise
        return x, c


class PermutedLabelTask:
    """Domain-incremental continual learning with CONFLICTING labels.

    The adversarial counterpart to :class:`SplitContinualTask`. Every task draws
    from the *same* input regions (shared prototypes), but each task applies a
    different label permutation, so input region ``r`` is class ``perm[t][r]`` in
    task ``t`` — the *same input* has *different* correct answers across tasks.

    This is the breaking case for the Phase-6 forgetting fix (``LabelVault``): a
    context-free input→label memory cannot be right for two tasks at once, and the
    shared, re-mapped regions force the encoder to drift (the two assumptions the
    fix relies on). Used by ``examples/experiment_forgetting_limits.py``.
    """

    def __init__(self, n_classes: int = 8, n_tasks: int = 2,
                 feature_dim: int = 16, seed: int = 0):
        self.n_classes = n_classes
        self.n_tasks = n_tasks
        self.feature_dim = feature_dim
        g = torch.Generator().manual_seed(seed)
        self.prototypes = torch.randn(n_classes, feature_dim, generator=g)
        # Task 0 is the identity map; later tasks permute the labels of the same
        # regions, so a region's correct answer conflicts across tasks.
        self.perms = [list(range(n_classes))]
        for _ in range(1, n_tasks):
            self.perms.append(torch.randperm(n_classes, generator=g).tolist())
        self.gen = torch.Generator().manual_seed(seed + 1)

    def sample(self, task_idx: int) -> tuple[torch.Tensor, int]:
        region = int(torch.randint(self.n_classes, (1,), generator=self.gen))
        signal = 0.5 + 0.5 * float(torch.rand(1, generator=self.gen))
        noise = torch.randn(self.feature_dim, generator=self.gen) * (1 - signal)
        x = signal * self.prototypes[region] + noise
        return x, self.perms[task_idx][region]


class ConceptDriftTask:
    """Holistic continual learning under *concept drift* (for the AMR study).

    Like :class:`PermutedLabelTask` every sample is drawn from one of a fixed set
    of input regions (shared prototypes), but here a subset of regions is
    PERMANENTLY remapped to new classes at a single known ``flip_step`` — a genuine
    new regime, not a reversible A→B→A. Before the flip region ``r`` is class
    ``base[r]``; after it the drifted regions take ``flipped[r]`` and never revert,
    so there is no recurring context to tag (distinct from ``PermutedLabelTask``).

    This is the setting Adaptive Memory Realignment targets (Ashrafee et al. 2025,
    https://arxiv.org/abs/2507.02310): a never-forget memory keeps voting the stale
    pre-drift label for the flipped regions, so the agent stays stuck unless those
    outdated entries are selectively realigned. ``drift_regions`` (default: the
    first half of the regions) flip; the rest keep their original mapping and serve
    as the unflipped-retention control.
    """

    def __init__(self, n_classes: int = 8, feature_dim: int = 16,
                 flip_step: int = 1500, drift_frac: float = 0.5, seed: int = 0):
        self.n_classes = n_classes
        self.feature_dim = feature_dim
        self.flip_step = flip_step
        g = torch.Generator().manual_seed(seed)
        self.prototypes = torch.randn(n_classes, feature_dim, generator=g)
        # Base mapping is the identity; the drift remaps a subset of regions by a
        # fixed derangement-ish permutation so the flipped answer truly differs.
        self.base = list(range(n_classes))
        shift = list(range(1, n_classes)) + [0]          # r -> (r+1) mod n
        n_drift = max(1, int(n_classes * drift_frac))
        self.drift_regions = list(range(n_drift))
        self.flipped = list(self.base)
        for r in self.drift_regions:
            self.flipped[r] = shift[r]
        self.unflipped_regions = [r for r in range(n_classes)
                                  if r not in self.drift_regions]
        self.gen = torch.Generator().manual_seed(seed + 1)
        self._step = 0

    def _label(self, region: int) -> int:
        mapping = self.flipped if self._step >= self.flip_step else self.base
        return mapping[region]

    def sample(self) -> tuple[torch.Tensor, int]:
        region = int(torch.randint(self.n_classes, (1,), generator=self.gen))
        signal = 0.5 + 0.5 * float(torch.rand(1, generator=self.gen))
        noise = torch.randn(self.feature_dim, generator=self.gen) * (1 - signal)
        x = signal * self.prototypes[region] + noise
        y = self._label(region)
        self._step += 1
        return x, y

    def sample_region(self, region: int) -> tuple[torch.Tensor, int]:
        """Draw an input from a *specific* region at the current drift phase.

        Used by the AMR experiment to measure per-region recovery/retention without
        advancing the drift clock (``_step`` is left untouched).
        """
        signal = 0.5 + 0.5 * float(torch.rand(1, generator=self.gen))
        noise = torch.randn(self.feature_dim, generator=self.gen) * (1 - signal)
        x = signal * self.prototypes[region] + noise
        return x, self._label(region)


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


class RealDigitsTask:
    """Real-data task: sklearn handwritten digits (1797 images, 10 classes).

    Streams shuffled training samples for online learning and keeps a held-out
    test split for frozen evaluation. Requires ``scikit-learn`` (optional dep;
    imported lazily so the core package stays torch-only).
    """

    def __init__(self, seed: int = 0, test_frac: float = 0.25):
        from sklearn.datasets import load_digits  # lazy optional import
        d = load_digits()
        X = torch.tensor(d.data, dtype=torch.float32) / 16.0  # features in [0,1]
        y = torch.tensor(d.target, dtype=torch.long)
        g = torch.Generator().manual_seed(seed)
        perm = torch.randperm(len(X), generator=g)
        n_test = int(len(X) * test_frac)
        self.X_test, self.y_test = X[perm[:n_test]], y[perm[:n_test]]
        self.X_train, self.y_train = X[perm[n_test:]], y[perm[n_test:]]
        self.n_classes = 10
        self.feature_dim = X.shape[1]
        self.gen = torch.Generator().manual_seed(seed + 1)

    def sample(self) -> tuple[torch.Tensor, int]:
        i = int(torch.randint(len(self.X_train), (1,), generator=self.gen))
        return self.X_train[i], int(self.y_train[i])

    def class_prototypes(self) -> torch.Tensor:
        """Mean embedding per class (used to build a retrieval corpus)."""
        return torch.stack([self.X_train[self.y_train == c].mean(0)
                            for c in range(self.n_classes)])


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

"""Task-free context inference from the reward stream (Phase-6 part 4).

The context-keyed ``LabelVault`` resolves conflicting label mappings *if* it is
told which task it is in. But in domain-incremental learning with an identical
input distribution across tasks (``PermutedLabelTask``), the task identity is not
observable from the input at all — only the *reward contingency* changes. So a
task-free agent must infer context from its own prediction-error dynamics: when
it suddenly starts being punished on inputs it used to get right, the regime has
shifted and a new context should be allocated.

``ContextInferrer`` is a minimal change-point detector over the reward stream. It
emits a one-hot context vector and rotates to a fresh slot when a sustained
accuracy collapse signals a regime change. It is deliberately simple (forward-only
slot allocation): it segments an A→B→… stream into distinct contexts without a
task oracle, which is what the vault's context key needs. Recognising a *returned*
context (B→A) would require matching the error pattern to past slots — left as
future work and noted honestly in the experiment.
"""
from __future__ import annotations

import torch


class ContextInferrer:
    def __init__(self, ctx_dim: int = 6, fast: float = 0.2, slow: float = 0.02,
                 drop: float = 0.3, warmup: int = 80, established: float = 0.55):
        self.ctx_dim = ctx_dim
        self.afast = fast
        self.aslow = slow
        self.drop = drop
        self.warmup = warmup
        self.established = established
        self.reset()

    def reset(self) -> None:
        self.slot = 0
        self.fast: float | None = None
        self.slow: float | None = None
        self.t_since_switch = 0

    def context(self) -> torch.Tensor:
        v = torch.zeros(self.ctx_dim)
        v[self.slot] = 1.0
        return v

    def observe(self, reward01: float) -> bool:
        """Feed the latest outcome (1.0 correct, 0.0 wrong). Returns True on switch.

        A regime change is declared only when we *were* doing well on the current
        context (slow baseline established above ``established``) and the fast EMA
        then collapses well below it. Gating on a high baseline avoids false
        switches during the noisy learning phase, when accuracy is low but rising.
        """
        if self.fast is None:
            self.fast = self.slow = reward01
        self.fast += self.afast * (reward01 - self.fast)
        self.slow += self.aslow * (reward01 - self.slow)
        self.t_since_switch += 1
        if (self.t_since_switch > self.warmup
                and self.slow > self.established
                and self.fast < self.slow - self.drop
                and self.slot < self.ctx_dim - 1):
            self.slot += 1
            self.t_since_switch = 0
            self.fast = self.slow = reward01     # rebaseline on the new regime
            return True
        return False

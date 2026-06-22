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
accuracy collapse signals a regime change. It segments an A→B→… stream into
distinct contexts without a task oracle. ``RecognizingContextManager`` extends
this with reward-probing so a *returned* context (B→A) re-selects its original
slot instead of allocating a new one (`experiment_context_recognition.py`).
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


class RecognizingContextManager:
    """Context manager that RE-RECOGNISES a returned context via reward probing.

    The forward-only :class:`ContextInferrer` allocates a *fresh* slot at every
    regime change, so revisiting an earlier task (B→A) lands on an empty context
    and forgets it again. Because conflicting tasks share the same input regions,
    context is observable only through reward — there is no input-only signal to
    re-identify the old task. So on a detected collapse this manager *probes* each
    known slot (plus one fresh slot) for a short window and adopts whichever yields
    the best reward, re-selecting an earlier task's original slot when it returns.

    Slot ids are allocated in first-encounter order (0, 1, …); the experiment tags
    the memory in the same order, so a probed slot id refers to the same context.
    """

    def __init__(self, ctx_dim: int = 6, probe_steps: int = 25, fast: float = 0.2,
                 slow: float = 0.02, drop: float = 0.3, warmup: int = 80,
                 established: float = 0.55, auto_detect: bool = True):
        self.ctx_dim = ctx_dim
        self.probe_steps = probe_steps
        self.afast = fast
        self.aslow = slow
        self.drop = drop
        self.warmup = warmup
        self.established = established
        self.auto_detect = auto_detect          # False ⇒ search only on force_search()
        self.reset()

    def reset(self) -> None:
        self.slot = 0
        self.n_known = 1
        self.mode = "normal"
        self.probe_cost = 0
        self._reset_ema()
        self._cands: list[int] = []
        self._ci = 0
        self._pcount = 0
        self._psum = 0.0
        self._scores: dict[int, float] = {}

    def _reset_ema(self) -> None:
        self.fast: float | None = None
        self.slow: float | None = None
        self.t = 0

    def context(self) -> torch.Tensor:
        v = torch.zeros(self.ctx_dim)
        v[self.slot] = 1.0
        return v

    def _detect_collapse(self, r: float) -> bool:
        if self.fast is None:
            self.fast = self.slow = r
        self.fast += self.afast * (r - self.fast)
        self.slow += self.aslow * (r - self.slow)
        self.t += 1
        return (self.t > self.warmup and self.slow > self.established
                and self.fast < self.slow - self.drop)

    def force_search(self) -> None:
        """Begin a probing search now (e.g. on an externally signalled boundary),
        independent of the reward-collapse detector."""
        if self.mode == "normal":
            self._start_search()

    def _start_search(self) -> None:
        self.mode = "search"
        cands = list(range(self.n_known))
        if self.n_known < self.ctx_dim:
            cands.append(self.n_known)        # one fresh slot
        self._cands = cands
        self._scores = {}
        self._ci = 0
        self._pcount = 0
        self._psum = 0.0
        self.slot = cands[0]

    def observe(self, reward01: float) -> None:
        """Feed the latest outcome; drives change detection and probing search."""
        if self.mode == "normal":
            if self.auto_detect and self._detect_collapse(reward01):
                self._start_search()
            return
        # search mode: accumulate reward for the candidate currently in use
        self.probe_cost += 1
        self._psum += reward01
        self._pcount += 1
        if self._pcount < self.probe_steps:
            return
        self._scores[self._cands[self._ci]] = self._psum / self._pcount
        self._ci += 1
        if self._ci < len(self._cands):
            self.slot = self._cands[self._ci]
            self._pcount = 0
            self._psum = 0.0
        else:                                  # finished probing → adopt the best
            best = max(self._scores, key=self._scores.get)
            self.slot = best
            if best == self.n_known:
                self.n_known += 1
            self.mode = "normal"
            self._reset_ema()

"""Re-recognising a returned context (Phase-6 part 5).

Part 4 resolved conflicting-label forgetting with a context key, but its forward-
only ``ContextInferrer`` allocates a *fresh* slot at every regime change — so when
an earlier task RETURNS (B→A) it lands on an empty context and forgets it again.

This isolates the re-recognition question. Detecting *that* a regime changed was
part 4's concern (a reward-collapse detector; task-free but noisy). Part 5 asks the
orthogonal question — *which* context is it? — so we hand each provider the change-
point (a boundary occurred) but never the task identity, and measure whether it
re-selects the right past context on a revisiting stream A→B→A→B. A full system
composes part-4 detection with part-5 recognition.

The memory is tagged cleanly by training with oracle context tags (so this tests
recognition, not segmentation). Because conflicting tasks share the same input
regions, context is observable only through reward — there is no input-only signal
(the same region exists under every context). So ``RecognizingContextManager``
probes each known slot (plus a fresh one) for a short window at the boundary and
adopts the best-rewarded one.

Eval is prequential (predict→observe, no weight learning). We compare per segment:
  * oracle    — the true task id each segment (upper bound).
  * forward    — allocate a fresh slot at every boundary (revisits hit empty slots).
  * recognise  — RecognizingContextManager (reward-probing re-selection).

    PYTHONPATH=. python examples/experiment_context_recognition.py
"""
from __future__ import annotations

import statistics as st

import torch

from svmp.config import SVMPConfig
from svmp.agent import SelfValidatingAgent
from svmp.context import RecognizingContextManager
from svmp.tasks import PermutedLabelTask

SEEDS = [0, 1, 2, 3]
STEPS = 2500
EVAL_PER_SEG = 600
CTX_DIM = 6
VOTE_SCALE = 10.0
VISIT_ORDER = [0, 1, 0, 1]          # A → B → A → B


def onehot(i, n=CTX_DIM):
    v = torch.zeros(n)
    v[i] = 1.0
    return v


def train_with_oracle_tags(agent, task):
    """Tag the memory cleanly: task t's verified facts get context slot t."""
    for t in range(task.n_tasks):
        for _ in range(STEPS):
            x, y = task.sample(t)
            agent.step(x, y, context=onehot(t))


# --- eval-time context providers. boundary() signals a regime change occurred
#     (no identity); only the oracle is told which task it is.
class _Oracle:
    def boundary(self, t): self.slot = t
    def context(self): return onehot(self.slot)
    def observe(self, r): pass
    cost = 0


class _Forward:
    def __init__(self): self.slot = 0; self.first = True
    def boundary(self, t):
        if self.first: self.first = False           # first segment stays slot 0
        else: self.slot = min(self.slot + 1, CTX_DIM - 1)
    def context(self): return onehot(self.slot)
    def observe(self, r): pass
    cost = 0


class _Recognise:
    def __init__(self):
        self.mgr = RecognizingContextManager(ctx_dim=CTX_DIM, probe_steps=30,
                                             auto_detect=False)
        self.first = True
    def boundary(self, t):
        if self.first: self.first = False
        else: self.mgr.force_search()               # probe to re-recognise
    def context(self): return self.mgr.context()
    def observe(self, r): self.mgr.observe(r)
    @property
    def cost(self): return self.mgr.probe_cost


def prequential_revisit(agent, task, provider):
    """Stream A→B→A→B; predict→observe, no learning. Returns per-segment accuracy."""
    seg_acc = []
    for t in VISIT_ORDER:
        provider.boundary(t)
        correct = 0
        for _ in range(EVAL_PER_SEG):
            x, y = task.sample(t)
            ok = int(agent.predict(x, context=provider.context()) == y)
            correct += ok
            provider.observe(1.0 if ok else 0.0)
        seg_acc.append(correct / EVAL_PER_SEG)
    return seg_acc


def run(mode, seed):
    cfg = SVMPConfig(seed=seed, n_classes=8)
    agent = SelfValidatingAgent(cfg, 16, direct_vote=True,
                                vote_scale=VOTE_SCALE, ctx_dim=CTX_DIM)
    task = PermutedLabelTask(8, 2, 16, seed=seed)
    train_with_oracle_tags(agent, task)
    provider = {"oracle": _Oracle, "forward": _Forward,
                "recognise": _Recognise}[mode]()
    seg = prequential_revisit(agent, task, provider)
    return seg, provider.cost


def main():
    print("Re-recognising a returned context (Permuted, A→B→A→B, n=4, "
          "prequential)\n")
    print(f"  {'mode':10s} |   A1    B1    A2*   B2*  | revisit mean | probe")
    agg = {}
    for mode in ("oracle", "forward", "recognise"):
        segs, costs = zip(*[run(mode, s) for s in SEEDS])
        m = [st.mean(s[i] for s in segs) for i in range(4)]
        revisit = st.mean([m[2], m[3]])          # the returned segments
        cost = st.mean(costs)
        agg[mode] = (m, revisit)
        print(f"  {mode:10s} | {m[0]:.3f} {m[1]:.3f} {m[2]:.3f} {m[3]:.3f} "
              f"|    {revisit:.3f}     | {cost:.0f}")

    o, f, r = agg["oracle"][1], agg["forward"][1], agg["recognise"][1]
    print("\nReading (A2*/B2* are the RETURNED segments — the forgetting test):")
    print(f"  Forward inference forgets on return ({f:.2f} revisit mean): every "
          f"change-point spawns a\n  fresh empty slot, so the revisited task falls "
          f"back to the drifted model.")
    print(f"  Reward-probing re-recognition restores it to {r:.2f}, vs the oracle's "
          f"{o:.2f} — recovering\n  {(r - f) / (o - f) * 100:.0f}% of the gap, at the "
          f"cost of a short probe at each switch.")
    print("  This closes the part-4 limitation: with reward feedback the agent "
          "re-selects an")
    print("  earlier task's context instead of re-forgetting it. The residual gap "
          "is the probe")
    print("  transient (wrong context until the search locks on). Still no task id "
          "is used.")


if __name__ == "__main__":
    main()

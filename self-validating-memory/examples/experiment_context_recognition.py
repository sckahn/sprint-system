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
  * recognise  — boundary given, reward-probing re-selection (recognition ceiling).
  * auto       — fully task-free: NO boundary either; the manager's own reward-
                 collapse detector drives the probing search. Tests whether probing
                 *absorbs* the detector's noise (false alarms → cheap re-probes of
                 the current slot, not forgetting) rather than relying on a clean
                 boundary signal.

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


class _Auto:
    """Fully task-free: no boundary signal — the reward-collapse detector inside
    the manager triggers the probing search itself."""
    def __init__(self):
        self.mgr = RecognizingContextManager(ctx_dim=CTX_DIM, probe_steps=30,
                                             auto_detect=True, accept=0.6)
    def boundary(self, t): pass                      # no boundary is given
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
                "recognise": _Recognise, "auto": _Auto}[mode]()
    seg = prequential_revisit(agent, task, provider)
    return seg, provider.cost


def main():
    print("Re-recognising a returned context (Permuted, A→B→A→B, n=4, "
          "prequential)\n")
    print(f"  {'mode':10s} |   A1    B1    A2*   B2*  | revisit mean | probe")
    agg = {}
    for mode in ("oracle", "forward", "recognise", "auto"):
        segs, costs = zip(*[run(mode, s) for s in SEEDS])
        m = [st.mean(s[i] for s in segs) for i in range(4)]
        revisit = st.mean([m[2], m[3]])          # the returned segments
        cost = st.mean(costs)
        agg[mode] = (revisit, cost)
        label = mode + (" (no bndry)" if mode == "auto" else "")
        print(f"  {label:10s} | {m[0]:.3f} {m[1]:.3f} {m[2]:.3f} {m[3]:.3f} "
              f"|    {revisit:.3f}     | {cost:.0f}")

    o = agg["oracle"][0]; f = agg["forward"][0]
    r = agg["recognise"][0]; a = agg["auto"][0]
    print("\nReading (A2*/B2* are the RETURNED segments — the forgetting test):")
    print(f"  Forward forgets on return ({f:.2f}): every boundary spawns a fresh "
          f"empty slot, so the\n  revisited task falls back to the drifted model.")
    print(f"  Given the boundary, reward-probing re-recognition restores it to "
          f"{r:.2f} (recovering\n  {(r - f) / (o - f) * 100:.0f}% of the gap to the "
          f"oracle {o:.2f}) — no task id, just reward.")
    print(f"  Fully task-free (NO boundary either), the manager's own collapse "
          f"detector drives the\n  probing and still reaches {a:.2f} — well above "
          f"forward's {f:.2f}. Probing ABSORBS the")
    print(f"  detector's false alarms: a spurious trigger early-accepts the current "
          f"slot after one\n  window (cheap re-probe), so noise costs probe steps, "
          f"not forgetting. The residual gap")
    print(f"  to the {r:.2f} recognition ceiling is detection cost — latency to fire "
          f"plus leftover\n  false-alarm probing. Recognition adds the most; "
          f"detection is now the bottleneck.")


if __name__ == "__main__":
    main()
